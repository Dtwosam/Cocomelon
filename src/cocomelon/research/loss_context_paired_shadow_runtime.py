from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from cocomelon.domain.features import OpportunityRank
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.continuous_paper_opening_rank import (
    LatestCoarseRankTracker,
)
from cocomelon.research.loss_context_paired_portfolio_shadow import (
    LOSS_CONTEXT_PAIRED_SHADOW_STATE_FILENAME,
    LossContextPairedPortfolioShadow,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)

DEFAULT_MAX_QUEUE_SIZE: Final = 16_384
DEFAULT_CONTROL_TIMEOUT_SECONDS: Final = 30.0


class LossContextPairedShadowRuntimeError(RuntimeError):
    pass


class _PairedShadowLike(Protocol):
    def on_record(
        self,
        record: ReplayRecord,
        now_ms: int,
        *,
        evaluate_decisions: bool = True,
    ) -> None: ...

    def reconcile_markets(
        self,
        selected_markets: Sequence[MarketId],
    ) -> None: ...

    @property
    def protected_open_markets(self) -> tuple[MarketId, ...]: ...

    def mark_restore_warmup_complete(self) -> None: ...

    def checkpoint(self, *, end_ms: int) -> dict[str, object]: ...

    def summary_payload(self, *, end_ms: int) -> dict[str, object]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class _RecordCommand:
    record: ReplayRecord
    now_ms: int
    evaluate_decisions: bool


@dataclass(frozen=True, slots=True)
class _RankCommand:
    ranks: tuple[OpportunityRank, ...]
    observed_at_ms: int


@dataclass(frozen=True, slots=True)
class _ReconcileCommand:
    markets: tuple[MarketId, ...]


@dataclass(frozen=True, slots=True)
class _ProtectedMarketsCommand:
    future: Future[dict[str, object]]


@dataclass(frozen=True, slots=True)
class _WarmupCompleteCommand:
    pass


@dataclass(frozen=True, slots=True)
class _CheckpointCommand:
    end_ms: int
    future: Future[dict[str, object]]


@dataclass(frozen=True, slots=True)
class _SummaryCommand:
    end_ms: int
    future: Future[dict[str, object]]


@dataclass(frozen=True, slots=True)
class _CloseCommand:
    future: Future[None]


_Command = (
    _RecordCommand
    | _RankCommand
    | _ReconcileCommand
    | _ProtectedMarketsCommand
    | _WarmupCompleteCommand
    | _CheckpointCommand
    | _SummaryCommand
    | _CloseCommand
)


