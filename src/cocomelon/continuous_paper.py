from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.execution import (
    ExecutionAttempt,
    PaperFill,
    PaperOrderPlan,
    PositionAction,
    PositionActionType,
)
from cocomelon.domain.journal import JournalObservation, TradeJournalEntry
from cocomelon.domain.market import Candle, MarketId, PerpMarketSnapshot
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import BaselineReplayPipeline, OpenLifecycleCheckpoint
from cocomelon.evidence.recording import (
    RecordedPublicEvent,
    _startup_ranks,
    candle_record_event,
    funding_rate_record_event,
    market_snapshot_record_event,
)
from cocomelon.evidence.redundant_stream import RedundantStreamMux
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.hyperliquid.client import INTERVAL_MS, InfoClient
from cocomelon.hyperliquid.normalize import (
    normalize_candles,
    normalize_funding_history,
    normalize_meta_and_asset_ctxs,
)
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.hyperliquid.ws_client import connect_mainnet_ws
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor
from cocomelon.journal.store import JournalStore
from cocomelon.research.cadence_shadow import CadenceShadowComparator
from cocomelon.research.continuous_paper_learning import (
    CONTINUOUS_PAPER_REPLAY_RUN_ID,
    ContinuousPaperOpeningLineage,
    ContinuousPaperOpeningLineageStore,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
    continuous_paper_trade_path,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.util.time import utc_now_ms

RUN_ID = CONTINUOUS_PAPER_REPLAY_RUN_ID
CHECKPOINT_FILENAME = "runtime-state.json"
SUMMARY_FILENAME = "session-summary.json"
CADENCE_SHADOW_FILENAME = "cadence-shadow-summary.json"
CADENCE_SHADOW_STATE_FILENAME = "cadence-shadow-state.json"


@dataclass(frozen=True, slots=True)
class ContinuousPaperConfig:
    duration_seconds: int = 19_800
    deep_limit: int = 20
    context_poll_seconds: int = 60
    selection_refresh_seconds: int = 300
    checkpoint_seconds: int = 30
    warmup_5m_bars: int = 25
    warmup_15m_bars: int = 25

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.deep_limit <= 0:
            raise ValueError("deep_limit must be positive")
        if self.context_poll_seconds <= 0:
            raise ValueError("context_poll_seconds must be positive")
        if self.selection_refresh_seconds < self.context_poll_seconds:
            raise ValueError("selection_refresh_seconds must be >= context_poll_seconds")
        if self.selection_refresh_seconds % self.context_poll_seconds:
            raise ValueError("selection_refresh_seconds must be divisible by context_poll_seconds")
        if self.checkpoint_seconds <= 0:
            raise ValueError("checkpoint_seconds must be positive")
        if self.warmup_5m_bars <= 0 or self.warmup_15m_bars <= 0:
            raise ValueError("warmup bar counts must be positive")


class _ContinuousTradePathSink:
    def __init__(self, store: ContinuousPaperTradePathStore) -> None:
        self._store = store
        self.error: str | None = None

    def record(
        self,
        trade: TradeJournalEntry,
        mark_observations: Sequence[ReplayRecord],
        known_gap_intervals: Sequence[tuple[int, int | None]],
    ) -> bool:
        try:
            created = self._store.record(
                continuous_paper_trade_path(
                    trade,
                    mark_observations,
                    known_gap_intervals,
                )
            )
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False
        self.error = None
        return created


class _ContinuousOpeningLineageSink:
    def __init__(
        self,
        store: ContinuousPaperOpeningLineageStore,
        runtime: ContinuousPaperRuntimeIdentity,
    ) -> None:
        self._store = store
        self._runtime = runtime

    def record(self, checkpoint: OpenLifecycleCheckpoint) -> bool:
        if checkpoint.opened_at_ms is None:
            raise ValueError("fresh paper opening is missing opened_at_ms")
        return self._store.record(
            ContinuousPaperOpeningLineage(
                opening_plan_id=checkpoint.opening_plan_id,
                feature_snapshot_id=checkpoint.feature_snapshot_id,
                market=checkpoint.market.canonical,
                opened_at_ms=checkpoint.opened_at_ms,
                runtime=self._runtime,
            )
        )


@dataclass(frozen=True, slots=True)
class ContinuousPaperSummary:
    started_at_ms: int
    ended_at_ms: int
    exit_reason: str
    selected_markets: tuple[str, ...]
    processed_records: int
    journal_observations: int
    closed_trades: int
    session_closed_trades: int
    feature_snapshot_count: int
    feature_snapshot_state_digest: str
    opening_lineage_count: int
    opening_lineage_state_digest: str
    trade_path_count: int
    trade_path_state_digest: str
    trade_path_capture_error: str | None
    open_positions: int
    equity: Decimal
    execution_healthy: bool
    execution_reason_codes: tuple[str, ...]
    network_access: bool = True
    live_orders: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "exit_reason": self.exit_reason,
            "selected_markets": list(self.selected_markets),
            "processed_records": self.processed_records,
            "journal_observations": self.journal_observations,
            "closed_trades": self.closed_trades,
            "session_closed_trades": self.session_closed_trades,
            "feature_snapshot_count": self.feature_snapshot_count,
            "feature_snapshot_state_digest": self.feature_snapshot_state_digest,
            "opening_lineage_count": self.opening_lineage_count,
            "opening_lineage_state_digest": self.opening_lineage_state_digest,
            "trade_path_count": self.trade_path_count,
            "trade_path_state_digest": self.trade_path_state_digest,
            "trade_path_capture_error": self.trade_path_capture_error,
            "open_positions": self.open_positions,
            "equity": str(self.equity),
            "execution_healthy": self.execution_healthy,
            "execution_reason_codes": list(self.execution_reason_codes),
            "network_access": self.network_access,
            "live_orders": self.live_orders,
        }


def _market_from_canonical(value: str) -> MarketId:
    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, MarketId):
        return value.canonical
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _payload_json(value: object) -> str:
    return json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _record_from_public(event: RecordedPublicEvent) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=int(event.receive_time.timestamp() * 1000),
        source=event.source,
        schema_version=event.schema_version,
        market=event.market.canonical,
        exchange_time_ms=event.exchange_time_ms,
        event_key=event.event_key,
        payload_json=_payload_json(event.payload),
        event_kind=event.kind,
    )


