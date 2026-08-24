from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import EquityFactKind
from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.journal import JournalObservation
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation
from cocomelon.evidence.lifecycle import BaselineReplayPipeline
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.replay.engine import ReplayInvariantError

MARKET = MarketId("", "BTC")
RUN_ID = "phase9-lifecycle-run"
EVALUATED_AT_MS = 3_598_000
BOUNDARY_MS = 3_600_000
OPEN_BOOK_MS = EVALUATED_AT_MS + 250
ORACLE_MS = BOUNDARY_MS - 500
FUNDING_RECEIVE_MS = BOUNDARY_MS + 100
STOP_MARK_MS = BOUNDARY_MS + 500
CLOSE_BOOK_MS = STOP_MARK_MS + 300


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


def _book(receive_ms: int, *, bid: str, ask: str, size: str = "1000") -> ReplayRecord:
    return _record(
        kind="l2_book",
        available_at_ms=receive_ms,
        exchange_time_ms=receive_ms,
        payload={
            "bids": [{"px": bid, "sz": size, "n": 1}],
            "asks": [{"px": ask, "sz": size, "n": 1}],
        },
    )


def _asset_ctx(receive_ms: int, *, mark: str, oracle: str | None = None) -> ReplayRecord:
    return _record(
        kind="active_asset_ctx",
        available_at_ms=receive_ms,
        payload={
            "mark_px": mark,
            "mid_px": mark,
            "oracle_px": oracle or mark,
            "funding": "0",
            "open_interest": "1000000",
        },
    )


