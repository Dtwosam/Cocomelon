from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import (
    Candle,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.replay import EvidenceClass, ReplayRecord
from cocomelon.domain.risk import (
    ExecutionCostEstimate,
    LiquidityRiskState,
    RiskHealthState,
    RiskLimits,
    RiskRequest,
)
from cocomelon.domain.strategy import Direction, StrategyContext
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import empty_account, risk_state_from_paper
from cocomelon.execution.interface import OpeningSubmission, PositionManagement
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.journal.assembler import (
    JournalInconsistency,
    TradeLifecycleInput,
    assemble_trade_journal_entry,
)
from cocomelon.journal.observations import (
    observation_from_account_state,
    observation_from_execution,
    observation_from_position_action,
    observation_from_risk,
    observation_from_strategy,
)
from cocomelon.journal.store import JournalStore
from cocomelon.replay.adapters import ReplayRequirements
from cocomelon.replay.engine import ReplayEngine, ReplayPipeline
from cocomelon.replay.manifest import build_replay_manifest
from cocomelon.replay.source import JsonlReplaySource, validate_recording
from cocomelon.strategies.engine import evaluate_strategies

MARKET = MarketId("", "BTC")
AS_OF_MS = 30_000
OPEN_BOOK_MS = 30_260
STOP_MARK_MS = 40_000
CLOSE_BOOK_MS = 40_300
STARTING_CASH = Decimal("10000")
EXECUTION_CONFIG = PaperExecutionConfig()


def _feature(direction: Direction, *, deep_ready: bool = True) -> FeatureSnapshot:
    sign = Decimal("1") if direction is not Direction.SHORT else Decimal("-1")
    return FeatureSnapshot(
        market=MARKET,
        as_of_ms=AS_OF_MS,
        source_received_at_ms=29_000,
        schema_version=1,
        day_return=sign * Decimal("0.02"),
        funding=Decimal("0"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=sign * Decimal("0.01"),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=sign * Decimal("0.005"),
        return_15m=sign * Decimal("0.01"),
        return_1h=sign * Decimal("0.02"),
        return_4h=sign * Decimal("0.03"),
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.3"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=sign * Decimal("0.2"),
        book_age_ms=100,
        trend_regime=(
            TrendRegime.DOWN if direction is Direction.SHORT else TrendRegime.UP
        ),
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("phase8-replay-fixture",),
    )


def _market_snapshot(feature: FeatureSnapshot) -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=MARKET,
            wire_name=MARKET.wire_name,
            sz_decimals=2,
            max_leverage=20,
            margin_table_id=1,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=MARKET,
            mark_px=Decimal("100"),
            mid_px=Decimal("100"),
            oracle_px=Decimal("100"),
            funding=feature.funding,
            open_interest=feature.open_interest,
            day_ntl_vlm=feature.day_notional_volume,
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="phase8-replay-fixture",
        received_at_ms=29_000,
        schema_version=1,
    )


def _candle(index: int, *, low: str, high: str, close: str) -> Candle:
    end_ms = (index + 1) * 1_000
    return Candle(
        market=MARKET,
        interval="15m",
        start_ms=index * 1_000,
        end_ms=end_ms,
        open_px=Decimal(close),
        high_px=Decimal(high),
        low_px=Decimal(low),
        close_px=Decimal(close),
        volume=Decimal("100"),
        trade_count=10,
        source="phase8-replay-fixture",
        received_at_ms=end_ms,
        schema_version=1,
    )


def _candles(direction: Direction) -> tuple[Candle, ...]:
    if direction is Direction.SHORT:
        prior = tuple(
            _candle(index, low="100", high="110", close="105")
            for index in range(20)
        )
        return (*prior, _candle(20, low="80", high="104", close="99"))
    prior = tuple(
        _candle(index, low="90", high="100", close="95")
        for index in range(20)
    )
    return (*prior, _candle(20, low="96", high="120", close="101"))


def _strategy_context(
    direction: Direction,
    *,
    deep_ready: bool = True,
) -> StrategyContext:
    feature = _feature(direction, deep_ready=deep_ready)
    return StrategyContext(
        market_snapshot=_market_snapshot(feature),
        feature_snapshot=feature,
        eligibility=EligibilityDecision(
            market=MARKET,
            rankable=True,
            deep_ready=deep_ready,
            reasons=(),
        ),
        candles_5m=(),
        candles_15m=_candles(direction),
        microstructure=None,
        as_of_ms=AS_OF_MS,
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=29_900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _receive_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _append_event(
    root: Path,
    *,
    kind: str,
    receive_ms: int,
    exchange_ms: int | None,
    event_key: str,
    payload: dict[str, object],
) -> None:
    path = root / f"events/1970-01-01/{kind}/{MARKET.canonical}/segment-000001.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "record_type": "normalized_event",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "kind": kind,
        "market": MARKET.canonical,
        "exchange_time_ms": exchange_ms,
        "receive_time": _receive_time(receive_ms),
        "event_key": event_key,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _write_recording(root: Path, direction: Direction, *, no_fill: bool = False) -> None:
    _append_event(
        root,
        kind="candle",
        receive_ms=AS_OF_MS,
        exchange_ms=21_000,
        event_key="candle:BTC:15m:20000:fixture",
        payload={
            "start_ms": 20_000,
            "end_ms": 21_000,
            "interval": "15m",
            "open_px": "101",
            "close_px": "101" if direction is not Direction.SHORT else "99",
            "high_px": "120" if direction is not Direction.SHORT else "104",
            "low_px": "96" if direction is not Direction.SHORT else "80",
            "volume": "100",
            "trade_count": 10,
        },
    )

    if direction is Direction.SHORT:
        open_bid = "99" if no_fill else "100"
        open_ask = "100.1"
    else:
        open_bid = "99.9"
        open_ask = "101" if no_fill else "100"
    _append_event(
        root,
        kind="l2_book",
        receive_ms=OPEN_BOOK_MS,
        exchange_ms=30_250,
        event_key=f"l2Book:BTC:30250:{open_bid}:{open_ask}",
        payload={
            "bids": [{"px": open_bid, "sz": "100", "n": 1}],
            "asks": [{"px": open_ask, "sz": "100", "n": 1}],
        },
    )

    stop_mark = "104" if direction is Direction.SHORT else "96"
    _append_event(
        root,
        kind="active_asset_ctx",
        receive_ms=STOP_MARK_MS,
        exchange_ms=None,
        event_key=f"activeAssetCtx:BTC:{STOP_MARK_MS}:{stop_mark}",
        payload={
            "mark_px": stop_mark,
            "mid_px": stop_mark,
            "oracle_px": stop_mark,
            "funding": "0",
            "open_interest": "1000",
        },
    )

    close_bid = "103.9" if direction is Direction.SHORT else "96"
    close_ask = "104" if direction is Direction.SHORT else "96.1"
    _append_event(
        root,
        kind="l2_book",
        receive_ms=CLOSE_BOOK_MS,
        exchange_ms=40_290,
        event_key=f"l2Book:BTC:40290:{close_bid}:{close_ask}",
        payload={
            "bids": [{"px": close_bid, "sz": "100", "n": 1}],
            "asks": [{"px": close_ask, "sz": "100", "n": 1}],
        },
    )


def _manifest(root: Path):
    return build_replay_manifest(
        validate_recording(root),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=AS_OF_MS,
        end_ms=CLOSE_BOOK_MS,
        code_revision="phase8-integration-fixture",
        config_snapshot={"execution_mode": "paper", "network_access": False},
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config=EXECUTION_CONFIG,
    )


def _book_event(record: ReplayRecord) -> StreamEvent:
    payload = record.payload
    assert isinstance(payload, dict)

    def side(name: str) -> tuple[dict[str, object], ...]:
        raw_rows = payload[name]
        assert isinstance(raw_rows, list)
        rows: list[dict[str, object]] = []
        for raw in raw_rows:
            assert isinstance(raw, dict)
            rows.append(
                {
                    "px": Decimal(str(raw["px"])),
                    "sz": Decimal(str(raw["sz"])),
                    "n": int(raw["n"]),
                }
            )
        return tuple(rows)

    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=record.exchange_time_ms,
        receive_time=datetime.fromtimestamp(record.available_at_ms / 1000, tz=UTC),
        schema_version=record.schema_version,
        source=record.source,
        event_key=record.event_key or "missing-l2-key",
        payload={"bids": side("bids"), "asks": side("asks")},
    )


def _mark_event(record: ReplayRecord) -> StreamEvent:
    payload = record.payload
    assert isinstance(payload, dict)
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp(record.available_at_ms / 1000, tz=UTC),
        schema_version=record.schema_version,
        source=record.source,
        event_key=record.event_key or "missing-context-key",
        payload={
            "mark_px": Decimal(str(payload["mark_px"])),
            "mid_px": Decimal(str(payload["mid_px"])),
            "oracle_px": Decimal(str(payload["oracle_px"])),
            "funding": Decimal(str(payload["funding"])),
            "open_interest": Decimal(str(payload["open_interest"])),
        },
    )