def _record_from_stream(event: StreamEvent) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=int(event.receive_time.timestamp() * 1000),
        source=event.source,
        schema_version=event.schema_version,
        market=event.market.canonical,
        exchange_time_ms=event.exchange_time_ms,
        event_key=event.event_key,
        payload_json=_payload_json(event.payload),
        event_kind=event.kind.value,
    )


def _record_from_gap(gap: DataGap) -> ReplayRecord:
    payload = {
        "stream_id": gap.stream_id,
        "started_ms": gap.started_ms,
        "ended_ms": gap.ended_ms,
        "reason": gap.reason,
    }
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=gap.started_ms,
        source=gap.source,
        schema_version=gap.schema_version,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap:{gap.stream_id}:{gap.started_ms}:{gap.ended_ms}:{gap.reason}",
        payload_json=_payload_json(payload),
        event_kind=None,
    )


def _record_payload(record: ReplayRecord) -> dict[str, object]:
    return {
        "record_kind": record.record_kind.value,
        "available_at_ms": record.available_at_ms,
        "source": record.source,
        "schema_version": record.schema_version,
        "market": record.market,
        "exchange_time_ms": record.exchange_time_ms,
        "event_key": record.event_key,
        "payload_json": record.payload_json,
        "event_kind": record.event_kind,
    }


def _record_from_payload(raw: object) -> ReplayRecord:
    if not isinstance(raw, dict):
        raise ValueError("checkpoint replay record must be an object")
    return ReplayRecord(
        record_kind=SourceRecordKind(str(raw["record_kind"])),
        available_at_ms=int(raw["available_at_ms"]),
        source=str(raw["source"]),
        schema_version=int(raw["schema_version"]),
        market=None if raw.get("market") is None else str(raw["market"]),
        exchange_time_ms=(
            None if raw.get("exchange_time_ms") is None else int(raw["exchange_time_ms"])
        ),
        event_key=None if raw.get("event_key") is None else str(raw["event_key"]),
        payload_json=str(raw["payload_json"]),
        event_kind=None if raw.get("event_kind") is None else str(raw["event_kind"]),
    )


def _position_action_payload(action: PositionAction) -> dict[str, object]:
    return {
        "action_type": action.action_type.value,
        "market": action.market.canonical,
        "quantity": None if action.quantity is None else str(action.quantity),
        "new_stop_price": (
            None if action.new_stop_price is None else str(action.new_stop_price)
        ),
        "reason_codes": list(action.reason_codes),
        "timestamp_ms": action.timestamp_ms,
    }


def _position_action_from_payload(raw: object) -> PositionAction:
    if not isinstance(raw, dict):
        raise ValueError("position action checkpoint must be an object")
    reason_codes = raw.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(value, str) for value in reason_codes
    ):
        raise ValueError("position action reason_codes are invalid")
    quantity_raw = raw.get("quantity")
    stop_raw = raw.get("new_stop_price")
    return PositionAction(
        action_type=PositionActionType(str(raw["action_type"])),
        market=_market_from_canonical(str(raw["market"])),
        quantity=None if quantity_raw is None else Decimal(str(quantity_raw)),
        new_stop_price=None if stop_raw is None else Decimal(str(stop_raw)),
        reason_codes=tuple(reason_codes),
        timestamp_ms=int(raw["timestamp_ms"]),
    )

def _checkpoint_payload(
    pipeline: BaselineReplayPipeline,
    *,
    last_available_at_ms: int,
    selected_markets: tuple[MarketId, ...],
) -> dict[str, object]:
    checkpoints = []
    for item in pipeline.open_lifecycle_checkpoints:
        checkpoints.append(
            {
                "market": item.market.canonical,
                "opening_plan_id": item.opening_plan_id,
                "feature_snapshot_id": item.feature_snapshot_id,
                "equity_before": str(item.equity_before),
                "exit_plan_ids": list(item.exit_plan_ids),
                "position_actions": [
                    _position_action_payload(action)
                    for action in item.position_actions
                ],
                "mark_observations": [
                    _record_payload(record) for record in item.mark_observations
                ],
            }
        )
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "last_available_at_ms": last_available_at_ms,
        "selected_markets": [market.canonical for market in selected_markets],
        "open_lifecycles": checkpoints,
        "known_gap_intervals": [
            [started_ms, ended_ms]
            for started_ms, ended_ms in pipeline.known_gap_intervals
        ],
        "execution_mode": "paper",
        "live_orders": False,
    }


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _load_checkpoint(path: Path) -> tuple[
    tuple[OpenLifecycleCheckpoint, ...],
    tuple[tuple[int, int | None], ...],
    int,
]:
    if not path.exists():
        return (), (), 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("continuous paper checkpoint is invalid")
    if raw.get("run_id") != RUN_ID or raw.get("execution_mode") != "paper":
        raise ValueError("continuous paper checkpoint authority mismatch")
    if raw.get("live_orders") is not False:
        raise ValueError("continuous paper checkpoint cannot authorize live orders")
    lifecycle_raw = raw.get("open_lifecycles")
    gap_raw = raw.get("known_gap_intervals")
    if not isinstance(lifecycle_raw, list) or not isinstance(gap_raw, list):
        raise ValueError("continuous paper checkpoint arrays are invalid")
    checkpoints: list[OpenLifecycleCheckpoint] = []
    for item in lifecycle_raw:
        if not isinstance(item, dict):
            raise ValueError("continuous paper lifecycle checkpoint is invalid")
        exit_ids = item.get("exit_plan_ids")
        actions = item.get("position_actions", [])
        marks = item.get("mark_observations")
        if not isinstance(exit_ids, list) or not all(isinstance(v, str) for v in exit_ids):
            raise ValueError("continuous paper exit_plan_ids are invalid")
        if not isinstance(actions, list):
            raise ValueError("continuous paper position actions are invalid")
        if not isinstance(marks, list):
            raise ValueError("continuous paper mark observations are invalid")
        checkpoints.append(
            OpenLifecycleCheckpoint(
                market=_market_from_canonical(str(item["market"])),
                opening_plan_id=str(item["opening_plan_id"]),
                feature_snapshot_id=str(item["feature_snapshot_id"]),
                equity_before=Decimal(str(item["equity_before"])),
                exit_plan_ids=tuple(exit_ids),
                position_actions=tuple(
                    _position_action_from_payload(action) for action in actions
                ),
                mark_observations=tuple(_record_from_payload(record) for record in marks),
            )
        )
    gaps: list[tuple[int, int | None]] = []
    for item in gap_raw:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("continuous paper gap interval is invalid")
        gaps.append((int(item[0]), None if item[1] is None else int(item[1])))
    return tuple(checkpoints), tuple(gaps), int(raw.get("last_available_at_ms", 0))