def _funding() -> ReplayRecord:
    return _record(
        kind="funding_rate",
        available_at_ms=FUNDING_RECEIVE_MS,
        exchange_time_ms=BOUNDARY_MS,
        payload={
            "time_ms": BOUNDARY_MS,
            "funding_rate": "0.0001",
            "premium": "0",
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
        provenance=("phase9-lifecycle-fixture",),
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


class _ScriptedDecisionEngine:
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


def _config(*, funding_grace_ms: int = 300_000) -> BaselineReplayConfig:
    return BaselineReplayConfig(
        execution=PaperExecutionConfig(funding_reconciliation_grace_ms=funding_grace_ms)
    )


def _pipeline(
    tmp_path: Path,
    *,
    config: BaselineReplayConfig | None = None,
    suffix: str = "first",
) -> tuple[BaselineReplayPipeline, PaperExecutionAdapter, EvaluationFactStore]:
    replay_config = config or _config()
    execution = PaperExecutionAdapter(
        tmp_path / f"execution-{suffix}.sqlite3",
        replay_config.execution,
        starting_cash=replay_config.starting_cash,
        startup_timestamp_ms=EVALUATED_AT_MS - 2_000,
    )
    facts = EvaluationFactStore(tmp_path / f"facts-{suffix}.sqlite3")
    pipeline = BaselineReplayPipeline(
        replay_config,
        execution,
        facts,
        selected_markets=(MARKET,),
        replay_run_id=RUN_ID,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        decision_engine=_ScriptedDecisionEngine(replay_config),
    )
    return pipeline, execution, facts


def _run_records(
    pipeline: BaselineReplayPipeline,
    records: tuple[ReplayRecord, ...],
) -> tuple[JournalObservation, ...]:
    observations: list[JournalObservation] = []
    for record in records:
        observations.extend(pipeline.on_record(record, record.available_at_ms))
    return tuple(observations)


def test_long_lifecycle_applies_funding_closes_and_records_evaluation_facts(
    tmp_path: Path,
) -> None:
    pipeline, execution, facts = _pipeline(tmp_path)
    observations = _run_records(
        pipeline,
        (
            _snapshot_record(),
            _trigger_record(),
            _book(OPEN_BOOK_MS, bid="99.9", ask="100.1"),
            _asset_ctx(ORACLE_MS, mark="100", oracle="100"),
            _funding(),
            _asset_ctx(STOP_MARK_MS, mark="94", oracle="94"),
            _book(CLOSE_BOOK_MS, bid="93.9", ask="94.0"),
        ),
    )
    trades = pipeline.finalize(CLOSE_BOOK_MS)

    assert len(trades) == 1
    trade = trades[0]
    assert trade.market == MARKET
    assert trade.direction is Direction.LONG
    assert trade.funding_event_ids
    assert trade.funding_cash_pnl < 0
    assert trade.entry_fees > 0
    assert trade.exit_fees > 0
    assert trade.net_pnl == trade.equity_after - trade.equity_before
    assert trade.mae is not None
    assert execution.account.positions == ()

    kinds = tuple(observation.kind.value for observation in observations)
    assert "funding_event" in kinds
    assert "position_action" in kinds
    assert "account_state" in kinds
    assert not pipeline.funding_inconsistent

    decision_facts = tuple(facts.iter_decision_facts())
    assert len(decision_facts) == 1
    assert decision_facts[0].replay_run_id == RUN_ID
    equity_kinds = {fact.kind for fact in facts.iter_equity_facts()}
    assert EquityFactKind.FILL in equity_kinds
    assert EquityFactKind.MARK in equity_kinds
    assert EquityFactKind.FUNDING in equity_kinds

    execution.close()
    facts.close()


def test_unresolved_funding_boundary_emits_gap_and_marks_pipeline_inconsistent(
    tmp_path: Path,
) -> None:
    config = _config(funding_grace_ms=100)
    pipeline, execution, facts = _pipeline(tmp_path, config=config, suffix="gap")
    observations = _run_records(
        pipeline,
        (
            _snapshot_record(),
            _trigger_record(),
            _book(OPEN_BOOK_MS, bid="99.9", ask="100.1"),
            _asset_ctx(ORACLE_MS, mark="100", oracle="100"),
            _asset_ctx(BOUNDARY_MS + 101, mark="100", oracle="100"),
        ),
    )

    gaps = [
        observation
        for observation in observations
        if observation.kind.value == "funding_gap"
    ]
    assert len(gaps) == 1
    assert gaps[0].reason_codes == ("FUNDING_RECORD_MISSING",)
    assert pipeline.funding_inconsistent is True
    assert execution.account.cumulative_funding == Decimal("0")

    execution.close()
    facts.close()


def test_identical_replay_restart_produces_identical_fact_ids(tmp_path: Path) -> None:
    records = (
        _snapshot_record(),
        _trigger_record(),
        _book(OPEN_BOOK_MS, bid="99.9", ask="100.1"),
        _asset_ctx(ORACLE_MS, mark="100", oracle="100"),
        _funding(),
        _asset_ctx(STOP_MARK_MS, mark="94", oracle="94"),
        _book(CLOSE_BOOK_MS, bid="93.9", ask="94.0"),
    )

    first, first_execution, first_facts = _pipeline(tmp_path, suffix="restart-a")
    _run_records(first, records)
    first.finalize(CLOSE_BOOK_MS)
    first_ids = (
        tuple(fact.fact_id for fact in first_facts.iter_decision_facts()),
        tuple(fact.fact_id for fact in first_facts.iter_equity_facts()),
    )
    first_execution.close()
    first_facts.close()

    second, second_execution, second_facts = _pipeline(tmp_path, suffix="restart-b")
    _run_records(second, records)
    second.finalize(CLOSE_BOOK_MS)
    second_ids = (
        tuple(fact.fact_id for fact in second_facts.iter_decision_facts()),
        tuple(fact.fact_id for fact in second_facts.iter_equity_facts()),
    )

    assert first_ids == second_ids
    second_execution.close()
    second_facts.close()


def test_lifecycle_raises_replay_invariant_on_journal_inconsistency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, execution, facts = _pipeline(tmp_path, suffix="invariant")
    _run_records(
        pipeline,
        (
            _snapshot_record(),
            _trigger_record(),
            _book(OPEN_BOOK_MS, bid="99.9", ask="100.1"),
            _asset_ctx(STOP_MARK_MS, mark="94", oracle="94"),
        ),
    )

    monkeypatch.setattr(
        "cocomelon.evidence.lifecycle.assemble_trade_journal_entry",
        lambda _lifecycle: object(),
    )
    with pytest.raises(ReplayInvariantError, match="journal lifecycle"):
        _run_records(
            pipeline,
            (_book(CLOSE_BOOK_MS, bid="93.9", ask="94.0"),),
        )

    execution.close()
    facts.close()
