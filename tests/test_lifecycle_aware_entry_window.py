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
from cocomelon.evidence.baseline import RecordedStateBook, replay_record_stream_event
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation
from cocomelon.evidence.lifecycle import BaselineReplayPipeline
from cocomelon.execution.paper import PaperExecutionAdapter

MARKET = MarketId("", "BTC")
RUN_ID = "lifecycle-aware-entry-window"
EVALUATED_AT_MS = 1_000_000
CUTOFF_MS = 1_030_000


def _book(receive_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=receive_ms,
        source="hyperliquid-mainnet-public-fixture",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=receive_ms,
        event_key=f"l2:{receive_ms}",
        payload_json=json.dumps(
            {
                "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
                "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
            },
            sort_keys=True,
        ),
        event_kind="l2_book",
    )


def _feature(timestamp_ms: int) -> FeatureSnapshot:
    return FeatureSnapshot(
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
        provenance=("lifecycle-aware-entry-window",),
    )


def _epoch(timestamp_ms: int) -> DecisionEpoch:
    feature = _feature(timestamp_ms)
    decision = StrategyDecision(
        market=MARKET,
        direction=Direction.LONG,
        score=Decimal("80"),
        timestamp_ms=timestamp_ms,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy="trend",
        invalidation_price=Decimal("95"),
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
    def __init__(self, replay_config: BaselineReplayConfig, timestamp_ms: int) -> None:
        self._state = RecordedStateBook(
            microstructure_window_ms=replay_config.microstructure_window_ms
        )
        self._timestamp_ms = timestamp_ms
        self._emitted = False

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def observe(self, _record: ReplayRecord, _now_ms: int) -> tuple[DecisionEpoch, ...]:
        if self._emitted:
            return ()
        self._emitted = True
        return (_epoch(self._timestamp_ms),)

    def flush(self, _end_ms: int) -> tuple[DecisionEpoch, ...]:
        return ()


class _OpeningProbe:
    def __init__(self) -> None:
        self.staged_at_ms: list[int] = []
        self.books_at_ms: list[int] = []

    def stage_epoch(self, epoch: DecisionEpoch) -> None:
        self.staged_at_ms.append(epoch.evaluated_at_ms)

    def on_book(self, _book: object, now_ms: int) -> None:
        self.books_at_ms.append(now_ms)

    def take_traces(self) -> tuple[object, ...]:
        return ()


def _pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision_timestamp_ms: int,
) -> tuple[BaselineReplayPipeline, PaperExecutionAdapter, EvaluationFactStore, _OpeningProbe]:
    replay_config = BaselineReplayConfig(execution=PaperExecutionConfig())
    execution = PaperExecutionAdapter(
        tmp_path / f"execution-{decision_timestamp_ms}.sqlite3",
        replay_config.execution,
        starting_cash=replay_config.starting_cash,
        startup_timestamp_ms=EVALUATED_AT_MS - 60_000,
    )
    facts = EvaluationFactStore(tmp_path / f"facts-{decision_timestamp_ms}.sqlite3")
    opening = _OpeningProbe()
    monkeypatch.setattr(
        "cocomelon.evidence.lifecycle.BaselineOpeningEngine",
        lambda *_args, **_kwargs: opening,
    )
    pipeline = BaselineReplayPipeline(
        replay_config,
        execution,
        facts,
        selected_markets=(MARKET,),
        replay_run_id=RUN_ID,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        decision_engine=_ScriptedDecisionEngine(replay_config, decision_timestamp_ms),
        new_exposure_cutoff_ms=CUTOFF_MS,
    )
    return pipeline, execution, facts, opening


def test_new_exposure_is_allowed_strictly_before_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp_ms = CUTOFF_MS - 1
    pipeline, execution, facts, opening = _pipeline(
        tmp_path,
        monkeypatch,
        decision_timestamp_ms=timestamp_ms,
    )
    try:
        pipeline.on_record(_book(timestamp_ms), timestamp_ms)
        assert opening.staged_at_ms == [timestamp_ms]
        assert opening.books_at_ms == [timestamp_ms]
    finally:
        facts.close()
        execution.close()


def test_new_exposure_is_blocked_at_cutoff_but_management_still_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline, execution, facts, opening = _pipeline(
        tmp_path,
        monkeypatch,
        decision_timestamp_ms=CUTOFF_MS,
    )
    managed_at_ms: list[int] = []

    def manage(_book: object, now_ms: int) -> tuple[object, ...]:
        managed_at_ms.append(now_ms)
        return ()

    monkeypatch.setattr(pipeline, "_manage_book", manage)
    record = _book(CUTOFF_MS)
    event = replay_record_stream_event(record)
    try:
        pipeline.on_record(record, CUTOFF_MS)
        assert managed_at_ms == [CUTOFF_MS]
        assert opening.staged_at_ms == []
        assert opening.books_at_ms == []
        assert len(tuple(facts.iter_decision_facts())) == 1
        assert event.market == MARKET
    finally:
        facts.close()
        execution.close()
