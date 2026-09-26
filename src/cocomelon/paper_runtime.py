from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.journal import JournalObservation, TradeJournalEntry
from cocomelon.domain.market import Candle, FundingRate, MarketId, PerpMarketSnapshot
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig, EvidenceRecordingConfig
from cocomelon.evidence.lifecycle import (
    BaselineReplayPipeline,
    OpenLifecycleCheckpoint,
)
from cocomelon.evidence.recording import (
    EvidenceInfoReader,
    _recent_funding,
    _startup_ranks,
    _warmup_candles,
    candle_record_event,
    funding_rate_record_event,
    market_snapshot_record_event,
)
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.normalize import normalize_funding_history
from cocomelon.hyperliquid.registry import MarketRegistry
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.hyperliquid.ws_client import connect_mainnet_ws
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor
from cocomelon.journal.store import JournalStore
from cocomelon.util.time import utc_now_ms

RUNTIME_ID = "continuous-mainnet-paper-v1"
CHECKPOINT_SCHEMA_VERSION = 1
DEFAULT_DURATION_SECONDS = 19_800
DEFAULT_REFRESH_SECONDS = 300
DEFAULT_FUNDING_POLL_SECONDS = 60
DEFAULT_DEEP_LIMIT = 20


class PaperRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PaperRuntimeConfig:
    state_root: Path
    duration_seconds: int = DEFAULT_DURATION_SECONDS
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS
    funding_poll_seconds: int = DEFAULT_FUNDING_POLL_SECONDS
    deep_limit: int = DEFAULT_DEEP_LIMIT
    starting_cash: Decimal = Decimal("10000")

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.refresh_seconds <= 0:
            raise ValueError("refresh_seconds must be positive")
        if self.funding_poll_seconds <= 0:
            raise ValueError("funding_poll_seconds must be positive")
        if self.deep_limit <= 0:
            raise ValueError("deep_limit must be positive")
        if not self.starting_cash.is_finite() or self.starting_cash <= 0:
            raise ValueError("starting_cash must be positive and finite")

    @property
    def execution_path(self) -> Path:
        return self.state_root / "paper.sqlite3"

    @property
    def journal_path(self) -> Path:
        return self.state_root / "journal.sqlite3"

    @property
    def facts_path(self) -> Path:
        return self.state_root / "facts.sqlite3"

    @property
    def checkpoint_path(self) -> Path:
        return self.state_root / "open-lifecycles.json"

    @property
    def status_path(self) -> Path:
        return self.state_root / "paper-runtime-status.json"


@dataclass(frozen=True, slots=True)
class RuntimeBootstrap:
    selected_markets: tuple[MarketId, ...]
    snapshots: tuple[PerpMarketSnapshot, ...]
    candles: tuple[Candle, ...]
    funding_rates: tuple[FundingRate, ...]
    subscriptions: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class PaperRuntimeSummary:
    runtime_id: str
    selected_markets: tuple[str, ...]
    open_positions: int
    closed_trades: int
    equity: Decimal
    realized_gross_pnl: Decimal
    cumulative_fees: Decimal
    cumulative_funding: Decimal
    started_at_ms: int
    finished_at_ms: int
    cycles: int
    network_access: bool = True
    paper_only: bool = True
    live_orders: bool = False


def _market_from_canonical(value: str) -> MarketId:
    if ":" not in value:
        return MarketId.from_wire_name("", value)
    dex = value.split(":", 1)[0]
    return MarketId.from_wire_name(dex, value)


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be serialized")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("mapping keys must be strings")
            result[key] = _canonical(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _received_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def replay_record_from_stream(event: StreamEvent) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=_received_ms(event.receive_time),
        source=event.source,
        schema_version=event.schema_version,
        market=event.market.canonical,
        exchange_time_ms=event.exchange_time_ms,
        event_key=event.event_key,
        payload_json=_canonical_json(event.payload),
        event_kind=event.kind.value,
    )


def replay_record_from_gap(gap: DataGap) -> ReplayRecord:
    available_at_ms = gap.ended_ms if gap.ended_ms is not None else gap.started_ms
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=available_at_ms,
        source=gap.source,
        schema_version=gap.schema_version,
        market=None,
        exchange_time_ms=None,
        event_key=(
            f"gap:{gap.stream_id}:{gap.started_ms}:"
            f"{gap.ended_ms if gap.ended_ms is not None else 'open'}:{gap.reason}"
        ),
        payload_json=_canonical_json(
            {
                "stream_id": gap.stream_id,
                "started_ms": gap.started_ms,
                "ended_ms": gap.ended_ms,
                "reason": gap.reason,
            }
        ),
        event_kind=None,
    )


