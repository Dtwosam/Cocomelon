from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation
from cocomelon.evidence.lifecycle import BaselineReplayPipeline
from cocomelon.execution.accounting import DAY_MS
from cocomelon.execution.paper import PaperExecutionAdapter

MARKET = MarketId("", "BTC")
RUN_ID = "phase9-open-activity-run"
EVALUATED_AT_MS = 3_598_000
OPEN_BOOK_MS = EVALUATED_AT_MS + 250


def _record(
    *,
    kind: str,
    available_at_ms: int,
    payload: dict[str, object],
    exchange_time_ms: int | None = None,
    event_key: str | None = None,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=available_at_ms,
        source="hyperliquid-mainnet-public-fixture",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=exchange_time_ms,
        event_key=event_key or f"{kind}:{MARKET.canonical}:{available_at_ms}",
        payload_json=json.dumps(payload, sort_keys=True),
        event_kind=kind,
    )


def _snapshot_record() -> ReplayRecord:
    return _record(
        kind="market_snapshot",
        available_at_ms=EVALUATED_AT_MS - 1_000,
        payload={
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


def _trigger_record() -> ReplayRecord:
    return _record(
        kind="candle",
        available_at_ms=EVALUATED_AT_MS,
        exchange_time_ms=EVALUATED_AT_MS - 1,
        event_key="epoch-trigger",
        payload={
            "interval": "15m",
            "start_ms": EVALUATED_AT_MS - 900_000,
            "end_ms": EVALUATED_AT_MS - 1,
            "open_px": "99",
            "high_px": "101",
            "low_px": "98",
            "close_px": "100",
            "volume": "1000",
            "trade_count": 100,
        },
    )


def _book() -> ReplayRecord:
    return _record(
        kind="l2_book",
        available_at_ms=OPEN_BOOK_MS,
        exchange_time_ms=OPEN_BOOK_MS,
        payload={
            "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
        },
    )


def _feature() -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MARKET,
        as_of_ms=EVALUATED_AT_MS,
        source_received_at_ms=EVALUATED_AT_MS - 1_000,
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
        provenance=("phase9-open-activity-fixture",),
    )


def _epoch() -> DecisionEpoch:
    feature = _feature()
    decision = StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=EVALUATED_AT_MS,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("95"),
        signal_ids=("fixture-signal",),
        reason_codes=("fixture-directional",),
    )
    return DecisionEpoch(
        boundary_ms=EVALUATED_AT_MS - 30_000,
        evaluated_at_ms=EVALUATED_AT_MS,
        markets=(
            EpochMarketEvaluation(
                feature=feature,
                eligibility=EligibilityDecision(
                    market=MARKET,
                    rankable=True,
                    deep_ready=True,
                    reasons=(),
                ),
                decision=decision,
            ),
        ),
    )


class ScriptedDecisionEngine:
    def __init__(
        self,
        replay_config: BaselineReplayConfig,
        *,
        epoch: DecisionEpoch | None = None,
    ) -> None:
        self._state = RecordedStateBook(
            microstructure_window_ms=replay_config.microstructure_window_ms
        )
        self._epoch = _epoch() if epoch is None else epoch
        self._emitted = False

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def observe(self, record: ReplayRecord, now_ms: int) -> tuple[DecisionEpoch, ...]:
        self._state.apply(record, now_ms)
        if record.event_key == "epoch-trigger" and not self._emitted:
            self._emitted = True
            return (self._epoch,)
        return ()

    def flush(self, _end_ms: int) -> tuple[DecisionEpoch, ...]:
        return ()