class _ReplayHarness:
    def __init__(
        self,
        execution_path: Path,
        direction: Direction,
        *,
        deep_ready: bool = True,
        reject_health: bool = False,
    ) -> None:
        self.direction = direction
        self.deep_ready = deep_ready
        self.reject_health = reject_health
        self.adapter = PaperExecutionAdapter(
            execution_path,
            EXECUTION_CONFIG,
            starting_cash=STARTING_CASH,
            startup_timestamp_ms=29_900,
        )
        self.decision = None
        self.opening: OpeningSubmission | None = None
        self.closing: PositionManagement | None = None
        self.mark_record: ReplayRecord | None = None
        self.mark_event: StreamEvent | None = None
        self.equity_before = self.adapter.account.equity

    def _risk_request(self, timestamp_ms: int) -> RiskRequest:
        assert self.decision is not None
        risk_account, open_positions = risk_state_from_paper(self.adapter.account)
        direction = self.decision.direction
        return RiskRequest(
            strategy_decision=self.decision,
            entry_reference_price=Decimal("100"),
            correlation_bucket="crypto_beta",
            account_state=risk_account,
            open_positions=open_positions,
            health_state=RiskHealthState(
                market_data_fresh=True,
                account_state_fresh=True,
                execution_health_ok=not self.reject_health,
                state_consistent=True,
                as_of_ms=timestamp_ms,
            ),
            cost_estimate=ExecutionCostEstimate(
                entry_slippage_fraction=Decimal("0.0005"),
                stop_slippage_fraction=Decimal("0.0010"),
                round_trip_fee_fraction=Decimal("0.0009"),
            ),
            liquidity_state=LiquidityRiskState(
                entry_side_visible_notional_25bps=Decimal("100000"),
                exit_side_visible_notional_25bps=Decimal("100000"),
                venue_max_leverage=Decimal("20"),
                liquidation_price=(
                    Decimal("110") if direction is Direction.SHORT else Decimal("90")
                ),
                venue_min_notional=Decimal("10"),
                as_of_ms=timestamp_ms,
            ),
            limits=RiskLimits(),
            timestamp_ms=timestamp_ms,
        )

    def on_record(self, record: ReplayRecord, now_ms: int):
        observations = []
        if record.event_kind == "candle":
            evaluation = evaluate_strategies(
                _strategy_context(self.direction, deep_ready=self.deep_ready)
            )
            self.decision = evaluation.decision
            observations.append(
                observation_from_strategy(self.decision, replay_run_id=None)
            )
            return tuple(observations)

        if record.event_kind == "active_asset_ctx":
            self.mark_record = record
            self.mark_event = _mark_event(record)
            return ()

        if record.event_kind != "l2_book" or self.decision is None:
            return ()

        if self.opening is None:
            self.opening = self.adapter.submit_risk_request(
                self._risk_request(AS_OF_MS),
                _instrument(),
                _book_event(record),
                reference_price=Decimal("100"),
                created_at_ms=AS_OF_MS,
                attempt_timestamp_ms=now_ms,
            )
            observations.append(
                observation_from_risk(self.opening.risk_decision, replay_run_id=None)
            )
            if self.opening.simulation is not None:
                observations.append(
                    observation_from_execution(
                        self.opening.simulation.attempt,
                        replay_run_id=None,
                    )
                )
            observations.append(
                observation_from_account_state(self.opening.account, replay_run_id=None)
            )
            return tuple(observations)

        if not self.adapter.account.positions or self.mark_event is None:
            return ()

        reference = Decimal("104") if self.direction is Direction.SHORT else Decimal("96")
        self.closing = self.adapter.manage_position(
            MARKET,
            _instrument(),
            self.mark_event,
            _book_event(record),
            strategy_decision=self.decision,
            strategy_fresh=False,
            critical_health=False,
            explicit_reduction_quantity=None,
            reference_price=reference,
            timestamp_ms=STOP_MARK_MS,
            attempt_timestamp_ms=now_ms,
        )
        observations.append(
            observation_from_position_action(self.closing.action, replay_run_id=None)
        )
        if self.closing.simulation is not None:
            observations.append(
                observation_from_execution(
                    self.closing.simulation.attempt,
                    replay_run_id=None,
                )
            )
        observations.append(
            observation_from_account_state(self.closing.account, replay_run_id=None)
        )
        return tuple(observations)

    def finalize(self, _end_ms: int):
        try:
            if (
                self.opening is None
                or self.opening.plan is None
                or self.opening.simulation is None
                or not self.opening.simulation.fills
                or self.closing is None
                or self.closing.plan is None
                or self.closing.simulation is None
                or not self.closing.simulation.fills
                or self.mark_record is None
                or self.decision is None
            ):
                return ()
            result = assemble_trade_journal_entry(
                TradeLifecycleInput(
                    feature_snapshot_id=self.decision.feature_snapshot_id,
                    opening_plan=self.opening.plan,
                    opening_attempt=self.opening.simulation.attempt,
                    exit_plans=(self.closing.plan,),
                    exit_attempts=(self.closing.simulation.attempt,),
                    fills=(
                        *self.opening.simulation.fills,
                        *self.closing.simulation.fills,
                    ),
                    position_actions=(self.closing.action,),
                    funding_accruals=(),
                    equity_before=self.equity_before,
                    equity_after=self.closing.account.equity,
                    exit_reason=self.closing.action.reason_codes[0],
                    mark_observations=(self.mark_record,),
                    known_gap_intervals=(),
                    evidence_class=EvidenceClass.MICROSTRUCTURE,
                    replay_run_id=None,
                )
            )
            assert not isinstance(result, JournalInconsistency), result
            return (result,)
        finally:
            self.adapter.close()

    def pipeline(self) -> ReplayPipeline:
        return ReplayPipeline(
            on_record=self.on_record,
            finalize=self.finalize,
            requirements=ReplayRequirements(requires_l2=True),
        )