def _record_from_public_event(event: object) -> ReplayRecord:
    kind = getattr(event, "kind")
    market = getattr(event, "market")
    receive_time = getattr(event, "receive_time")
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=_received_ms(receive_time),
        source=str(getattr(event, "source")),
        schema_version=int(getattr(event, "schema_version")),
        market=market.canonical,
        exchange_time_ms=getattr(event, "exchange_time_ms"),
        event_key=str(getattr(event, "event_key")),
        payload_json=_canonical_json(getattr(event, "payload")),
        event_kind=str(kind),
    )


def replay_record_from_snapshot(snapshot: PerpMarketSnapshot) -> ReplayRecord:
    return _record_from_public_event(market_snapshot_record_event(snapshot))


def replay_record_from_candle(candle: Candle) -> ReplayRecord:
    return _record_from_public_event(candle_record_event(candle))


def replay_record_from_funding(rate: FundingRate) -> ReplayRecord:
    return _record_from_public_event(funding_rate_record_event(rate))


def _checkpoint_payload(
    checkpoints: Sequence[OpenLifecycleCheckpoint],
) -> dict[str, object]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "open_lifecycles": [
            {
                "market": item.market.canonical,
                "opening_plan_id": item.opening_plan_id,
                "feature_snapshot_id": item.feature_snapshot_id,
                "equity_before": str(item.equity_before),
            }
            for item in checkpoints
        ],
    }


def load_open_lifecycle_checkpoints(path: Path) -> tuple[OpenLifecycleCheckpoint, ...]:
    if not path.exists():
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PaperRuntimeError("runtime lifecycle checkpoint must be an object")
    if raw.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise PaperRuntimeError("unsupported runtime lifecycle checkpoint schema")
    if raw.get("runtime_id") != RUNTIME_ID:
        raise PaperRuntimeError("runtime lifecycle checkpoint identity mismatch")
    items = raw.get("open_lifecycles")
    if not isinstance(items, list):
        raise PaperRuntimeError("runtime lifecycle checkpoint entries must be an array")
    checkpoints: list[OpenLifecycleCheckpoint] = []
    for item in items:
        if not isinstance(item, dict):
            raise PaperRuntimeError("runtime lifecycle checkpoint entry must be an object")
        checkpoints.append(
            OpenLifecycleCheckpoint(
                market=_market_from_canonical(str(item["market"])),
                opening_plan_id=str(item["opening_plan_id"]),
                feature_snapshot_id=str(item["feature_snapshot_id"]),
                equity_before=Decimal(str(item["equity_before"])),
            )
        )
    checkpoints.sort(key=lambda item: item.market.canonical)
    if len({item.market.canonical for item in checkpoints}) != len(checkpoints):
        raise PaperRuntimeError("runtime lifecycle checkpoint contains duplicate markets")
    return tuple(checkpoints)