def test_baseline_pipeline_restore_avoids_full_equity_fact_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    execution = PaperExecutionAdapter(
        tmp_path / "execution-fast-restore.sqlite3",
        config.execution,
        starting_cash=config.starting_cash,
        startup_timestamp_ms=EVALUATED_AT_MS - 2_000,
    )
    facts = EvaluationFactStore(tmp_path / "facts-fast-restore.sqlite3")

    def fail_full_scan(
        _replay_run_id: str | None = None,
    ) -> object:
        raise AssertionError(
            "pipeline restore must not scan historical equity facts"
        )

    monkeypatch.setattr(facts, "iter_equity_facts", fail_full_scan)
    monkeypatch.setattr(
        facts,
        "iter_equity_account_state_ids",
        fail_full_scan,
    )

    try:
        BaselineReplayPipeline(
            config,
            execution,
            facts,
            selected_markets=(MARKET,),
            replay_run_id=RUN_ID,
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            decision_engine=ScriptedDecisionEngine(config),
        )
    finally:
        execution.close()
        facts.close()


def test_baseline_pipeline_reports_fill_and_open_position_before_trade_closes(tmp_path) -> None:
    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    execution = PaperExecutionAdapter(
        tmp_path / "execution.sqlite3",
        config.execution,
        starting_cash=config.starting_cash,
        startup_timestamp_ms=EVALUATED_AT_MS - 2_000,
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    pipeline = BaselineReplayPipeline(
        config,
        execution,
        facts,
        selected_markets=(MARKET,),
        replay_run_id=RUN_ID,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        decision_engine=ScriptedDecisionEngine(config),
    )
    try:
        for record in (_snapshot_record(), _trigger_record(), _book()):
            pipeline.on_record(record, record.available_at_ms)

        assert len(execution.account.positions) == 1
        assert pipeline.finalize(OPEN_BOOK_MS) == ()
        replay_pipeline = pipeline.replay_pipeline()
        assert replay_pipeline.activity is not None
        activity = replay_pipeline.activity()
        assert activity.fills == 1
        assert activity.opened_positions == 1
        assert activity.closed_positions == 0
        decision_activity = pipeline.session_decision_activity
        assert decision_activity.decision_epochs == 1
        assert decision_activity.long_decisions == 1
        assert decision_activity.short_decisions == 0
        assert decision_activity.no_trade_decisions == 0
        assert decision_activity.decision_reason_counts == (
            ("fixture-directional", 1),
        )
        assert decision_activity.eligibility_evaluations == 1
        assert decision_activity.eligibility_rankable == 1
        assert decision_activity.eligibility_deep_ready == 1
        assert decision_activity.eligibility_reason_counts == ()
        assert decision_activity.latest_epoch_market_count == 1
        assert decision_activity.latest_epoch_rankable_count == 1
        assert decision_activity.latest_epoch_deep_ready_count == 1
        assert (
            decision_activity.latest_epoch_eligibility_reason_counts
            == ()
        )
        assert decision_activity.latest_epoch_stale_book_age_ms == ()
        assert decision_activity.risk_evaluations == 1
        assert decision_activity.risk_approvals == 1
        assert decision_activity.risk_rejections == 0
        assert decision_activity.opening_execution_attempts == 1
        assert decision_activity.opening_fills == 1
        runtime_components = pipeline.runtime_max_ms_by_component
        assert {
            "decision_engine_observe",
            "epoch_decision_fact_batch",
            "epoch_opening_stage",
            "epoch_process_total",
            "funding_reconcile",
        } <= set(runtime_components)
        assert all(
            value >= 0
            for value in runtime_components.values()
        )
    finally:
        execution.close()
        facts.close()


def test_pipeline_reports_underlying_eligibility_failure_reasons(
    tmp_path: Path,
) -> None:
    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    feature = _feature()
    epoch = DecisionEpoch(
        boundary_ms=EVALUATED_AT_MS - 30_000,
        evaluated_at_ms=EVALUATED_AT_MS,
        markets=(
            EpochMarketEvaluation(
                feature=feature,
                eligibility=EligibilityDecision(
                    market=MARKET,
                    rankable=True,
                    deep_ready=False,
                    reasons=(
                        "missing_deep_data",
                        "stale_book",
                    ),
                ),
                decision=StrategyDecision(
                    market=MARKET,
                    direction=Direction.NO_TRADE,
                    score=Decimal("0"),
                    timestamp_ms=EVALUATED_AT_MS,
                    feature_snapshot_id=feature.snapshot_id,
                    lead_strategy=None,
                    invalidation_price=None,
                    signal_ids=(),
                    reason_codes=("not_deep_ready",),
                ),
            ),
        ),
    )
    execution = PaperExecutionAdapter(
        tmp_path / "execution-eligibility.sqlite3",
        config.execution,
        starting_cash=config.starting_cash,
        startup_timestamp_ms=EVALUATED_AT_MS - 2_000,
    )
    facts = EvaluationFactStore(
        tmp_path / "facts-eligibility.sqlite3"
    )
    pipeline = BaselineReplayPipeline(
        config,
        execution,
        facts,
        selected_markets=(MARKET,),
        replay_run_id=RUN_ID + "-eligibility",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        decision_engine=ScriptedDecisionEngine(
            config,
            epoch=epoch,
        ),
    )
    try:
        pipeline.on_record(
            _snapshot_record(),
            _snapshot_record().available_at_ms,
        )
        trigger = _trigger_record()
        pipeline.on_record(trigger, trigger.available_at_ms)

        activity = pipeline.session_decision_activity
        assert activity.decision_epochs == 1
        assert activity.no_trade_decisions == 1
        assert activity.decision_reason_counts == (
            ("not_deep_ready", 1),
        )
        assert activity.eligibility_evaluations == 1
        assert activity.eligibility_rankable == 1
        assert activity.eligibility_deep_ready == 0
        assert activity.eligibility_reason_counts == (
            ("missing_deep_data", 1),
            ("stale_book", 1),
        )
        assert activity.latest_epoch_market_count == 1
        assert activity.latest_epoch_rankable_count == 1
        assert activity.latest_epoch_deep_ready_count == 0
        assert (
            activity.latest_epoch_eligibility_reason_counts
            == (
                ("missing_deep_data", 1),
                ("stale_book", 1),
            )
        )
        assert activity.latest_epoch_stale_book_age_ms == (
            (MARKET.canonical, feature.book_age_ms),
        )
    finally:
        execution.close()
        facts.close()


class _RolloverAssertingDecisionEngine:
    def __init__(
        self,
        replay_config: BaselineReplayConfig,
        execution: PaperExecutionAdapter,
    ) -> None:
        self._state = RecordedStateBook(
            microstructure_window_ms=replay_config.microstructure_window_ms
        )
        self._execution = execution
        self.observed = False

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def observe(
        self,
        record: ReplayRecord,
        now_ms: int,
    ) -> tuple[DecisionEpoch, ...]:
        assert self._execution.account.day_start_ms == DAY_MS
        assert self._execution.account.daily_realized_pnl == Decimal("0")
        self._state.apply(record, now_ms)
        self.observed = True
        return ()

    def flush(self, _end_ms: int) -> tuple[DecisionEpoch, ...]:
        return ()


def test_pipeline_rolls_account_day_before_decision_engine_observes_record(
    tmp_path,
) -> None:
    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    execution = PaperExecutionAdapter(
        tmp_path / "execution-rollover.sqlite3",
        config.execution,
        starting_cash=config.starting_cash,
        startup_timestamp_ms=DAY_MS - 1_000,
    )
    facts = EvaluationFactStore(tmp_path / "facts-rollover.sqlite3")
    decision_engine = _RolloverAssertingDecisionEngine(
        config,
        execution,
    )
    pipeline = BaselineReplayPipeline(
        config,
        execution,
        facts,
        selected_markets=(MARKET,),
        replay_run_id=RUN_ID + "-rollover",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        decision_engine=decision_engine,
    )
    record = _record(
        kind="market_snapshot",
        available_at_ms=DAY_MS + 1_000,
        payload={
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
    try:
        pipeline.on_record(record, record.available_at_ms)
        assert decision_engine.observed is True
        assert execution.account.day_start_ms == DAY_MS
    finally:
        execution.close()
        facts.close()
