from __future__ import annotations

import copy
import queue
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord

DEFAULT_MAX_QUEUE_RECORDS: Final = 8_192


class PairedShadowFeedError(RuntimeError):
    pass


class PairedShadowWorker(Protocol):
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

    def mark_restore_warmup_complete(self) -> None: ...

    def checkpoint(self, *, end_ms: int) -> dict[str, object]: ...

    def summary_payload(self, *, end_ms: int) -> dict[str, object]: ...

    def close(self) -> None: ...


ShadowFactory = Callable[[], PairedShadowWorker]


@dataclass(frozen=True, slots=True)
class _RecordItem:
    record: ReplayRecord
    evaluate_decisions: bool


@dataclass(frozen=True, slots=True)
class _ReconcileItem:
    markets: tuple[MarketId, ...]


@dataclass(frozen=True, slots=True)
class _WarmupCompleteItem:
    pass


@dataclass(frozen=True, slots=True)
class _CheckpointItem:
    end_ms: int


@dataclass(frozen=True, slots=True)
class _SummaryItem:
    end_ms: int


@dataclass(frozen=True, slots=True)
class _StopItem:
    pass


_FeedItem = (
    _RecordItem
    | _ReconcileItem
    | _WarmupCompleteItem
    | _CheckpointItem
    | _SummaryItem
    | _StopItem
)