class LossContextPairedShadowRuntime:
    """Thread-owned bounded actor for the paired portfolio shadow.

    Active paper only performs bounded non-blocking queue submissions.
    Paired replay, SQLite, checkpoint and summary work lives on a dedicated
    thread. Overflow or shadow failure disables only this research lane.
    """

    def __init__(
        self,
        *,
        freeze: LossContextPortfolioShadowFreeze,
        replay_config: BaselineReplayConfig,
        selected_markets: Sequence[MarketId],
        state_root: str | Path,
        startup_timestamp_ms: int,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        shadow_factory: type[LossContextPairedPortfolioShadow] = (
            LossContextPairedPortfolioShadow
        ),
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        if startup_timestamp_ms < 0:
            raise ValueError("startup_timestamp_ms must be non-negative")
        markets = tuple(
            sorted(selected_markets, key=lambda item: item.canonical)
        )
        if not markets:
            raise ValueError("selected_markets must not be empty")
        self._freeze = freeze
        self._replay_config = replay_config
        self._markets = markets
        self._state_root = Path(state_root)
        self._restore_markets = self._checkpoint_markets_or_default(
            self._state_root,
            markets,
        )
        self._startup_timestamp_ms = startup_timestamp_ms
        self._shadow_factory = shadow_factory
        self._queue: queue.Queue[_Command] = queue.Queue(
            maxsize=max_queue_size
        )
        self._lock = threading.Lock()
        self._failed = threading.Event()
        self._closed = threading.Event()
        self._initialized = threading.Event()
        self._error: str | None = None
        self._submitted_records = 0
        self._processed_records = 0
        self._submitted_rank_snapshots = 0
        self._processed_rank_snapshots = 0
        self._submitted_reconciles = 0
        self._processed_reconciles = 0
        self._queue_high_watermark = 0
        self._queue_overflows = 0
        self._warmup_complete_submitted = False
        self._warmup_complete_processed = False
        self._checkpoint_count = 0
        self._last_checkpoint_end_ms: int | None = None
        self._thread = threading.Thread(
            target=self._worker,
            name="cocomelon-loss-context-paired-shadow",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _checkpoint_markets_or_default(
        state_root: Path,
        default: tuple[MarketId, ...],
    ) -> tuple[MarketId, ...]:
        path = state_root / LOSS_CONTEXT_PAIRED_SHADOW_STATE_FILENAME
        if not path.exists():
            return default
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LossContextPairedShadowRuntimeError(
                "paired shadow checkpoint is unreadable"
            ) from exc
        if not isinstance(raw, dict):
            raise LossContextPairedShadowRuntimeError(
                "paired shadow checkpoint must be an object"
            )
        selected = raw.get("selected_markets")
        if not isinstance(selected, list) or not selected:
            raise LossContextPairedShadowRuntimeError(
                "paired shadow checkpoint selected markets are invalid"
            )
        markets: list[MarketId] = []
        for item in selected:
            if not isinstance(item, str) or not item:
                raise LossContextPairedShadowRuntimeError(
                    "paired shadow checkpoint market is invalid"
                )
            if ":" in item:
                dex, coin = item.split(":", 1)
                markets.append(MarketId(dex, coin))
            else:
                markets.append(MarketId("", item))
        return tuple(markets)

    @property
    def candidate_id(self) -> str:
        return self._freeze.candidate_id

    @staticmethod
    def _rank_ordinal_provider(
        tracker: LatestCoarseRankTracker,
        market: MarketId,
        at_ms: int,
    ) -> int | None:
        snapshot = tracker.snapshot_for_market(market, at_ms=at_ms)
        if snapshot is None:
            return None
        return snapshot[1].ordinal

    def _set_error(self, exc: BaseException | str) -> None:
        message = (
            exc
            if isinstance(exc, str)
            else f"{type(exc).__name__}: {exc}"
        )
        with self._lock:
            if self._error is None:
                self._error = str(message)
        self._failed.set()

    def _record_queue_depth(self) -> None:
        depth = self._queue.qsize()
        with self._lock:
            self._queue_high_watermark = max(
                self._queue_high_watermark,
                depth,
            )

    def _put_nowait(self, command: _Command) -> bool:
        if self._failed.is_set() or self._closed.is_set():
            return False
        try:
            self._queue.put_nowait(command)
        except queue.Full:
            with self._lock:
                self._queue_overflows += 1
            self._set_error(
                "LossContextPairedShadowRuntimeError: paired shadow queue overflow"
            )
            return False
        self._record_queue_depth()
        return True

    def submit_record(
        self,
        record: ReplayRecord,
        *,
        now_ms: int,
        evaluate_decisions: bool,
    ) -> bool:
        accepted = self._put_nowait(
            _RecordCommand(
                record=record,
                now_ms=now_ms,
                evaluate_decisions=evaluate_decisions,
            )
        )
        if accepted:
            with self._lock:
                self._submitted_records += 1
        return accepted

    def submit_rank_snapshot(
        self,
        ranks: Sequence[OpportunityRank],
        *,
        observed_at_ms: int,
    ) -> bool:
        accepted = self._put_nowait(
            _RankCommand(
                ranks=tuple(ranks),
                observed_at_ms=observed_at_ms,
            )
        )
        if accepted:
            with self._lock:
                self._submitted_rank_snapshots += 1
        return accepted

    def submit_reconcile(
        self,
        selected_markets: Sequence[MarketId],
    ) -> bool:
        markets = tuple(
            sorted(
                selected_markets,
                key=lambda item: item.canonical,
            )
        )
        accepted = self._put_nowait(
            _ReconcileCommand(markets=markets)
        )
        if accepted:
            with self._lock:
                self._submitted_reconciles += 1
        return accepted

    def submit_restore_warmup_complete(self) -> bool:
        accepted = self._put_nowait(_WarmupCompleteCommand())
        if accepted:
            with self._lock:
                self._warmup_complete_submitted = True
        return accepted

    def _worker(self) -> None:
        tracker = LatestCoarseRankTracker()
        shadow: _PairedShadowLike | None = None
        try:
            shadow = self._shadow_factory(
                freeze=self._freeze,
                replay_config=self._replay_config,
                selected_markets=self._restore_markets,
                state_root=self._state_root,
                startup_timestamp_ms=self._startup_timestamp_ms,
                rank_ordinal_provider=lambda market, at_ms: (
                    self._rank_ordinal_provider(
                        tracker,
                        market,
                        at_ms,
                    )
                ),
            )
            self._initialized.set()
            while True:
                command = self._queue.get()
                try:
                    if isinstance(command, _CloseCommand):
                        command.future.set_result(None)
                        return
                    if self._failed.is_set():
                        future = getattr(command, "future", None)
                        if isinstance(future, Future) and not future.done():
                            future.set_exception(
                                LossContextPairedShadowRuntimeError(
                                    self._error
                                    or "paired shadow runtime disabled"
                                )
                            )
                        continue
                    if isinstance(command, _RecordCommand):
                        shadow.on_record(
                            command.record,
                            command.now_ms,
                            evaluate_decisions=(
                                command.evaluate_decisions
                            ),
                        )
                        with self._lock:
                            self._processed_records += 1
                    elif isinstance(command, _RankCommand):
                        tracker.update(
                            command.ranks,
                            observed_at_ms=command.observed_at_ms,
                        )
                        with self._lock:
                            self._processed_rank_snapshots += 1
                    elif isinstance(command, _ReconcileCommand):
                        shadow.reconcile_markets(command.markets)
                        with self._lock:
                            self._processed_reconciles += 1
                    elif isinstance(command, _ProtectedMarketsCommand):
                        command.future.set_result({
                            "protected_markets": shadow.protected_open_markets,
                        })
                    elif isinstance(command, _WarmupCompleteCommand):
                        shadow.mark_restore_warmup_complete()
                        with self._lock:
                            self._warmup_complete_processed = True
                    elif isinstance(command, _CheckpointCommand):
                        payload = shadow.checkpoint(
                            end_ms=command.end_ms
                        )
                        with self._lock:
                            self._checkpoint_count += 1
                            self._last_checkpoint_end_ms = (
                                command.end_ms
                            )
                        command.future.set_result(payload)
                    elif isinstance(command, _SummaryCommand):
                        command.future.set_result(
                            shadow.summary_payload(
                                end_ms=command.end_ms
                            )
                        )
                except BaseException as exc:
                    future = getattr(command, "future", None)
                    if isinstance(future, Future) and not future.done():
                        future.set_exception(exc)
                    self._set_error(exc)
                finally:
                    self._queue.task_done()
        except BaseException as exc:
            self._set_error(exc)
            self._initialized.set()
        finally:
            if shadow is not None:
                try:
                    shadow.close()
                except BaseException as exc:
                    self._set_error(exc)
            self._closed.set()

    async def _request_control(
        self,
        command: _CheckpointCommand | _SummaryCommand | _ProtectedMarketsCommand,
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self._failed.is_set() or self._closed.is_set():
            raise LossContextPairedShadowRuntimeError(
                self._error or "paired shadow runtime disabled"
            )

        def enqueue() -> None:
            self._queue.put(command, timeout=timeout_seconds)
            self._record_queue_depth()

        try:
            await asyncio.wait_for(
                asyncio.to_thread(enqueue),
                timeout=timeout_seconds,
            )
            return await asyncio.wait_for(
                asyncio.wrap_future(command.future),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            self._set_error(
                "LossContextPairedShadowRuntimeError: paired shadow control timeout"
            )
            raise LossContextPairedShadowRuntimeError(
                "paired shadow control timeout"
            ) from exc

    def fail_closed(self, reason: str) -> None:
        """Disable only the shadow, not ordinary paper trading."""
        self._set_error("LossContextPairedShadowRuntimeError: " + reason)

    async def protected_open_markets(
        self,
        *,
        timeout_seconds: float = DEFAULT_CONTROL_TIMEOUT_SECONDS,
    ) -> tuple[MarketId, ...]:
        """Actor-ordered snapshot includes fills from all preceding records."""
        payload = await self._request_control(
            _ProtectedMarketsCommand(future=Future()),
            timeout_seconds=timeout_seconds,
        )
        markets = payload.get("protected_markets")
        if not isinstance(markets, tuple) or any(
            not isinstance(market, MarketId) for market in markets
        ):
            self._set_error("invalid paired position coverage response")
            raise LossContextPairedShadowRuntimeError(
                "invalid paired position coverage response"
            )
        return tuple(
            market for market in markets if isinstance(market, MarketId)
        )

    async def checkpoint(
        self,
        *,
        end_ms: int,
        timeout_seconds: float = DEFAULT_CONTROL_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        future: Future[dict[str, object]] = Future()
        return await self._request_control(
            _CheckpointCommand(end_ms=end_ms, future=future),
            timeout_seconds=timeout_seconds,
        )

    async def summary(
        self,
        *,
        end_ms: int,
        timeout_seconds: float = DEFAULT_CONTROL_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        future: Future[dict[str, object]] = Future()
        return await self._request_control(
            _SummaryCommand(end_ms=end_ms, future=future),
            timeout_seconds=timeout_seconds,
        )

    async def close(
        self,
        *,
        timeout_seconds: float = DEFAULT_CONTROL_TIMEOUT_SECONDS,
    ) -> None:
        if self._closed.is_set():
            return
        future: Future[None] = Future()
        command = _CloseCommand(future=future)

        def enqueue() -> None:
            self._queue.put(command, timeout=timeout_seconds)

        try:
            await asyncio.wait_for(
                asyncio.to_thread(enqueue),
                timeout=timeout_seconds,
            )
            await asyncio.wait_for(
                asyncio.wrap_future(future),
                timeout=timeout_seconds,
            )
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._thread.join,
                    timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            self._set_error(
                "LossContextPairedShadowRuntimeError: paired shadow close timeout"
            )
            raise LossContextPairedShadowRuntimeError(
                "paired shadow close timeout"
            ) from exc

    def status_payload(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": (
                    self._initialized.is_set()
                    and not self._failed.is_set()
                    and not self._closed.is_set()
                ),
                "initialized": self._initialized.is_set(),
                "failed": self._failed.is_set(),
                "closed": self._closed.is_set(),
                "error": self._error,
                "portfolio_shadow_candidate_id": (
                    self._freeze.candidate_id
                ),
                "desired_markets": tuple(
                    market.canonical for market in self._markets
                ),
                "restore_markets": tuple(
                    market.canonical for market in self._restore_markets
                ),
                "research_state_root": self._state_root.name,
                "queue_capacity": self._queue.maxsize,
                "queue_depth": self._queue.qsize(),
                "queue_high_watermark": self._queue_high_watermark,
                "queue_overflows": self._queue_overflows,
                "submitted_records": self._submitted_records,
                "processed_records": self._processed_records,
                "submitted_rank_snapshots": (
                    self._submitted_rank_snapshots
                ),
                "processed_rank_snapshots": (
                    self._processed_rank_snapshots
                ),
                "submitted_reconciles": self._submitted_reconciles,
                "processed_reconciles": self._processed_reconciles,
                "warmup_complete_submitted": (
                    self._warmup_complete_submitted
                ),
                "warmup_complete_processed": (
                    self._warmup_complete_processed
                ),
                "checkpoint_count": self._checkpoint_count,
                "last_checkpoint_end_ms": self._last_checkpoint_end_ms,
                "research_only": True,
                "shadow_only": True,
                "paper_only": True,
                "non_blocking_active_paper_feed": True,
                "queue_overflow_fails_shadow_closed": True,
                "changes_strategy": False,
                "changes_risk_limits": False,
                "changes_positions": False,
                "promotion_authority": False,
                "execution_authority": False,
            }