def _restore_cadence_shadow(
    path: Path,
    selected_markets: tuple[MarketId, ...],
    *,
    replay_config: BaselineReplayConfig,
) -> CadenceShadowComparator:
    shadow = CadenceShadowComparator(
        selected_markets,
        replay_config=replay_config,
    )
    if not path.exists():
        return shadow
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        shadow.restore_state(raw)
        shadow.reconcile_markets(selected_markets)
    except Exception as exc:
        shadow = CadenceShadowComparator(
            selected_markets,
            replay_config=replay_config,
        )
        shadow.mark_state_restore_error(
            f"{type(exc).__name__}: {exc}"
        )
    return shadow


def _native_market_snapshots(
    reader: InfoClient,
    *,
    received_at_ms: int,
) -> dict[str, PerpMarketSnapshot]:
    raw = reader.meta_and_asset_ctxs("")
    snapshots = normalize_meta_and_asset_ctxs("", raw, received_at_ms=received_at_ms)
    return {snapshot.meta.market.canonical: snapshot for snapshot in snapshots}


def _ranked_selection(
    snapshots: dict[str, PerpMarketSnapshot],
    *,
    as_of_ms: int,
    deep_limit: int,
    pinned: tuple[MarketId, ...],
) -> tuple[MarketId, ...]:
    _feature_map, ranks = _startup_ranks(snapshots, as_of_ms=as_of_ms)
    ranked = [rank.market for rank in ranks if rank.market.dex == ""]
    selected = ranked[:deep_limit]
    selected_by_key = {market.canonical: market for market in selected}
    for market in pinned:
        selected_by_key[market.canonical] = market
    return tuple(
        sorted(
            selected_by_key.values(),
            key=lambda market: (
                0 if market.canonical in {item.canonical for item in selected} else 1,
                selected.index(market) if market in selected else deep_limit,
                market.canonical,
            ),
        )
    )