class LossContextPairedShadowBackgroundFeed:
    """Non-blocking bridge from the active paper loop to a shadow worker.

    The hot path only attempts a bounded non-waiting queue insert. The paired
    shadow, including both SQLite-backed accounts, is created and used
    exclusively on one dedicated worker thread. Any overflow or worker
    exception permanently invalidates the research feed; it never
    back-pressures the active trader.
    """

    def __init__(
        self,
        shadow_factory: ShadowFactory,
        *,
        max_queue_records: int = DEFAULT_MAX_QUEUE_RECORDS,
        thread_name: str = "cocomelon-loss-context-shadow",
    ) -> None:
        if max_queue_records <= 0:
            raise ValueError("max_queue_records must be positive")
        if not thread_name.strip():
            raise ValueError("thread_name must not be empty")
        self._shadow_factory = shadow_factory
        self._queue: queue.Queue[_FeedItem] = queue.Queue(
            maxsize=max_queue_records
        )
        self._thread_name = thread_name
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._started = False
        self._worker_stopped = False
        self._failed_reason: str | None = None
        self._failed_detail: str | None = None
        self._offered_records = 0
        self._accepted_records = 0
        self._processed_records = 0
        self._offered_controls = 0
        self._processed_controls = 0
        self._rejected_after_failure = 0
        self._queue_overflow_count = 0
        self._max_queue_depth = 0
        self._checkpoint_count = 0
        self._last_checkpoint_end_ms: int | None = None
        self._summary_count = 0
        self._last_summary_end_ms: int | None = None
        self._last_summary: dict[str, object] | None = None
        self._worker_thread_id: int | None = None

    def start(self) -> None:
        with self._lock:
            if self._started:
                raise PairedShadowFeedError(
                    "paired shadow feed already started"
                )
            self._started = True
            self._thread = threading.Thread(
                target=self._worker_main,
                name=self._thread_name,
                daemon=True,
            )
            thread = self._thread
        thread.start()

    def wait_until_ready(self, timeout_seconds: float = 5.0) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        return self._ready.wait(timeout_seconds)

    def _fail(self, reason: str, detail: str | None = None) -> None:
        with self._lock:
            if self._failed_reason is not None:
                return
            self._failed_reason = reason
            self._failed_detail = detail

    def _offer(self, item: _FeedItem, *, record: bool) -> bool:
        with self._lock:
            if not self._started:
                raise PairedShadowFeedError(
                    "paired shadow feed is not started"
                )
            if self._worker_stopped or self._stop_requested.is_set():
                self._rejected_after_failure += 1
                return False
            if self._failed_reason is not None:
                self._rejected_after_failure += 1
                return False
            if record:
                self._offered_records += 1
            else:
                self._offered_controls += 1
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._queue_overflow_count += 1
            self._fail(
                "queue_overflow",
                (
                    "paired shadow queue overflowed; "
                    "research continuity is invalid"
                ),
            )
            return False
        with self._lock:
            if record:
                self._accepted_records += 1
            self._max_queue_depth = max(
                self._max_queue_depth,
                self._queue.qsize(),
            )
        return True

    def offer_record(
        self,
        record: ReplayRecord,
        *,
        evaluate_decisions: bool = True,
    ) -> bool:
        return self._offer(
            _RecordItem(
                record=record,
                evaluate_decisions=evaluate_decisions,
            ),
            record=True,
        )

    def request_reconcile(
        self,
        selected_markets: Sequence[MarketId],
    ) -> bool:
        markets = tuple(
            sorted(
                selected_markets,
                key=lambda item: item.canonical,
            )
        )
        if not markets:
            raise ValueError("selected_markets must not be empty")
        if len({item.canonical for item in markets}) != len(markets):
            raise ValueError(
                "selected_markets must not contain duplicates"
            )
        return self._offer(
            _ReconcileItem(markets=markets),
            record=False,
        )

    def request_warmup_complete(self) -> bool:
        return self._offer(
            _WarmupCompleteItem(),
            record=False,
        )

    def request_checkpoint(self, *, end_ms: int) -> bool:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        return self._offer(
            _CheckpointItem(end_ms=end_ms),
            record=False,
        )

    def request_summary(self, *, end_ms: int) -> bool:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        return self._offer(
            _SummaryItem(end_ms=end_ms),
            record=False,
        )

    def request_stop(self) -> bool:
        with self._lock:
            if not self._started:
                return True
            if self._stop_requested.is_set():
                return True
            try:
                self._queue.put_nowait(_StopItem())
            except queue.Full:
                self._stop_requested.set()
                self._queue_overflow_count += 1
                stop_failed = True
            else:
                self._stop_requested.set()
                stop_failed = False
        if stop_failed:
            self._fail(
                "stop_queue_overflow",
                "paired shadow stop sentinel could not be queued",
            )
            return False
        return True

    def _process_item(
        self,
        shadow: PairedShadowWorker,
        item: _FeedItem,
    ) -> None:
        if isinstance(item, _RecordItem):
            shadow.on_record(
                item.record,
                item.record.available_at_ms,
                evaluate_decisions=item.evaluate_decisions,
            )
            with self._lock:
                self._processed_records += 1
            return
        if isinstance(item, _ReconcileItem):
            shadow.reconcile_markets(item.markets)
        elif isinstance(item, _WarmupCompleteItem):
            shadow.mark_restore_warmup_complete()
        elif isinstance(item, _CheckpointItem):
            shadow.checkpoint(end_ms=item.end_ms)
            with self._lock:
                self._checkpoint_count += 1
                self._last_checkpoint_end_ms = item.end_ms
        elif isinstance(item, _SummaryItem):
            summary = shadow.summary_payload(end_ms=item.end_ms)
            with self._lock:
                self._last_summary = copy.deepcopy(summary)
                self._summary_count += 1
                self._last_summary_end_ms = item.end_ms
        else:
            raise PairedShadowFeedError(
                "unsupported paired shadow feed item"
            )
        with self._lock:
            self._processed_controls += 1

    def _worker_main(self) -> None:
        shadow: PairedShadowWorker | None = None
        try:
            with self._lock:
                self._worker_thread_id = threading.get_ident()
            shadow = self._shadow_factory()
            self._ready.set()
            while True:
                if self._stop_requested.is_set() and self._queue.empty():
                    break
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if isinstance(item, _StopItem):
                        break
                    with self._lock:
                        failed = self._failed_reason is not None
                    if failed:
                        continue
                    try:
                        self._process_item(shadow, item)
                    except Exception as exc:
                        self._fail(
                            "worker_exception",
                            f"{type(exc).__name__}: {exc}",
                        )
                finally:
                    self._queue.task_done()
        except Exception as exc:
            self._fail(
                "worker_startup_exception",
                f"{type(exc).__name__}: {exc}",
            )
            self._ready.set()
        finally:
            if shadow is not None:
                try:
                    shadow.close()
                except Exception as exc:
                    self._fail(
                        "worker_close_exception",
                        f"{type(exc).__name__}: {exc}",
                    )
            with self._lock:
                self._worker_stopped = True
            self._ready.set()

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def join(self, timeout_seconds: float = 5.0) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout_seconds)
        return not thread.is_alive()

    @property
    def last_summary(self) -> dict[str, object] | None:
        with self._lock:
            return copy.deepcopy(self._last_summary)

    def status_payload(self) -> dict[str, object]:
        with self._lock:
            thread = self._thread
            return {
                "started": self._started,
                "ready": self._ready.is_set(),
                "worker_alive": (
                    False if thread is None else thread.is_alive()
                ),
                "worker_stopped": self._worker_stopped,
                "worker_thread_id": self._worker_thread_id,
                "failed": self._failed_reason is not None,
                "failed_reason": self._failed_reason,
                "failed_detail": self._failed_detail,
                "queue_depth": self._queue.qsize(),
                "queue_capacity": self._queue.maxsize,
                "max_queue_depth": self._max_queue_depth,
                "queue_overflow_count": self._queue_overflow_count,
                "offered_records": self._offered_records,
                "accepted_records": self._accepted_records,
                "processed_records": self._processed_records,
                "offered_controls": self._offered_controls,
                "processed_controls": self._processed_controls,
                "rejected_after_failure": self._rejected_after_failure,
                "checkpoint_count": self._checkpoint_count,
                "last_checkpoint_end_ms": self._last_checkpoint_end_ms,
                "summary_count": self._summary_count,
                "last_summary_end_ms": self._last_summary_end_ms,
                "hot_path_blocking_puts": 0,
                "overflow_fails_research_closed": True,
                "worker_exception_fails_research_closed": True,
                "active_trader_backpressure": False,
                "research_only": True,
                "shadow_only": True,
                "changes_strategy": False,
                "changes_risk_limits": False,
                "changes_positions": False,
                "promotion_authority": False,
                "execution_authority": False,
            }