def write_open_lifecycle_checkpoints(
    path: Path,
    checkpoints: Sequence[OpenLifecycleCheckpoint],
) -> None:
    ordered = tuple(sorted(checkpoints, key=lambda item: item.market.canonical))
    encoded = json.dumps(
        _checkpoint_payload(ordered),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == encoded:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _ranked_native_markets(
    registry: Mapping[str, PerpMarketSnapshot],
    *,
    as_of_ms: int,
    deep_limit: int,
) -> tuple[MarketId, ...]:
    _, ranks = _startup_ranks(registry, as_of_ms=as_of_ms)
    native = tuple(rank.market for rank in ranks if rank.market.dex == "")
    return native[:deep_limit]


def build_runtime_bootstrap(
    reader: EvidenceInfoReader,
    config: PaperRuntimeConfig,
    *,
    pinned_markets: Sequence[MarketId] = (),
    warmup_markets: Sequence[MarketId] | None = None,
    now_ms: Callable[[], int] = utc_now_ms,
) -> RuntimeBootstrap:
    registry = MarketRegistry(reader, now_ms=now_ms).refresh()
    ranked = _ranked_native_markets(
        registry.markets,
        as_of_ms=registry.received_at_ms,
        deep_limit=config.deep_limit,
    )
    selected_by_key = {market.canonical: market for market in ranked}
    for market in pinned_markets:
        if market.dex:
            raise PaperRuntimeError("paper runtime supports native perp execution only")
        if market.canonical not in registry.markets:
            raise PaperRuntimeError(
                f"open paper position market disappeared from mainnet registry: {market.canonical}"
            )
        selected_by_key[market.canonical] = market
    selected = tuple(sorted(selected_by_key.values(), key=lambda item: item.canonical))
    if not selected:
        raise PaperRuntimeError("broad mainnet scan produced no rankable paper markets")

    snapshots = tuple(registry.markets[market.canonical] for market in selected)
    requested_warmups = selected if warmup_markets is None else tuple(warmup_markets)
    warmup_keys = {market.canonical for market in requested_warmups}
    recording_config = EvidenceRecordingConfig(
        duration_seconds=1,
        deep_limit=max(config.deep_limit, len(selected)),
    )
    candles: list[Candle] = []
    end_ms = now_ms()
    for market in selected:
        if market.canonical in warmup_keys:
            candles.extend(
                _warmup_candles(
                    reader,
                    market,
                    recording_config,
                    end_ms=end_ms,
                    now_ms=now_ms,
                )
            )

    funding: list[FundingRate] = []
    pinned_keys = {market.canonical for market in pinned_markets}
    for market in selected:
        if market.canonical in pinned_keys:
            funding.extend(
                _recent_funding(
                    reader,
                    market,
                    end_ms=end_ms,
                    now_ms=now_ms,
                )
            )

    subscriptions = DeepWatchlistManager().reconcile(selected).subscribe
    return RuntimeBootstrap(
        selected_markets=selected,
        snapshots=snapshots,
        candles=tuple(candles),
        funding_rates=tuple(funding),
        subscriptions=subscriptions,
    )


def _restore_open_lifecycles(
    pipeline: BaselineReplayPipeline,
    execution: PaperExecutionAdapter,
    checkpoints: Sequence[OpenLifecycleCheckpoint],
) -> None:
    by_market = {item.market.canonical: item for item in checkpoints}
    open_markets = {position.market.canonical for position in execution.account.positions}
    missing = open_markets - set(by_market)
    if missing:
        raise PaperRuntimeError(
            "open paper position is missing durable lifecycle metadata: "
            + ",".join(sorted(missing))
        )
    for position in execution.account.positions:
        checkpoint = by_market[position.market.canonical]
        if checkpoint.opening_plan_id != position.opening_plan_id:
            raise PaperRuntimeError("paper lifecycle checkpoint opening plan mismatch")
        plan = execution.store.load_plan(position.opening_plan_id)
        if plan is None:
            raise PaperRuntimeError("open paper position is missing its opening plan")
        attempts, fills = execution.store.load_execution_history(plan.plan_id)
        fill_attempt_ids = {fill.attempt_id for fill in fills}
        opening_attempts = tuple(
            attempt for attempt in attempts if attempt.attempt_id in fill_attempt_ids
        )
        if len(opening_attempts) != 1:
            raise PaperRuntimeError("open paper position has ambiguous opening execution")
        opening_attempt = opening_attempts[0]
        opening_fills = tuple(
            fill for fill in fills if fill.attempt_id == opening_attempt.attempt_id
        )
        funding = execution.store.load_funding_for_market(
            position.market,
            start_ms=position.opened_at_ms,
        )
        pipeline.restore_open_lifecycle(
            checkpoint,
            opening_plan=plan,
            opening_attempt=opening_attempt,
            opening_fills=opening_fills,
            funding_accruals=funding,
        )


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _runtime_status(
    *,
    pipeline: BaselineReplayPipeline,
    execution: PaperExecutionAdapter,
    journal: JournalStore,
    selected_markets: Sequence[MarketId],
    as_of_ms: int,
) -> dict[str, object]:
    account = execution.account
    trades = tuple(journal.iter_trades())
    return {
        "schema_version": 1,
        "runtime_id": RUNTIME_ID,
        "as_of_ms": as_of_ms,
        "paper_only": True,
        "live_orders": False,
        "selected_markets": [item.canonical for item in selected_markets],
        "open_positions": [
            {
                "market": position.market.canonical,
                "side": position.side.value,
                "quantity": str(position.quantity),
                "average_entry_price": str(position.average_entry_price),
                "stop_price": str(position.stop_price),
                "opened_at_ms": position.opened_at_ms,
                "planned_risk": str(position.planned_risk),
                "latest_mark": (
                    None if position.latest_mark is None else str(position.latest_mark)
                ),
                "unrealized_pnl": (
                    None
                    if position.latest_mark is None
                    else str(
                        position.quantity
                        * (
                            position.latest_mark - position.average_entry_price
                            if position.side.value == "long"
                            else position.average_entry_price - position.latest_mark
                        )
                    )
                ),
            }
            for position in account.positions
        ],
        "open_lifecycle_count": len(pipeline.open_lifecycle_checkpoints),
        "closed_trade_count": len(trades),
        "latest_closed_trade": (
            None
            if not trades
            else {
                "trade_id": trades[-1].trade_id,
                "market": trades[-1].market.canonical,
                "direction": trades[-1].direction.value,
                "opened_at_ms": trades[-1].opened_at_ms,
                "closed_at_ms": trades[-1].closed_at_ms,
                "net_pnl": str(trades[-1].net_pnl),
                "net_r": None if trades[-1].net_r is None else str(trades[-1].net_r),
            }
        ),
        "account": {
            "equity": str(account.equity),
            "cash": str(account.cash),
            "realized_gross_pnl": str(account.realized_gross_pnl),
            "unrealized_pnl": str(account.unrealized_pnl),
            "cumulative_fees": str(account.cumulative_fees),
            "cumulative_funding": str(account.cumulative_funding),
            "daily_realized_pnl": str(account.daily_realized_pnl),
            "gross_open_notional": str(account.gross_open_notional),
            "available_margin": str(account.available_margin),
            "consecutive_losses": account.consecutive_losses,
        },
    }


async def run_continuous_paper_runtime(
    settings: Settings,
    config: PaperRuntimeConfig,
    *,
    reader: EvidenceInfoReader | None = None,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> PaperRuntimeSummary:
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise PaperRuntimeError("continuous paper runtime requires paper execution mode")
    config.state_root.mkdir(parents=True, exist_ok=True)

    info = reader or InfoClient(settings)
    started_at_ms = clock_ms()
    replay_config = BaselineReplayConfig(starting_cash=config.starting_cash)
    execution = PaperExecutionAdapter(
        config.execution_path,
        replay_config.execution,
        starting_cash=config.starting_cash,
        startup_timestamp_ms=started_at_ms,
    )
    facts = EvaluationFactStore(config.facts_path)
    journal = JournalStore(config.journal_path)
    pipeline: BaselineReplayPipeline | None = None
    selected_markets: tuple[MarketId, ...] = ()
    cycles = 0
    last_available_ms = 0
    previous_selected: set[str] = set()

    async def persist_runtime_state() -> None:
        if pipeline is None:
            return
        write_open_lifecycle_checkpoints(
            config.checkpoint_path,
            pipeline.open_lifecycle_checkpoints,
        )
        _atomic_json(
            config.status_path,
            _runtime_status(
                pipeline=pipeline,
                execution=execution,
                journal=journal,
                selected_markets=selected_markets,
                as_of_ms=max(last_available_ms, clock_ms()),
            ),
        )

    async def consume_record(raw_record: ReplayRecord) -> None:
        nonlocal last_available_ms
        if pipeline is None:
            raise PaperRuntimeError("paper pipeline is not initialized")
        available_at_ms = max(raw_record.available_at_ms, last_available_ms)
        record = (
            raw_record
            if available_at_ms == raw_record.available_at_ms
            else replace(raw_record, available_at_ms=available_at_ms)
        )
        last_available_ms = available_at_ms
        observations: Sequence[JournalObservation] = pipeline.on_record(
            record,
            available_at_ms,
        )
        for observation in observations:
            journal.record_observation(observation)
        for trade in pipeline.finalize(available_at_ms):
            journal.record_trade(trade)
        await persist_runtime_state()

    async def consume_stream(event: StreamEvent) -> None:
        await consume_record(replay_record_from_stream(event))

    async def consume_gap(gap: DataGap) -> None:
        await consume_record(replay_record_from_gap(gap))

    try:
        deadline_ms = started_at_ms + config.duration_seconds * 1000
        while clock_ms() < deadline_ms:
            pinned = tuple(position.market for position in execution.account.positions)
            bootstrap = await asyncio.to_thread(
                build_runtime_bootstrap,
                info,
                config,
                pinned_markets=pinned,
                warmup_markets=(),
                now_ms=clock_ms,
            )
            selected_markets = bootstrap.selected_markets
            selected_keys = {item.canonical for item in selected_markets}
            added = tuple(
                market
                for market in selected_markets
                if market.canonical not in previous_selected
            )
            if added:
                bootstrap = await asyncio.to_thread(
                    build_runtime_bootstrap,
                    info,
                    config,
                    pinned_markets=pinned,
                    warmup_markets=added,
                    now_ms=clock_ms,
                )
                selected_markets = bootstrap.selected_markets
                selected_keys = {item.canonical for item in selected_markets}

            if pipeline is None:
                pipeline = BaselineReplayPipeline(
                    replay_config,
                    execution,
                    facts,
                    selected_markets=selected_markets,
                    replay_run_id=RUNTIME_ID,
                    evidence_class=EvidenceClass.MICROSTRUCTURE,
                )
                checkpoints = load_open_lifecycle_checkpoints(config.checkpoint_path)
                _restore_open_lifecycles(pipeline, execution, checkpoints)
                await persist_runtime_state()
            else:
                pipeline.reconcile_markets(selected_markets)

            bootstrap_at_ms = clock_ms()
            seed_records = [
                *(replay_record_from_snapshot(item) for item in bootstrap.snapshots),
                *(replay_record_from_candle(item) for item in bootstrap.candles),
                *(replay_record_from_funding(item) for item in bootstrap.funding_rates),
            ]
            for record in sorted(seed_records, key=lambda item: item.sort_key):
                await consume_record(
                    replace(
                        record,
                        available_at_ms=max(bootstrap_at_ms, record.available_at_ms),
                    )
                )

            previous_selected = selected_keys
            cycles += 1
            remaining_seconds = max(0.0, (deadline_ms - clock_ms()) / 1000)
            cycle_seconds = min(float(config.refresh_seconds), remaining_seconds)
            if cycle_seconds <= 0:
                break

            mux = RedundantStreamMux(event_sink=consume_stream, gap_sink=consume_gap)

            async def connection_factory():
                return await connect_mainnet_ws(settings)

            supervisors: list[WebSocketSupervisor] = []
            for lane in range(2):
                async def lane_event_sink(
                    event: StreamEvent,
                    lane: int = lane,
                ) -> None:
                    await mux.on_event(lane, event)

                async def lane_gap_sink(
                    gap: DataGap,
                    lane: int = lane,
                ) -> None:
                    await mux.on_gap(lane, gap)

                supervisors.append(
                    WebSocketSupervisor(
                        connection_factory,
                        bootstrap.subscriptions,
                        event_sink=lane_event_sink,
                        gap_sink=lane_gap_sink,
                        clock_ms=clock_ms,
                        utcnow=lambda: datetime.now(UTC),
                    )
                )

            async def poll_open_position_funding() -> None:
                while True:
                    await asyncio.sleep(float(config.funding_poll_seconds))
                    for position in tuple(execution.account.positions):
                        end_ms = clock_ms()
                        try:
                            raw = await asyncio.to_thread(
                                info.funding_history,
                                position.market,
                                start_ms=max(position.opened_at_ms, end_ms - 2 * 3_600_000),
                                end_ms=end_ms,
                            )
                            rates = normalize_funding_history(
                                position.market,
                                raw,
                                received_at_ms=clock_ms(),
                            )
                            for rate in rates:
                                await consume_record(replay_record_from_funding(rate))
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            await consume_gap(
                                DataGap(
                                    stream_id=(
                                        f"rest:funding_rate:{position.market.canonical}"
                                    ),
                                    started_ms=end_ms,
                                    ended_ms=end_ms,
                                    reason=f"poll_error:{type(exc).__name__}",
                                    source="hyperliquid-mainnet-info",
                                )
                            )

            tasks = tuple(
                asyncio.create_task(supervisor.run()) for supervisor in supervisors
            ) + (asyncio.create_task(poll_open_position_funding()),)
            try:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks),
                        timeout=cycle_seconds,
                    )
                except TimeoutError:
                    pass
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            await persist_runtime_state()

        finished_at_ms = clock_ms()
        if pipeline is None:
            raise PaperRuntimeError("continuous paper runtime never initialized")
        await persist_runtime_state()
        trades: tuple[TradeJournalEntry, ...] = tuple(journal.iter_trades())
        account = execution.account
        return PaperRuntimeSummary(
            runtime_id=RUNTIME_ID,
            selected_markets=tuple(item.canonical for item in selected_markets),
            open_positions=len(account.positions),
            closed_trades=len(trades),
            equity=account.equity,
            realized_gross_pnl=account.realized_gross_pnl,
            cumulative_fees=account.cumulative_fees,
            cumulative_funding=account.cumulative_funding,
            started_at_ms=started_at_ms,
            finished_at_ms=finished_at_ms,
            cycles=cycles,
        )
    finally:
        facts.close()
        journal.close()
        execution.close()
