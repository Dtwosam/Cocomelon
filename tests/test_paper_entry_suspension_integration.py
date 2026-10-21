from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    PaperExecutionConfig,
    PositionActionType,
)
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.baseline import RecordedStateBook, replay_record_stream_event
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation
from cocomelon.evidence.lifecycle import BaselineReplayPipeline
from cocomelon.execution.funding import FundingAccrual
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.paper_entry_suspension import PaperEntrySuspension, load_entry_suspension

MARKET = MarketId("", "BTC")
START_MS = 1_000_000


def _risk(direction: Direction = Direction.LONG) -> RiskDecision:
    return RiskDecision(
        strategy_decision_id=f"suspension-{direction.value}",
        market=MARKET,
        direction=direction,
        approved=True,
        reason_codes=("risk_approved",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("20"),
        approved_notional=Decimal("200"),
        entry_reference_price=Decimal("100"),
        stop_price=Decimal("95") if direction is Direction.LONG else Decimal("105"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
        correlation_bucket="crypto_beta",
        binding_caps=(),
        timestamp_ms=START_MS,
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=4,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=START_MS - 1_000,
        metadata_source="hyperliquid-mainnet-public-fixture",
    )


def _event(kind: StreamKind, timestamp_ms: int, payload: dict) -> StreamEvent:
    return StreamEvent(
        kind=kind,
        market=MARKET,
        exchange_time_ms=timestamp_ms,
        receive_time=datetime.fromtimestamp(timestamp_ms / 1_000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-public-fixture",
        event_key=f"{kind.value}:{timestamp_ms}",
        payload=payload,
    )


def _book(
    timestamp_ms: int, *, bid: str = "99.9", ask: str = "100.1", size: str = "1000"
) -> StreamEvent:
    return _event(
        StreamKind.L2_BOOK,
        timestamp_ms,
        {
            "bids": ({"px": Decimal(bid), "sz": Decimal(size), "n": 1},),
            "asks": ({"px": Decimal(ask), "sz": Decimal(size), "n": 1},),
        },
    )


def _adapter(path: Path, *, suspended: bool) -> PaperExecutionAdapter:
    return PaperExecutionAdapter(
        path,
        PaperExecutionConfig(),
        starting_cash=Decimal("10000"),
        startup_timestamp_ms=START_MS - 2_000,
        entries_suspended=suspended,
    )


@pytest.mark.parametrize("direction", (Direction.LONG, Direction.SHORT))
def test_suspended_adapter_rejects_direct_opening_without_health_or_account_mutation(
    tmp_path: Path, direction: Direction
) -> None:
    # Removing the adapter's gate must create real exposure and fail this test.
    execution = _adapter(tmp_path / "paper.sqlite3", suspended=True)
    try:
        before = execution.account
        submitted = execution.submit_opening(
            _risk(direction),
            _instrument(),
            _book(START_MS + 300),
            reference_price=Decimal("100"),
            created_at_ms=START_MS,
            attempt_timestamp_ms=START_MS + 300,
        )
        assert submitted.rejection is not None
        assert submitted.rejection.reason == "PAPER_ENTRIES_SUSPENDED"
        assert submitted.plan is None
        assert submitted.simulation is None
        assert execution.account == before
        assert execution.health.healthy_for_new_exposure is True
        assert execution.store.table_counts()["paper_order_plans"] == 0
        assert execution.store.table_counts()["paper_execution_attempts"] == 0
        assert execution.store.table_counts()["paper_fills"] == 0
        assert execution.session_opening_attempts == 0
        assert execution.session_opening_fills == 0
        assert execution.session_blocked_openings == 1
        assert execution.pending_reduce_only_count == 0
    finally:
        execution.close()


def _record(kind: str, timestamp_ms: int, payload: dict) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=timestamp_ms,
        source="hyperliquid-mainnet-public-fixture",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=timestamp_ms,
        event_key=f"{kind}:{timestamp_ms}",
        payload_json=json.dumps(payload, default=str, sort_keys=True),
        event_kind=kind,
    )


def _book_record(timestamp_ms: int, **kwargs: str) -> ReplayRecord:
    event = _book(timestamp_ms, **kwargs)
    return _record(event.kind.value, timestamp_ms, dict(event.payload))


def _context(timestamp_ms: int, mark: str = "100") -> ReplayRecord:
    return _record(
        "active_asset_ctx",
        timestamp_ms,
        {
            "mark_px": mark,
            "mid_px": mark,
            "oracle_px": mark,
            "funding": "0",
            "open_interest": "1000000",
        },
    )


def _snapshot(timestamp_ms: int) -> ReplayRecord:
    return _record(
        "market_snapshot",
        timestamp_ms,
        {
            "meta": {
                "wire_name": MARKET.wire_name,
                "sz_decimals": 4,
                "max_leverage": 20,
                "margin_table_id": 1,
                "only_isolated": False,
                "is_delisted": False,
                "margin_mode": None,
            },
            "context": {
                "mark_px": "100",
                "mid_px": "100",
                "oracle_px": "100",
                "funding": "0",
                "open_interest": "1000000",
                "day_ntl_vlm": "500000000",
                "premium": "0",
                "prev_day_px": "99",
            },
        },
    )


def _epoch(timestamp_ms: int, direction: Direction, *, stop: str | None = None) -> DecisionEpoch:
    feature = FeatureSnapshot(
        market=MARKET,
        as_of_ms=timestamp_ms,
        source_received_at_ms=timestamp_ms - 1,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("0.002"),
        return_15m=Decimal("0.01"),
        return_1h=None,
        return_4h=None,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("0.1"),
        book_age_ms=10,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("paper-entry-suspension-integration",),
    )
    invalidation = stop or ("95" if direction is Direction.LONG else "105")
    decision = StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal(invalidation),
        signal_ids=("fixture-signal",),
        reason_codes=("fixture-directional",),
    )
    return DecisionEpoch(
        boundary_ms=timestamp_ms - 30_000,
        evaluated_at_ms=timestamp_ms,
        markets=(
            EpochMarketEvaluation(
                feature=feature,
                eligibility=EligibilityDecision(
                    market=MARKET, rankable=True, deep_ready=True, reasons=()
                ),
                decision=decision,
            ),
        ),
    )


class _ScriptedDecisionEngine:
    """Only signals are scripted; books, risk, manager, fills and stores are real."""

    def __init__(self, config: BaselineReplayConfig, epochs: tuple[DecisionEpoch, ...]):
        self._state = RecordedStateBook(microstructure_window_ms=config.microstructure_window_ms)
        self._epochs = list(epochs)

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def seed(self, record: ReplayRecord, now_ms: int) -> None:
        self._state.apply(record, now_ms)

    def observe(self, record: ReplayRecord, now_ms: int) -> tuple[DecisionEpoch, ...]:
        self.seed(record, now_ms)
        ready = []
        while self._epochs and self._epochs[0].evaluated_at_ms <= now_ms:
            ready.append(self._epochs.pop(0))
        return tuple(ready)

    def flush(self, _end_ms: int) -> tuple[DecisionEpoch, ...]:
        return ()


def _pipeline(
    execution: PaperExecutionAdapter,
    facts: EvaluationFactStore,
    *,
    epochs: tuple[DecisionEpoch, ...] = (),
    cutoff_ms: int | None = 0,
    opening_observer: object | None = None,
) -> BaselineReplayPipeline:
    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    return BaselineReplayPipeline(
        config,
        execution,
        facts,
        selected_markets=(MARKET,),
        replay_run_id="paper-entry-suspension-integration",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        decision_engine=_ScriptedDecisionEngine(config, epochs),
        new_exposure_cutoff_ms=cutoff_ms,
        opening_research_observer=opening_observer,  # type: ignore[arg-type]
    )


def _feed(pipeline: BaselineReplayPipeline, *records: ReplayRecord) -> None:
    for record in records:
        pipeline.on_record(record, record.available_at_ms)


def _restored_held_position(
    tmp_path: Path,
    direction: Direction = Direction.LONG,
    *,
    epochs: tuple[DecisionEpoch, ...] = (),
    policy: PaperEntrySuspension | None = None,
) -> tuple[BaselineReplayPipeline, PaperExecutionAdapter, EvaluationFactStore]:
    """A real filled lifecycle crosses a closed/reopened SQLite account handoff."""
    account_path = tmp_path / "paper.sqlite3"
    facts_path = tmp_path / "facts.sqlite3"
    execution = _adapter(account_path, suspended=False)
    facts = EvaluationFactStore(facts_path)
    predecessor = _pipeline(execution, facts, epochs=(_epoch(START_MS, direction),), cutoff_ms=None)
    _feed(
        predecessor,
        _snapshot(START_MS - 1_000),
        _context(START_MS),
        _book_record(START_MS + 300),
    )
    assert len(execution.account.positions) == 1
    checkpoint = predecessor.open_lifecycle_checkpoints[0]
    before = execution.account
    counts = execution.store.table_counts()
    facts.close()
    execution.close()

    restored = _adapter(
        account_path, suspended=True if policy is None else policy.entries_suspended
    )
    restored_facts = EvaluationFactStore(facts_path)
    assert restored.account == before
    assert restored.store.table_counts() == counts
    assert restored.health.healthy_for_new_exposure is True
    plan = restored.store.load_plan(checkpoint.opening_plan_id)
    assert plan is not None
    attempts, fills = restored.store.load_execution_history(plan.plan_id)
    attempt = next(a for a in attempts if a.filled_quantity > 0)
    successor = _pipeline(
        restored,
        restored_facts,
        epochs=epochs,
        cutoff_ms=0 if policy is None else policy.new_exposure_cutoff_ms,
    )
    successor.restore_open_lifecycle(
        checkpoint,
        opening_plan=plan,
        opening_attempt=attempt,
        opening_fills=tuple(f for f in fills if f.attempt_id == attempt.attempt_id),
    )
    _feed(successor, _snapshot(START_MS + 400))
    return successor, restored, restored_facts


@pytest.mark.parametrize(
    ("direction", "mark", "bid", "ask"),
    ((Direction.LONG, "94", "93.9", "94.1"), (Direction.SHORT, "106", "105.9", "106.1")),
)
def test_restored_held_stop_really_fills_after_suspension_without_reentry(
    tmp_path: Path, direction: Direction, mark: str, bid: str, ask: str
) -> None:
    # Gating management instead of entries must leave the position open and fail.
    pipeline, execution, facts = _restored_held_position(
        tmp_path, direction, epochs=(_epoch(START_MS + 700, direction),)
    )
    try:
        opening_plan_id = execution.account.positions[0].opening_plan_id
        _feed(
            pipeline,
            _context(START_MS + 700, mark),
            _book_record(START_MS + 1_000, bid=bid, ask=ask),
            _book_record(START_MS + 1_400, bid=bid, ask=ask),
        )
        assert execution.account.positions == ()
        trades = pipeline.finalize(START_MS + 1_400)
        assert len(trades) == 1
        assert trades[0].entry_fees > 0
        assert trades[0].exit_fees > 0
        assert trades[0].exit_reason == "MARK_STOP_TRIGGERED"
        assert len(tuple(facts.iter_decision_facts())) == 2
        assert execution.store.table_counts()["paper_order_plans"] == 2
        assert execution.session_opening_attempts == 0
        assert execution.session_opening_fills == 0
        assert execution.pending_reduce_only_count == 0
        assert execution.store.load_plan(opening_plan_id).reduce_only is False
    finally:
        facts.close()
        execution.close()


def test_staged_before_cutoff_cannot_fill_on_first_eligible_later_book(tmp_path: Path) -> None:
    # Removing the attempt-time cutoff lets a previously staged candidate fill.
    execution = _adapter(tmp_path / "paper.sqlite3", suspended=False)
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    pipeline = _pipeline(
        execution, facts, epochs=(_epoch(START_MS, Direction.LONG),), cutoff_ms=START_MS + 100
    )
    try:
        _feed(pipeline, _snapshot(START_MS - 1_000), _context(START_MS))
        assert pipeline.pending_opening_markets == (MARKET,)
        _feed(pipeline, _book_record(START_MS + 300), _book_record(START_MS + 600))
        assert execution.account.positions == ()
        assert execution.store.table_counts()["paper_order_plans"] == 0
        assert execution.store.table_counts()["paper_execution_attempts"] == 0
        assert execution.store.table_counts()["paper_fills"] == 0
        assert len(tuple(facts.iter_decision_facts())) == 1
        assert execution.health.healthy_for_new_exposure is True
    finally:
        facts.close()
        execution.close()


@pytest.mark.parametrize("held", (Direction.LONG, Direction.SHORT))
def test_fresh_opposite_thesis_can_close_but_cannot_reverse_after_suspension(
    tmp_path: Path, held: Direction
) -> None:
    opposite = Direction.SHORT if held is Direction.LONG else Direction.LONG
    pipeline, execution, facts = _restored_held_position(
        tmp_path, held, epochs=(_epoch(START_MS + 700, opposite),)
    )
    try:
        _feed(
            pipeline,
            _context(START_MS + 700),
            _book_record(START_MS + 1_000),
            _book_record(START_MS + 1_400),
        )
        assert execution.account.positions == ()
        trades = pipeline.finalize(START_MS + 1_400)
        assert len(trades) == 1
        assert trades[0].exit_reason == "OPPOSITE_FRESH_THESIS"
        assert trades[0].direction is held
        assert len(tuple(facts.iter_decision_facts())) == 2
        assert execution.store.table_counts()["paper_order_plans"] == 2
        assert execution.session_opening_attempts == 0
        assert execution.session_opening_fills == 0
    finally:
        facts.close()
        execution.close()


def test_suspended_stop_preserves_latency_retry_until_real_reduce_only_fill(tmp_path: Path) -> None:
    pipeline, execution, facts = _restored_held_position(tmp_path)
    try:
        original = execution.account.positions[0]
        _feed(
            pipeline,
            _context(START_MS + 700, "94"),
            _book_record(START_MS + 800, bid="93.9", ask="94.1"),
        )
        assert execution.account.positions[0].quantity == original.quantity
        assert execution.pending_reduce_only_count == 1
        assert execution.store.table_counts()["paper_fills"] == 1
        _feed(pipeline, _book_record(START_MS + 1_000, bid="93.9", ask="94.1"))
        assert execution.account.positions == ()
        assert execution.pending_reduce_only_count == 0
        assert execution.store.table_counts()["paper_fills"] == 2
        assert len(pipeline.finalize(START_MS + 1_000)) == 1
        assert execution.session_opening_attempts == 0
    finally:
        facts.close()
        execution.close()


def test_suspended_adapter_rejects_original_full_risk_request(tmp_path: Path) -> None:
    # Checking only submit_opening would miss an independent risk-request bypass.
    class Recorder:
        def __init__(self) -> None:
            self.traces = []

        def record_opening_trace(self, trace: object) -> None:
            self.traces.append(trace)

    recorder = Recorder()
    control = _adapter(tmp_path / "control.sqlite3", suspended=False)
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    pipeline = _pipeline(
        control,
        facts,
        epochs=(_epoch(START_MS, Direction.LONG),),
        cutoff_ms=None,
        opening_observer=recorder,
    )
    blocked = _adapter(tmp_path / "blocked.sqlite3", suspended=True)
    try:
        _feed(
            pipeline, _snapshot(START_MS - 1_000), _context(START_MS), _book_record(START_MS + 300)
        )
        assert len(control.account.positions) == 1
        assert len(recorder.traces) == 1
        trace = recorder.traces[0]
        submitted = blocked.submit_risk_request(
            trace.risk_request,
            trace.instrument,
            trace.book_event,
            reference_price=Decimal("100"),
            created_at_ms=START_MS,
            attempt_timestamp_ms=START_MS + 300,
        )
        assert submitted.rejection is not None
        assert submitted.rejection.reason == "PAPER_ENTRIES_SUSPENDED"
        assert submitted.simulation is None
        assert submitted.plan is None
        assert blocked.account.positions == ()
        assert blocked.session_opening_attempts == 0
        assert blocked.session_blocked_openings == 1
        assert blocked.health.healthy_for_new_exposure is True
        assert blocked.store.table_counts()["paper_order_plans"] == 0
    finally:
        facts.close()
        control.close()
        blocked.close()


@pytest.mark.parametrize("direction", (Direction.LONG, Direction.SHORT))
def test_partial_ioc_remainder_cannot_reopen_or_top_up_but_held_stop_executes(
    tmp_path: Path, direction: Direction
) -> None:
    # An IOC remainder is not a resting entry that may later fill after suspension.
    path = tmp_path / "paper.sqlite3"
    predecessor = _adapter(path, suspended=False)
    partial = predecessor.submit_opening(
        _risk(direction),
        _instrument(),
        _book(START_MS + 300, size="0.5"),
        reference_price=Decimal("100"),
        created_at_ms=START_MS,
        attempt_timestamp_ms=START_MS + 300,
    )
    assert partial.simulation is not None
    assert partial.simulation.attempt.result is ExecutionResult.PARTIAL
    assert partial.account.positions[0].quantity == Decimal("0.5")
    before = predecessor.account
    predecessor.close()
    execution = _adapter(path, suspended=True)
    try:
        assert execution.account == before
        rejected = execution.submit_opening(
            _risk(direction),
            _instrument(),
            _book(START_MS + 600),
            reference_price=Decimal("100"),
            created_at_ms=START_MS,
            attempt_timestamp_ms=START_MS + 600,
        )
        assert rejected.rejection.reason == "PAPER_ENTRIES_SUSPENDED"
        assert execution.account.positions[0].quantity == Decimal("0.5")
        assert execution.store.table_counts()["paper_execution_attempts"] == 1
        stop = "94" if direction is Direction.LONG else "106"
        managed = execution.manage_position(
            MARKET,
            _instrument(),
            replay_record_stream_event(_context(START_MS + 700, stop)),
            _book(START_MS + 1_000, bid=stop, ask=str(Decimal(stop) + Decimal("0.1"))),
            strategy_decision=None,
            strategy_fresh=False,
            critical_health=False,
            explicit_reduction_quantity=None,
            reference_price=Decimal(stop),
            timestamp_ms=START_MS + 700,
            attempt_timestamp_ms=START_MS + 1_000,
        )
        assert managed.action.action_type is PositionActionType.EXIT_STOP
        assert managed.plan is not None and managed.plan.reduce_only is True
        assert managed.plan.requested_quantity == Decimal("0.5")
        assert managed.simulation.attempt.result is ExecutionResult.FULL
        assert execution.account.positions == ()
        assert execution.session_opening_attempts == 0
        assert execution.session_opening_fills == 0
        assert execution.pending_reduce_only_count == 0
    finally:
        execution.close()


def test_no_fill_protection_keeps_position_then_retries_while_entries_blocked(
    tmp_path: Path,
) -> None:
    pipeline, execution, facts = _restored_held_position(tmp_path)
    try:
        quantity = execution.account.positions[0].quantity
        _feed(
            pipeline,
            _context(START_MS + 700, "94"),
            _book_record(START_MS + 1_000, bid="90", ask="98"),
        )
        assert execution.account.positions[0].quantity == quantity
        assert execution.store.table_counts()["paper_fills"] == 1
        assert pipeline.finalize(START_MS + 1_000) == ()
        _feed(pipeline, _book_record(START_MS + 1_300, bid="93.9", ask="94.1"))
        assert execution.account.positions == ()
        assert len(pipeline.finalize(START_MS + 1_300)) == 1
        assert execution.session_opening_attempts == 0
    finally:
        facts.close()
        execution.close()


@pytest.mark.parametrize(("direction", "stop"), ((Direction.LONG, "97"), (Direction.SHORT, "103")))
def test_suspension_preserves_real_stop_tightening_and_durable_protection(
    tmp_path: Path, direction: Direction, stop: str
) -> None:
    pipeline, execution, facts = _restored_held_position(
        tmp_path, direction, epochs=(_epoch(START_MS + 700, direction, stop=stop),)
    )
    try:
        quantity = execution.account.positions[0].quantity
        _feed(pipeline, _context(START_MS + 700), _book_record(START_MS + 1_000))
        assert execution.account.positions[0].stop_price == Decimal(stop)
        assert execution.account.positions[0].quantity == quantity
        assert execution.store.table_counts()["paper_fills"] == 1
        assert execution.health.healthy_for_new_exposure is True
    finally:
        facts.close()
        execution.close()
    recovered = _adapter(tmp_path / "paper.sqlite3", suspended=True)
    try:
        assert recovered.account.positions[0].stop_price == Decimal(stop)
        assert recovered.account.positions[0].quantity == quantity
        assert recovered.entries_suspended is True
    finally:
        recovered.close()


@pytest.mark.parametrize("requested_fraction", (Decimal("0.5"), Decimal("2")))
def test_explicit_reduction_cannot_reverse_or_increase_suspended_exposure(
    tmp_path: Path, requested_fraction: Decimal
) -> None:
    pipeline, execution, facts = _restored_held_position(tmp_path)
    del pipeline
    try:
        quantity = execution.account.positions[0].quantity
        requested = quantity * requested_fraction
        managed = execution.manage_position(
            MARKET,
            _instrument(),
            replay_record_stream_event(_context(START_MS + 700)),
            _book(START_MS + 1_000),
            strategy_decision=None,
            strategy_fresh=False,
            critical_health=False,
            explicit_reduction_quantity=requested,
            reference_price=Decimal("100"),
            timestamp_ms=START_MS + 700,
            attempt_timestamp_ms=START_MS + 1_000,
        )
        assert managed.action.action_type is PositionActionType.REDUCE
        assert managed.plan is not None and managed.plan.reduce_only is True
        assert managed.plan.requested_quantity <= quantity
        assert managed.simulation.attempt.result is ExecutionResult.FULL
        remaining = sum((p.quantity for p in execution.account.positions), Decimal("0"))
        assert Decimal("0") <= remaining < quantity
        assert execution.session_opening_attempts == 0
        assert execution.session_opening_fills == 0
    finally:
        facts.close()
        execution.close()


def test_real_execution_write_failure_keeps_protection_then_emergency_exit_runs(
    tmp_path: Path,
) -> None:
    # The gate cannot suppress emergency management after a real durable-store fault.
    pipeline, execution, facts = _restored_held_position(tmp_path)
    try:
        before = execution.account
        with execution.store.raw_connection() as connection:
            connection.execute(
                "CREATE TRIGGER reject_account_write BEFORE INSERT ON paper_account_state "
                "BEGIN SELECT RAISE(ABORT, 'fixture account fault'); END"
            )
        with pytest.raises(sqlite3.IntegrityError, match="fixture account fault"):
            execution.mark_account_to_market({MARKET: Decimal("101")}, timestamp_ms=START_MS + 600)
        assert execution.account == before
        assert execution.health.healthy_for_new_exposure is False
        with execution.store.raw_connection() as connection:
            connection.execute("DROP TRIGGER reject_account_write")
        _feed(pipeline, _context(START_MS + 700), _book_record(START_MS + 1_000))
        assert execution.account.positions == ()
        trades = pipeline.finalize(START_MS + 1_000)
        assert len(trades) == 1
        assert trades[0].exit_reason == "CRITICAL_EXECUTION_OR_ACCOUNT_HEALTH"
        assert execution.session_opening_attempts == 0
        assert execution.session_opening_fills == 0
        saved = execution.account
    finally:
        facts.close()
        execution.close()
    recovered = _adapter(tmp_path / "paper.sqlite3", suspended=True)
    try:
        assert recovered.account == saved
        assert recovered.health.healthy_for_new_exposure is True
        blocked = recovered.submit_opening(
            _risk(),
            _instrument(),
            _book(START_MS + 2_000),
            reference_price=Decimal("100"),
            created_at_ms=START_MS + 1_500,
            attempt_timestamp_ms=START_MS + 2_000,
        )
        assert blocked.rejection.reason == "PAPER_ENTRIES_SUSPENDED"
        assert recovered.account == saved
    finally:
        recovered.close()


def test_policy_write_failure_never_disables_actual_held_stop_or_marks_health_bad(
    tmp_path: Path,
) -> None:
    policy_root = tmp_path / "policy"
    policy_root.mkdir()
    # A real filesystem conflict makes the atomic temporary-file write fail.
    (policy_root / "paper-entry-suspension.tmp").mkdir()
    policy = load_entry_suspension(policy_root, timestamp_ms=START_MS + 400)
    assert policy.restore_status == "write_failed"
    assert policy.durable is False
    assert policy.entries_suspended is True
    pipeline, execution, facts = _restored_held_position(tmp_path, policy=policy)
    try:
        held = execution.account.positions[0]
        _feed(pipeline, _context(START_MS + 500), _book_record(START_MS + 600))
        assert execution.account.positions[0].opening_plan_id == held.opening_plan_id
        assert execution.account.positions[0].opened_at_ms == held.opened_at_ms
        assert execution.account.positions[0].stop_price == held.stop_price
        assert execution.account.positions[0].quantity == held.quantity
        assert execution.health.healthy_for_new_exposure is True
        assert execution.store.table_counts()["paper_order_plans"] == 1
        _feed(
            pipeline,
            _context(START_MS + 700, "94"),
            _book_record(START_MS + 1_000, bid="93.9", ask="94.1"),
        )
        assert execution.account.positions == ()
        assert pipeline.finalize(START_MS + 1_000)[0].exit_reason == "MARK_STOP_TRIGGERED"
        assert execution.session_opening_attempts == 0
    finally:
        facts.close()
        execution.close()


def test_funding_is_still_booked_once_and_survives_suspended_account_restore(
    tmp_path: Path,
) -> None:
    pipeline, execution, facts = _restored_held_position(tmp_path)
    del pipeline
    try:
        position = execution.account.positions[0]
        original_cash = execution.account.cash
        original_fees = execution.account.cumulative_fees
        payment = FundingAccrual(
            market=MARKET,
            boundary_ms=3_600_000,
            position_id=position.position_id,
            signed_quantity=position.quantity,
            oracle_price=Decimal("100"),
            funding_rate=Decimal("0.001"),
            cash_delta=-(position.quantity * Decimal("0.1")),
            oracle_event_key="fixture-original-oracle",
            funding_source="hyperliquid-mainnet-public-fixture",
            funding_received_at_ms=3_600_100,
        )
        execution.apply_funding(payment, timestamp_ms=3_600_100)
        saved = execution.account
        assert saved.cash == original_cash + payment.cash_delta
        assert saved.cumulative_fees == original_fees
        execution.apply_funding(payment, timestamp_ms=3_600_200)
        assert execution.account == saved
    finally:
        facts.close()
        execution.close()
    recovered = _adapter(tmp_path / "paper.sqlite3", suspended=True)
    try:
        assert recovered.account == saved
        assert recovered.store.table_counts()["paper_funding_events"] == 1
        assert recovered.health.healthy_for_new_exposure is True
        assert recovered.entries_suspended is True
    finally:
        recovered.close()


@pytest.mark.parametrize("exit_state", ("latency", "partial"))
def test_unfinished_protective_exit_survives_real_account_and_lifecycle_handoff(
    tmp_path: Path, exit_state: str
) -> None:
    # A handoff must preserve reduction history and never replay the opening.
    pipeline, execution, facts = _restored_held_position(tmp_path)
    quantity = execution.account.positions[0].quantity
    _feed(pipeline, _context(START_MS + 700, "94"))
    if exit_state == "latency":
        _feed(pipeline, _book_record(START_MS + 800, bid="93.9", ask="94.1"))
        assert execution.pending_reduce_only_count == 1
        assert execution.account.positions[0].quantity == quantity
    else:
        _feed(pipeline, _book_record(START_MS + 1_000, bid="93.9", ask="94.1", size="0.1"))
        assert execution.account.positions[0].quantity == quantity - Decimal("0.1")
    checkpoint = pipeline.open_lifecycle_checkpoints[0]
    before = execution.account
    counts = execution.store.table_counts()
    facts.close()
    execution.close()

    successor = _adapter(tmp_path / "paper.sqlite3", suspended=True)
    successor_facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        assert successor.account == before
        assert successor.store.table_counts() == counts
        assert successor.health.healthy_for_new_exposure is True
        opening_plan = successor.store.load_plan(checkpoint.opening_plan_id)
        attempts, fills = successor.store.load_execution_history(opening_plan.plan_id)
        opening_attempt = next(a for a in attempts if a.filled_quantity > 0)
        exit_plans = tuple(
            successor.store.load_plan(plan_id) for plan_id in checkpoint.exit_plan_ids
        )
        exit_histories = tuple(
            successor.store.load_execution_history(p.plan_id) for p in exit_plans
        )
        restored = _pipeline(successor, successor_facts)
        restored.restore_open_lifecycle(
            checkpoint,
            opening_plan=opening_plan,
            opening_attempt=opening_attempt,
            opening_fills=fills,
            exit_plans=exit_plans,
            exit_attempts=tuple(a for attempts, _fills in exit_histories for a in attempts),
            exit_fills=tuple(f for _attempts, fills in exit_histories for f in fills),
        )
        _feed(
            restored,
            _snapshot(START_MS + 1_100),
            _context(START_MS + 1_200, "94"),
            _book_record(START_MS + 1_300, bid="93.9", ask="94.1"),
            _book_record(START_MS + 1_500, bid="93.9", ask="94.1"),
        )
        assert successor.account.positions == ()
        assert len(restored.finalize(START_MS + 1_500)) == 1
        assert successor.store.table_counts()["paper_fills"] == counts["paper_fills"] + 1
        assert successor.session_opening_attempts == 0
        assert successor.session_opening_fills == 0
        assert successor.pending_reduce_only_count == 0
    finally:
        successor_facts.close()
        successor.close()