def _run(
    root: Path,
    journal: JournalStore,
    execution_path: Path,
    direction: Direction,
    *,
    deep_ready: bool = True,
    reject_health: bool = False,
):
    harness = _ReplayHarness(
        execution_path,
        direction,
        deep_ready=deep_ready,
        reject_health=reject_health,
    )
    result = ReplayEngine(
        JsonlReplaySource(root),
        journal,
        harness.pipeline(),
    ).run(_manifest(root))
    return result, harness


def test_replay_account_state_observation_preserves_deterministic_state_id() -> None:
    account = empty_account(STARTING_CASH, AS_OF_MS)

    first = observation_from_account_state(account, replay_run_id=None)
    second = observation_from_account_state(account, replay_run_id=None)

    assert first.kind.value == "account_state"
    assert first.timestamp_ms == account.updated_at_ms
    assert first.account_state_id == account.state_id
    assert first == second


@pytest.mark.parametrize("direction", (Direction.LONG, Direction.SHORT))
def test_microstructure_replay_is_deterministic_through_phase5_to_phase8(
    tmp_path: Path,
    direction: Direction,
) -> None:
    root = tmp_path / "recording"
    _write_recording(root, direction)
    journal = JournalStore(tmp_path / "journal.sqlite3")

    first, first_harness = _run(
        root,
        journal,
        tmp_path / "paper-first.sqlite3",
        direction,
    )
    second, second_harness = _run(
        root,
        journal,
        tmp_path / "paper-second.sqlite3",
        direction,
    )

    assert first == second
    assert first.result_digest == second.result_digest
    assert first.risk_approvals == 1
    assert first.risk_rejections == 0
    assert first.execution_attempts == 2
    assert first.opened_positions == 1
    assert first.closed_positions == 1
    assert len(first.closed_trade_ids) == 1
    assert first_harness.adapter.account.positions == ()
    assert second_harness.adapter.account.positions == ()

    row = journal.connection.execute(
        "SELECT payload_json FROM journal_trades WHERE trade_id = ?",
        (first.closed_trade_ids[0],),
    ).fetchone()
    assert row is not None
    trade = json.loads(row[0])
    assert trade["direction"] == direction.value
    assert Decimal(trade["net_pnl"]) < 0
    assert Decimal(trade["net_r"]) < 0
    assert Decimal(trade["entry_fees"]) > 0
    assert Decimal(trade["exit_fees"]) > 0
    assert trade["mfe"]["complete"] is True
    assert trade["mae"]["complete"] is True
    journal.close()


