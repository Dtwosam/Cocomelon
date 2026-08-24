from __future__ import annotations

import json
from decimal import Decimal

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
    def __init__(self, replay_config: BaselineReplayConfig) -> None:
        self._state = RecordedStateBook(
            microstructure_window_ms=replay_config.microstructure_window_ms
        )
        self._emitted = False

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def observe(self, record: ReplayRecord, now_ms: int) -> tuple[DecisionEpoch, ...]:
        self._state.apply(record, now_ms)
        if record.event_key == "epoch-trigger" and not self._emitted:
            self._emitted = True
            return (_epoch(),)
        return ()

    def flush(self, _end_ms: int) -> tuple[DecisionEpoch, ...]:
        return ()


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
    finally:
        execution.close()
        facts.close()