async def _warmup_market(
    reader: InfoClient,
    market: MarketId,
    *,
    end_ms: int,
    config: ContinuousPaperConfig,
) -> tuple[Candle, ...]:
    output: list[Candle] = []
    for interval, bars in (
        ("5m", config.warmup_5m_bars),
        ("15m", config.warmup_15m_bars),
    ):
        start_ms = max(0, end_ms - INTERVAL_MS[interval] * (bars + 2))
        raw = await asyncio.to_thread(
            reader.candles,
            market,
            interval,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        received_at_ms = utc_now_ms()
        output.extend(
            normalize_candles(
                market,
                raw,
                received_at_ms=received_at_ms,
            )
        )
    return tuple(output)


class _RecordPump:
    def __init__(
        self,
        pipeline: BaselineReplayPipeline,
        journal: JournalStore,
        *,
        last_available_at_ms: int,
        cadence_shadow: CadenceShadowComparator | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.journal = journal
        self.cadence_shadow = cadence_shadow
        self.cadence_shadow_error: str | None = None
        self.last_available_at_ms = last_available_at_ms
        self.processed_records = 0
        self.journal_observations = 0
        existing_trades = tuple(journal.iter_trades())
        self._known_trade_ids = {trade.trade_id for trade in existing_trades}
        self._recent_closed_trades: deque[TradeJournalEntry] = deque(
            existing_trades[-10:],
            maxlen=10,
        )
        self.closed_trades = len(self._known_trade_ids)
        self.session_closed_trades = 0
        self.last_observation: JournalObservation | None = None
        self._lock = asyncio.Lock()

    async def process(self, record: ReplayRecord) -> None:
        async with self._lock:
            available = max(self.last_available_at_ms, record.available_at_ms)
            if available != record.available_at_ms:
                record = ReplayRecord(
                    record_kind=record.record_kind,
                    available_at_ms=available,
                    source=record.source,
                    schema_version=record.schema_version,
                    market=record.market,
                    exchange_time_ms=record.exchange_time_ms,
                    event_key=record.event_key,
                    payload_json=record.payload_json,
                    event_kind=record.event_kind,
                )
            observations: tuple[JournalObservation, ...] = self.pipeline.on_record(
                record,
                available,
            )
            for observation in observations:
                self.journal.record_observation(observation)
            if observations:
                self.last_observation = observations[-1]
            for trade in self.pipeline.finalize(available):
                if trade.trade_id in self._known_trade_ids:
                    continue
                self.journal.record_trade(trade)
                self._known_trade_ids.add(trade.trade_id)
                self._recent_closed_trades.append(trade)
                self.closed_trades += 1
                self.session_closed_trades += 1
            if self.cadence_shadow is not None:
                try:
                    self.cadence_shadow.observe(record, available)
                except Exception as exc:
                    self.cadence_shadow_error = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    self.cadence_shadow = None
            self.last_available_at_ms = available
            self.processed_records += 1
            self.journal_observations += len(observations)

    @property
    def recent_closed_trades(self) -> tuple[TradeJournalEntry, ...]:
        return tuple(self._recent_closed_trades)

    def cadence_shadow_payload(self) -> dict[str, object]:
        if self.cadence_shadow_error is not None:
            return {
                "shadow_only": True,
                "execution_authority": False,
                "session_only": False,
                "durable_state": True,
                "enabled": False,
                "error": self.cadence_shadow_error,
            }
        if self.cadence_shadow is None:
            return {
                "shadow_only": True,
                "execution_authority": False,
                "session_only": False,
                "durable_state": True,
                "enabled": False,
                "error": None,
            }
        payload = dict(self.cadence_shadow.summary_payload())
        payload["enabled"] = True
        payload["error"] = None
        return payload

    def reconcile_cadence_shadow(
        self,
        selected_markets: tuple[MarketId, ...],
    ) -> None:
        if self.cadence_shadow is None:
            return
        try:
            self.cadence_shadow.reconcile_markets(selected_markets)
        except Exception as exc:
            self.cadence_shadow_error = (
                f"{type(exc).__name__}: {exc}"
            )
            self.cadence_shadow = None


def _closed_trade_status_payload(trade: TradeJournalEntry) -> dict[str, object]:
    return {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "holding_duration_ms": trade.holding_duration_ms,
        "entry_price": str(trade.entry_price),
        "exit_price": str(trade.exit_price),
        "filled_quantity": str(trade.filled_quantity),
        "initial_stop": str(trade.initial_stop),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "gross_realized_pnl": str(trade.gross_realized_pnl),
        "entry_fees": str(trade.entry_fees),
        "exit_fees": str(trade.exit_fees),
        "funding_cash_pnl": str(trade.funding_cash_pnl),
        "net_pnl": str(trade.net_pnl),
        "net_r": str(trade.net_r),
        "mfe_r": (
            None
            if trade.mfe is None or trade.mfe.r_multiple is None
            else str(trade.mfe.r_multiple)
        ),
        "mae_r": (
            None
            if trade.mae is None or trade.mae.r_multiple is None
            else str(trade.mae.r_multiple)
        ),
        "excursion_complete": bool(
            trade.mfe is not None
            and trade.mae is not None
            and trade.mfe.complete
            and trade.mae.complete
            and trade.mfe.r_multiple is not None
            and trade.mae.r_multiple is not None
        ),
        "exit_reason": trade.exit_reason,
    }



def _closed_trade_performance(
    trades: tuple[TradeJournalEntry, ...],
    feature_store: LearningFeatureSnapshotStore,
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    def summarize(items: tuple[TradeJournalEntry, ...]) -> dict[str, object]:
        count = len(items)
        net_pnl = sum((trade.net_pnl for trade in items), Decimal("0"))
        net_r = sum((trade.net_r for trade in items), Decimal("0"))
        complete_excursions = tuple(
            trade
            for trade in items
            if trade.mfe is not None
            and trade.mae is not None
            and trade.mfe.complete
            and trade.mae.complete
            and trade.mfe.r_multiple is not None
            and trade.mae.r_multiple is not None
        )
        mfe_values = tuple(
            trade.mfe.r_multiple
            for trade in complete_excursions
            if trade.mfe is not None and trade.mfe.r_multiple is not None
        )
        mae_values = tuple(
            trade.mae.r_multiple
            for trade in complete_excursions
            if trade.mae is not None and trade.mae.r_multiple is not None
        )
        mfe_sum = sum(mfe_values, Decimal("0"))
        mae_sum = sum(mae_values, Decimal("0"))
        excursion_count = len(complete_excursions)
        giveback_values = tuple(
            max(
                Decimal("0"),
                trade.mfe.r_multiple - trade.net_r,
            )
            for trade in complete_excursions
            if trade.mfe is not None and trade.mfe.r_multiple is not None
        )
        reached_0_5r = tuple(
            trade
            for trade in complete_excursions
            if trade.mfe is not None
            and trade.mfe.r_multiple is not None
            and trade.mfe.r_multiple >= Decimal("0.5")
        )
        reached_1r = tuple(
            trade
            for trade in complete_excursions
            if trade.mfe is not None
            and trade.mfe.r_multiple is not None
            and trade.mfe.r_multiple >= Decimal("1")
        )

        def mean_giveback(
            reached: tuple[TradeJournalEntry, ...],
        ) -> str | None:
            if not reached:
                return None
            values = tuple(
                max(
                    Decimal("0"),
                    trade.mfe.r_multiple - trade.net_r,
                )
                for trade in reached
                if trade.mfe is not None and trade.mfe.r_multiple is not None
            )
            return str(sum(values, Decimal("0")) / len(values))

        def mean_final_net_r(
            reached: tuple[TradeJournalEntry, ...],
        ) -> str | None:
            if not reached:
                return None
            return str(
                sum((trade.net_r for trade in reached), Decimal("0"))
                / len(reached)
            )

        return {
            "trades": count,
            "wins": sum(1 for trade in items if trade.net_pnl > 0),
            "losses": sum(1 for trade in items if trade.net_pnl < 0),
            "breakeven": sum(1 for trade in items if trade.net_pnl == 0),
            "net_pnl": str(net_pnl),
            "mean_net_pnl": None if count == 0 else str(net_pnl / count),
            "mean_net_r": None if count == 0 else str(net_r / count),
            "average_holding_ms": (
                None
                if count == 0
                else sum(trade.holding_duration_ms for trade in items) // count
            ),
            "complete_excursion_trades": excursion_count,
            "incomplete_or_missing_excursion_trades": count - excursion_count,
            "mean_mfe_r": (
                None if excursion_count == 0 else str(mfe_sum / excursion_count)
            ),
            "mean_mae_r": (
                None if excursion_count == 0 else str(mae_sum / excursion_count)
            ),
            "mfe_ge_0_5r": sum(
                1
                for trade in complete_excursions
                if trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("0.5")
            ),
            "mfe_ge_1r": sum(
                1
                for trade in complete_excursions
                if trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("1")
            ),
            "losses_with_mfe_lt_0_25r": sum(
                1
                for trade in complete_excursions
                if trade.net_pnl < 0
                and trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple < Decimal("0.25")
            ),
            "losses_after_mfe_ge_0_5r": sum(
                1
                for trade in complete_excursions
                if trade.net_pnl < 0
                and trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("0.5")
            ),
            "losses_after_mfe_ge_1r": sum(
                1
                for trade in complete_excursions
                if trade.net_pnl < 0
                and trade.mfe is not None
                and trade.mfe.r_multiple is not None
                and trade.mfe.r_multiple >= Decimal("1")
            ),
            "mean_peak_to_close_giveback_r": (
                None
                if excursion_count == 0
                else str(
                    sum(giveback_values, Decimal("0"))
                    / excursion_count
                )
            ),
            "mean_giveback_after_mfe_ge_0_5r": mean_giveback(
                reached_0_5r
            ),
            "mean_giveback_after_mfe_ge_1r": mean_giveback(reached_1r),
            "positive_closes_after_mfe_ge_0_5r": sum(
                1 for trade in reached_0_5r if trade.net_pnl > 0
            ),
            "positive_closes_after_mfe_ge_1r": sum(
                1 for trade in reached_1r if trade.net_pnl > 0
            ),
            "mean_final_net_r_after_mfe_ge_0_5r": mean_final_net_r(
                reached_0_5r
            ),
            "mean_final_net_r_after_mfe_ge_1r": mean_final_net_r(
                reached_1r
            ),
        }

    def grouped(
        labels: dict[str, list[TradeJournalEntry]],
    ) -> dict[str, dict[str, object]]:
        return {
            label: summarize(tuple(items))
            for label, items in sorted(labels.items())
        }

    gross_profit = sum(
        (trade.net_pnl for trade in trades if trade.net_pnl > 0),
        Decimal("0"),
    )
    gross_loss_abs = -sum(
        (trade.net_pnl for trade in trades if trade.net_pnl < 0),
        Decimal("0"),
    )
    profit_factor = (
        None
        if gross_loss_abs == 0
        else (
            "0"
            if gross_profit == 0
            else str(gross_profit / gross_loss_abs)
        )
    )

    def decision_score_band(score: Decimal) -> str:
        if score < Decimal("65"):
            return "<65"
        if score < Decimal("70"):
            return "65-<70"
        if score < Decimal("75"):
            return "70-<75"
        if score < Decimal("80"):
            return "75-<80"
        return "80+"

    by_side: dict[str, list[TradeJournalEntry]] = {}
    by_exit_reason: dict[str, list[TradeJournalEntry]] = {}
    by_lead_strategy: dict[str, list[TradeJournalEntry]] = {}
    by_decision_score_band: dict[str, list[TradeJournalEntry]] = {}
    by_trend_regime: dict[str, list[TradeJournalEntry]] = {}
    by_volatility_regime: dict[str, list[TradeJournalEntry]] = {}
    decision_fact_attributed_trades = 0
    decision_fact_attribution_misses = 0
    feature_snapshot_fallback_trades = 0
    regime_attribution_misses = 0

    for trade in trades:
        by_side.setdefault(trade.direction.value, []).append(trade)
        by_exit_reason.setdefault(trade.exit_reason, []).append(trade)

        lead_strategy = "unknown"
        score_band = "unknown"
        trend_regime = "unknown"
        volatility_regime = "unknown"
        decision_fact = None
        if trade.replay_run_id is not None:
            try:
                decision_fact = fact_store.load_decision_by_strategy_id(
                    trade.strategy_decision_id,
                    trade.replay_run_id,
                )
            except Exception:
                decision_fact = None

        if decision_fact is not None:
            decision_fact_attributed_trades += 1
            lead_strategy = decision_fact.lead_strategy or "unknown"
            score_band = decision_score_band(decision_fact.score)
            trend_regime = decision_fact.trend_regime.value
            volatility_regime = decision_fact.volatility_regime.value
        else:
            decision_fact_attribution_misses += 1
            try:
                verified = feature_store.load(trade.feature_snapshot_id)
                if verified is not None:
                    feature_snapshot_fallback_trades += 1
                    trend_regime = verified.snapshot.trend_regime.value
                    volatility_regime = verified.snapshot.volatility_regime.value
                else:
                    regime_attribution_misses += 1
            except Exception:
                regime_attribution_misses += 1

        by_lead_strategy.setdefault(lead_strategy, []).append(trade)
        by_decision_score_band.setdefault(score_band, []).append(trade)
        by_trend_regime.setdefault(trend_regime, []).append(trade)
        by_volatility_regime.setdefault(volatility_regime, []).append(trade)

    return {
        **summarize(trades),
        "gross_profit": str(gross_profit),
        "gross_loss_abs": str(gross_loss_abs),
        "profit_factor": profit_factor,
        "decision_fact_attributed_trades": decision_fact_attributed_trades,
        "decision_fact_attribution_misses": decision_fact_attribution_misses,
        "feature_snapshot_fallback_trades": feature_snapshot_fallback_trades,
        "regime_attribution_misses": regime_attribution_misses,
        "unattributed_feature_trades": regime_attribution_misses,
        "by_side": grouped(by_side),
        "by_exit_reason": grouped(by_exit_reason),
        "by_lead_strategy": grouped(by_lead_strategy),
        "by_decision_score_band": grouped(by_decision_score_band),
        "by_trend_regime": grouped(by_trend_regime),
        "by_volatility_regime": grouped(by_volatility_regime),
    }


def _position_protection_metrics(
    *,
    side: str,
    quantity: Decimal,
    entry_price: Decimal,
    stop_price: Decimal,
    latest_mark: Decimal | None,
    planned_risk: Decimal,
) -> dict[str, object]:
    if planned_risk < 0:
        raise ValueError("planned_risk must be non-negative")
    if side == "long":
        stop_pnl = (stop_price - entry_price) * quantity
        unrealized = (
            None
            if latest_mark is None
            else (latest_mark - entry_price) * quantity
        )
    elif side == "short":
        stop_pnl = (entry_price - stop_price) * quantity
        unrealized = (
            None
            if latest_mark is None
            else (entry_price - latest_mark) * quantity
        )
    else:
        raise ValueError("position side must be long or short")
    return {
        "unrealized_gross_pnl": (
            None if unrealized is None else str(unrealized)
        ),
        "current_gross_r": (
            None
            if unrealized is None or planned_risk == 0
            else str(unrealized / planned_risk)
        ),
        "stop_trigger_gross_pnl": str(stop_pnl),
        "stop_trigger_gross_r": (
            None if planned_risk == 0 else str(stop_pnl / planned_risk)
        ),
        "stop_protects_profit": stop_pnl > 0,
    }


def _live_status_payload(
    execution: PaperExecutionAdapter,
    pump: _RecordPump,
    selected_markets: tuple[MarketId, ...],
    feature_store: LearningFeatureSnapshotStore,
    fact_store: EvaluationFactStore,
    *,
    timestamp_ms: int,
) -> dict[str, object]:
    positions: list[dict[str, object]] = []
    for position in execution.account.positions:
        latest_mark = position.latest_mark
        protection = _position_protection_metrics(
            side=position.side.value,
            quantity=position.quantity,
            entry_price=position.average_entry_price,
            stop_price=position.stop_price,
            latest_mark=latest_mark,
            planned_risk=position.planned_risk,
        )
        positions.append(
            {
                "market": position.market.canonical,
                "side": position.side.value,
                "quantity": str(position.quantity),
                "average_entry_price": str(position.average_entry_price),
                "stop_price": str(position.stop_price),
                "latest_mark": (
                    None if latest_mark is None else str(latest_mark)
                ),
                **protection,
                "planned_risk": str(position.planned_risk),
                "opened_at_ms": position.opened_at_ms,
                "opening_plan_id": position.opening_plan_id,
            }
        )
    open_planned_risk = sum(
        (position.planned_risk for position in execution.account.positions),
        Decimal("0"),
    )
    open_planned_risk_fraction = (
        Decimal("0")
        if execution.account.equity == 0
        else open_planned_risk / execution.account.equity
    )
    open_stop_trigger_gross_pnl = sum(
        (
            Decimal(str(position["stop_trigger_gross_pnl"]))
            for position in positions
        ),
        Decimal("0"),
    )
    open_stop_trigger_gross_r = (
        None
        if open_planned_risk == 0
        else open_stop_trigger_gross_pnl / open_planned_risk
    )
    protected_stop_count = sum(
        1
        for position in positions
        if position["stop_protects_profit"] is True
    )
    total_account_pnl = execution.account.equity - execution.account.starting_cash
    total_return_fraction = (
        Decimal("0")
        if execution.account.starting_cash == 0
        else total_account_pnl / execution.account.starting_cash
    )
    gross_open_notional_fraction = (
        Decimal("0")
        if execution.account.equity == 0
        else execution.account.gross_open_notional / execution.account.equity
    )
    closed_trade_performance = _closed_trade_performance(
        tuple(pump.journal.iter_trades()),
        feature_store,
        fact_store,
    )
    activity = pump.pipeline.session_decision_activity
    decision_reason_counts = dict(activity.decision_reason_counts)
    risk_reason_counts = dict(activity.risk_reason_counts)

    observation = pump.last_observation
    last_observation: dict[str, object] | None = None
    if observation is not None:
        last_observation = {
            "kind": observation.kind.value,
            "timestamp_ms": observation.timestamp_ms,
            "market": (
                None
                if observation.market is None
                else observation.market.canonical
            ),
            "reason_codes": list(observation.reason_codes),
            "plan_id": observation.plan_id,
        }
    return {
        "kind": "continuous-paper-heartbeat",
        "timestamp_ms": timestamp_ms,
        "paper_only": True,
        "live_orders": False,
        "selected_market_count": len(selected_markets),
        "selected_markets": [
            market.canonical for market in selected_markets
        ],
        "processed_records": pump.processed_records,
        "journal_observations": pump.journal_observations,
        "closed_trades": pump.closed_trades,
        "session_closed_trades": pump.session_closed_trades,
        "recent_closed_trades": [
            _closed_trade_status_payload(trade)
            for trade in reversed(pump.recent_closed_trades)
        ],
        "closed_trade_performance": closed_trade_performance,
        "open_planned_risk": str(open_planned_risk),
        "open_planned_risk_fraction_of_equity": str(
            open_planned_risk_fraction
        ),
        "open_stop_trigger_gross_pnl": str(open_stop_trigger_gross_pnl),
        "open_stop_trigger_gross_r": (
            None
            if open_stop_trigger_gross_r is None
            else str(open_stop_trigger_gross_r)
        ),
        "open_positions_with_profit_protected_stop": protected_stop_count,
        "gross_open_notional": str(execution.account.gross_open_notional),
        "gross_open_notional_fraction_of_equity": str(
            gross_open_notional_fraction
        ),
        "available_margin": str(execution.account.available_margin),
        "session_decision_epochs": activity.decision_epochs,
        "last_decision_boundary_ms": activity.last_decision_boundary_ms,
        "last_decision_evaluated_at_ms": activity.last_decision_evaluated_at_ms,
        "session_decisions": {
            "long": activity.long_decisions,
            "short": activity.short_decisions,
            "no_trade": activity.no_trade_decisions,
        },
        "session_decision_reason_counts": decision_reason_counts,
        "session_risk": {
            "evaluations": activity.risk_evaluations,
            "approvals": activity.risk_approvals,
            "rejections": activity.risk_rejections,
            "reason_counts": risk_reason_counts,
        },
        "session_opening_execution_attempts": activity.opening_execution_attempts,
        "session_opening_fills": activity.opening_fills,
        "cadence_shadow": pump.cadence_shadow_payload(),
        "open_position_count": len(positions),
        "positions": positions,
        "starting_cash": str(execution.account.starting_cash),
        "cash": str(execution.account.cash),
        "equity": str(execution.account.equity),
        "total_account_pnl": str(total_account_pnl),
        "total_return_fraction": str(total_return_fraction),
        "unrealized_pnl": str(execution.account.unrealized_pnl),
        "realized_gross_pnl": str(execution.account.realized_gross_pnl),
        "cumulative_fees": str(execution.account.cumulative_fees),
        "cumulative_funding": str(execution.account.cumulative_funding),
        "execution_healthy": execution.health.healthy_for_new_exposure,
        "execution_reason_codes": list(execution.health.reason_codes),
        "last_observation": last_observation,
    }


def _emit_live_status(
    execution: PaperExecutionAdapter,
    pump: _RecordPump,
    selected_markets: tuple[MarketId, ...],
    feature_store: LearningFeatureSnapshotStore,
    fact_store: EvaluationFactStore,
    *,
    timestamp_ms: int,
) -> None:
    payload = _live_status_payload(
        execution,
        pump,
        selected_markets,
        feature_store,
        fact_store,
        timestamp_ms=timestamp_ms,
    )
    print(
        "COCOMELON_PAPER_HEARTBEAT "
        + json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        flush=True,
    )


def _restore_open_lifecycles(
    pipeline: BaselineReplayPipeline,
    execution: PaperExecutionAdapter,
    checkpoints: tuple[OpenLifecycleCheckpoint, ...],
) -> None:
    account_markets = {position.market.canonical for position in execution.account.positions}
    checkpoint_markets = {item.market.canonical for item in checkpoints}
    if account_markets != checkpoint_markets:
        raise RuntimeError(
            "paper account/open-lifecycle checkpoint mismatch; refusing unsafe restart"
        )

    for checkpoint in checkpoints:
        opening_plan = execution.store.load_plan(checkpoint.opening_plan_id)
        if opening_plan is None:
            raise RuntimeError("opening plan missing during paper runtime restore")
        opening_attempts, opening_fills = execution.store.load_execution_history(
            opening_plan.plan_id
        )
        filled_opening_attempts = tuple(
            attempt for attempt in opening_attempts if attempt.filled_quantity > 0
        )
        if len(filled_opening_attempts) != 1:
            raise RuntimeError("paper runtime restore requires one filled opening attempt")
        opening_attempt = filled_opening_attempts[0]
        opening_attempt_fills = tuple(
            fill for fill in opening_fills if fill.attempt_id == opening_attempt.attempt_id
        )

        exit_plans: list[PaperOrderPlan] = []
        exit_attempts: list[ExecutionAttempt] = []
        exit_fills: list[PaperFill] = []
        for plan_id in checkpoint.exit_plan_ids:
            plan = execution.store.load_plan(plan_id)
            if plan is None:
                raise RuntimeError("exit plan missing during paper runtime restore")
            exit_plans.append(plan)
            attempts, fills = execution.store.load_execution_history(plan_id)
            exit_attempts.extend(attempts)
            exit_fills.extend(fills)

        position = next(
            position
            for position in execution.account.positions
            if position.market == checkpoint.market
        )
        funding = execution.store.load_funding_for_market(
            checkpoint.market,
            start_ms=position.opened_at_ms,
        )
        pipeline.restore_open_lifecycle(
            checkpoint,
            opening_plan=opening_plan,
            opening_attempt=opening_attempt,
            opening_fills=opening_attempt_fills,
            exit_plans=tuple(exit_plans),
            exit_attempts=tuple(exit_attempts),
            exit_fills=tuple(exit_fills),
            funding_accruals=funding,
        )


async def run_continuous_paper_session(
    state_root: str | Path,
    config: ContinuousPaperConfig,
    *,
    settings: Settings | None = None,
    stop_file: str | Path | None = None,
    runtime_identity: ContinuousPaperRuntimeIdentity | None = None,
) -> ContinuousPaperSummary:
    settings = settings or Settings.from_env()
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise RuntimeError("continuous paper runtime refuses non-paper execution mode")

    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    stop_path = None if stop_file is None else Path(stop_file)
    if stop_path is not None and stop_path.exists():
        stop_path.unlink()
    started_at_ms = utc_now_ms()
    checkpoint_path = root / CHECKPOINT_FILENAME
    checkpoints, gap_intervals, restored_available_at_ms = _load_checkpoint(checkpoint_path)

    reader = InfoClient(settings)
    execution = PaperExecutionAdapter(
        root / "paper.sqlite3",
        BaselineReplayConfig().execution,
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=started_at_ms,
    )
    journal = JournalStore(root / "journal.sqlite3")
    facts = EvaluationFactStore(root / "facts.sqlite3")
    feature_store = LearningFeatureSnapshotStore(root / "learning-features")
    opening_lineage_store = ContinuousPaperOpeningLineageStore(
        root / "opening-lineage"
    )
    trade_path_store = ContinuousPaperTradePathStore(root / "trade-paths")
    trade_path_sink = _ContinuousTradePathSink(trade_path_store)

    try:
        if not execution.health.healthy_for_new_exposure:
            raise RuntimeError(
                "paper execution state is unhealthy: "
                + ",".join(execution.health.reason_codes)
            )

        initial_received_at_ms = utc_now_ms()
        snapshots = await asyncio.to_thread(
            _native_market_snapshots,
            reader,
            received_at_ms=initial_received_at_ms,
        )
        pinned = tuple(position.market for position in execution.account.positions)
        selected = _ranked_selection(
            snapshots,
            as_of_ms=initial_received_at_ms,
            deep_limit=config.deep_limit,
            pinned=pinned,
        )
        if not selected:
            raise RuntimeError("continuous paper scan produced no rankable native markets")

        replay_config = BaselineReplayConfig()
        pipeline = BaselineReplayPipeline(
            replay_config,
            execution,
            facts,
            selected_markets=selected,
            replay_run_id=RUN_ID,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            feature_snapshot_sink=feature_store,
            opening_lifecycle_sink=(
                None
                if runtime_identity is None
                else _ContinuousOpeningLineageSink(
                    opening_lineage_store,
                    runtime_identity,
                )
            ),
            closed_lifecycle_sink=trade_path_sink,
        )
        pipeline.restore_gap_intervals(gap_intervals)
        _restore_open_lifecycles(pipeline, execution, checkpoints)
        cadence_shadow = _restore_cadence_shadow(
            root / CADENCE_SHADOW_STATE_FILENAME,
            selected,
            replay_config=replay_config,
        )
        pump = _RecordPump(
            pipeline,
            journal,
            last_available_at_ms=restored_available_at_ms,
            cadence_shadow=cadence_shadow,
        )

        selected_keys = {market.canonical for market in selected}
        for market in selected:
            snapshot = snapshots.get(market.canonical)
            if snapshot is None:
                raise RuntimeError(
                    "selected market missing from native registry: "
                    f"{market.canonical}"
                )
            await pump.process(_record_from_public(market_snapshot_record_event(snapshot)))
        for market in selected:
            for candle in await _warmup_market(
                reader,
                market,
                end_ms=started_at_ms,
                config=config,
            ):
                await pump.process(_record_from_public(candle_record_event(candle)))

        async def refresh_funding() -> None:
            now_ms = utc_now_ms()
            for position in tuple(execution.account.positions):
                start_ms = max(position.opened_at_ms, now_ms - 8 * 60 * 60 * 1000)
                raw = await asyncio.to_thread(
                    reader.funding_history,
                    position.market,
                    start_ms=start_ms,
                    end_ms=now_ms,
                )
                received_at_ms = utc_now_ms()
                for rate in normalize_funding_history(
                    position.market,
                    raw,
                    received_at_ms=received_at_ms,
                ):
                    await pump.process(
                        _record_from_public(funding_rate_record_event(rate))
                    )

        await refresh_funding()

        def persist_checkpoint() -> None:
            _write_json_atomic(
                checkpoint_path,
                _checkpoint_payload(
                    pipeline,
                    last_available_at_ms=pump.last_available_at_ms,
                    selected_markets=selected,
                ),
            )
            _write_json_atomic(
                root / CADENCE_SHADOW_FILENAME,
                pump.cadence_shadow_payload(),
            )
            if pump.cadence_shadow is not None:
                _write_json_atomic(
                    root / CADENCE_SHADOW_STATE_FILENAME,
                    pump.cadence_shadow.state_payload(),
                )

        persist_checkpoint()
        _emit_live_status(
            execution,
            pump,
            selected,
            feature_store,
            facts,
            timestamp_ms=utc_now_ms(),
        )

        async def connection_factory() -> Any:
            return await connect_mainnet_ws(settings)

        async def start_supervisors(
            markets: tuple[MarketId, ...],
        ) -> tuple[tuple[WebSocketSupervisor, ...], tuple[asyncio.Task[None], ...]]:
            plan = DeepWatchlistManager().reconcile(markets)
            async def event_sink(event: StreamEvent) -> None:
                await pump.process(_record_from_stream(event))

            async def gap_sink(gap: DataGap) -> None:
                await pump.process(_record_from_gap(gap))

            mux = RedundantStreamMux(event_sink=event_sink, gap_sink=gap_sink)
            supervisors: list[WebSocketSupervisor] = []
            tasks: list[asyncio.Task[None]] = []
            for lane in range(2):
                async def lane_event_sink(event: StreamEvent, lane: int = lane) -> None:
                    await mux.on_event(lane, event)

                async def lane_gap_sink(gap: DataGap, lane: int = lane) -> None:
                    await mux.on_gap(lane, gap)

                supervisor = WebSocketSupervisor(
                    connection_factory,
                    plan.subscribe,
                    event_sink=lane_event_sink,
                    gap_sink=lane_gap_sink,
                    clock_ms=utc_now_ms,
                    utcnow=lambda: datetime.now(UTC),
                )
                supervisors.append(supervisor)
                tasks.append(asyncio.create_task(supervisor.run()))
            return tuple(supervisors), tuple(tasks)

        _supervisors, supervisor_tasks = await start_supervisors(selected)
        deadline_ms = started_at_ms + config.duration_seconds * 1000
        next_selection_refresh_ms = started_at_ms + config.selection_refresh_seconds * 1000
        next_checkpoint_ms = started_at_ms + config.checkpoint_seconds * 1000

        exit_reason = "duration_elapsed"
        try:
            while utc_now_ms() < deadline_ms:
                if stop_path is not None and stop_path.exists():
                    exit_reason = "upgrade_requested"
                    break
                now_ms = utc_now_ms()
                sleep_seconds = min(
                    float(config.context_poll_seconds),
                    max(0.1, (deadline_ms - now_ms) / 1000),
                )
                await asyncio.sleep(sleep_seconds)
                now_ms = utc_now_ms()
                if stop_path is not None and stop_path.exists():
                    exit_reason = "upgrade_requested"
                    break

                refreshed = await asyncio.to_thread(
                    _native_market_snapshots,
                    reader,
                    received_at_ms=now_ms,
                )
                for market in selected:
                    snapshot = refreshed.get(market.canonical)
                    if snapshot is not None:
                        await pump.process(
                            _record_from_public(market_snapshot_record_event(snapshot))
                        )
                await refresh_funding()

                if now_ms >= next_selection_refresh_ms:
                    pinned = tuple(
                        position.market for position in execution.account.positions
                    )
                    desired = _ranked_selection(
                        refreshed,
                        as_of_ms=now_ms,
                        deep_limit=config.deep_limit,
                        pinned=pinned,
                    )
                    desired_keys = {market.canonical for market in desired}
                    added = tuple(
                        market
                        for market in desired
                        if market.canonical not in selected_keys
                    )
                    for market in added:
                        snapshot = refreshed.get(market.canonical)
                        if snapshot is None:
                            raise RuntimeError(
                                f"newly selected market missing from registry: {market.canonical}"
                            )
                        await pump.process(
                            _record_from_public(market_snapshot_record_event(snapshot))
                        )
                        for candle in await _warmup_market(
                            reader,
                            market,
                            end_ms=now_ms,
                            config=config,
                        ):
                            await pump.process(
                                _record_from_public(candle_record_event(candle))
                            )
                    if desired_keys != selected_keys:
                        for task in supervisor_tasks:
                            task.cancel()
                        await asyncio.gather(*supervisor_tasks, return_exceptions=True)
                        selected = desired
                        selected_keys = desired_keys
                        pipeline.reconcile_markets(selected)
                        pump.reconcile_cadence_shadow(selected)
                        _supervisors, supervisor_tasks = await start_supervisors(selected)
                    next_selection_refresh_ms = (
                        now_ms + config.selection_refresh_seconds * 1000
                    )

                _emit_live_status(
                    execution,
                    pump,
                    selected,
                    feature_store,
                    facts,
                    timestamp_ms=now_ms,
                )

                if now_ms >= next_checkpoint_ms:
                    persist_checkpoint()
                    next_checkpoint_ms = now_ms + config.checkpoint_seconds * 1000

                failed = tuple(
                    task for task in supervisor_tasks if task.done() and not task.cancelled()
                )
                for task in failed:
                    exc = task.exception()
                    if exc is not None:
                        raise exc
        finally:
            for task in supervisor_tasks:
                task.cancel()
            await asyncio.gather(*supervisor_tasks, return_exceptions=True)

        persist_checkpoint()
        ended_at_ms = utc_now_ms()
        closed_trades = tuple(journal.iter_trades())
        summary = ContinuousPaperSummary(
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            exit_reason=exit_reason,
            selected_markets=tuple(market.canonical for market in selected),
            processed_records=pump.processed_records,
            journal_observations=pump.journal_observations,
            closed_trades=len(closed_trades),
            session_closed_trades=pump.session_closed_trades,
            feature_snapshot_count=len(feature_store.iter_verified()),
            feature_snapshot_state_digest=feature_store.state_digest,
            opening_lineage_count=opening_lineage_store.record_count,
            opening_lineage_state_digest=opening_lineage_store.state_digest,
            trade_path_count=trade_path_store.record_count,
            trade_path_state_digest=trade_path_store.state_digest,
            trade_path_capture_error=trade_path_sink.error,
            open_positions=len(execution.account.positions),
            equity=execution.account.equity,
            execution_healthy=execution.health.healthy_for_new_exposure,
            execution_reason_codes=execution.health.reason_codes,
        )
        _write_json_atomic(root / SUMMARY_FILENAME, summary.payload())
        return summary
    finally:
        facts.close()
        journal.close()
        execution.close()