def test_no_trade_and_risk_rejection_replay_create_zero_exposure(tmp_path: Path) -> None:
    root = tmp_path / "recording"
    _write_recording(root, Direction.LONG)
    journal = JournalStore(tmp_path / "journal.sqlite3")

    no_trade, no_trade_harness = _run(
        root,
        journal,
        tmp_path / "paper-no-trade.sqlite3",
        Direction.LONG,
        deep_ready=False,
    )
    rejected, rejected_harness = _run(
        root,
        JournalStore(tmp_path / "journal-reject.sqlite3"),
        tmp_path / "paper-reject.sqlite3",
        Direction.LONG,
        reject_health=True,
    )

    assert no_trade.risk_approvals == 0
    assert no_trade.risk_rejections == 1
    assert no_trade.execution_attempts == 0
    assert no_trade.closed_positions == 0
    assert no_trade_harness.adapter.account.positions == ()
    assert rejected.risk_approvals == 0
    assert rejected.risk_rejections == 1
    assert rejected.execution_attempts == 0
    assert rejected.closed_positions == 0
    assert rejected_harness.adapter.account.positions == ()
    journal.close()


def test_zero_fill_replay_journals_attempt_without_creating_exposure(tmp_path: Path) -> None:
    root = tmp_path / "recording"
    _write_recording(root, Direction.LONG, no_fill=True)
    journal = JournalStore(tmp_path / "journal.sqlite3")

    result, harness = _run(
        root,
        journal,
        tmp_path / "paper-no-fill.sqlite3",
        Direction.LONG,
    )

    assert result.risk_approvals == 1
    assert result.execution_attempts == 1
    assert result.fills == 0
    assert result.closed_positions == 0
    assert harness.adapter.account.positions == ()
    journal.close()
