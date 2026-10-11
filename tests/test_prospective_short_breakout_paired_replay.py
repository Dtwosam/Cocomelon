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
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
    SourceSegment,
)
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import DecisionEpoch, EpochMarketEvaluation
from cocomelon.research.prospective_short_breakout_paired_entry import (
    ObservedRankWitness,
)
from cocomelon.research.prospective_short_breakout_paired_replay import (
    ShortRankIndependentPairedPaperReplay,
    ShortRankPairedReplayError,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)

MARKET = MarketId("", "TEST")
FREEZE = ProspectiveShortBreakoutRankState(frozen_at_ms=1_000)
EVALUATED_MS = FREEZE.started_at_ms + 60_000
OPEN_MS = EVALUATED_MS + 250
STOP_MS = EVALUATED_MS + 500
CLOSE_MS = EVALUATED_MS + 800


def _record(
    kind: str, at_ms: int, payload: dict[str, object],
    *, event_key: str | None = None, exchange_ms: int | None = None,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at_ms,
        source="synthetic-test-only-not-a-mainnet-receipt",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=exchange_ms,
        event_key=event_key or f"{kind}:{at_ms}",
        payload_json=json.dumps(payload, sort_keys=True),
        event_kind=kind,
    )


def _records() -> tuple[ReplayRecord, ...]:
    return (
        _record("market_snapshot", EVALUATED_MS - 1_000, {
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
                "prev_day_px": "101",
            },
        }),
        _record(
            "candle", EVALUATED_MS, {
                "interval": "15m",
                "start_ms": EVALUATED_MS - 900_000,
                "end_ms": EVALUATED_MS - 1,
                "open_px": "101",
                "high_px": "101",
                "low_px": "99",
                "close_px": "100",
                "volume": "1000",
                "trade_count": 100,
            },
            event_key="epoch-trigger", exchange_ms=EVALUATED_MS - 1,
        ),
        _record("l2_book", OPEN_MS, {
            "bids": [{"px": "99.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "100.1", "sz": "1000", "n": 1}],
        }, exchange_ms=OPEN_MS),
        _record("active_asset_ctx", STOP_MS, {
            "mark_px": "106",
            "mid_px": "106",
            "oracle_px": "106",
            "funding": "0",
            "open_interest": "1000000",
        }),
        _record("l2_book", CLOSE_MS, {
            "bids": [{"px": "105.9", "sz": "1000", "n": 1}],
            "asks": [{"px": "106.1", "sz": "1000", "n": 1}],
        }, exchange_ms=CLOSE_MS),
    )


def _manifest() -> ReplayManifest:
    start = EVALUATED_MS - 2_000
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=start,
        end_ms=CLOSE_MS + 1,
        segments=(SourceSegment(
            relative_path="tests/not-a-mainnet-source.jsonl",
            partition="unit-test",
            sha256="a" * 64,
            byte_count=1,
            row_count=5,
            schema_version=1,
            first_available_at_ms=start,
            last_available_at_ms=CLOSE_MS,
        ),),
        gap_refs=(),
        code_revision="synthetic-fixture",
        config_digest="b" * 64,
        feature_version="unit",
        strategy_version="unit",
        risk_version="unit",
        execution_config_version="unit",
        fee_schedule_id="unit",
        replay_engine_version="unit",
        dataset_manifest_id=None,
    )


def _feature() -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MARKET,
        as_of_ms=EVALUATED_MS,
        source_received_at_ms=EVALUATED_MS - 1_000,
        schema_version=1,
        day_return=Decimal("-0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("-0.002"),
        return_15m=Decimal("-0.01"),
        return_1h=Decimal("-0.02"),
        return_4h=None,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.1"),
        relative_volume_15m=Decimal("1.2"),
        spread_bps=Decimal("2"),
        bid_depth_25bps=Decimal("100000"),
        ask_depth_25bps=Decimal("100000"),
        book_imbalance=Decimal("-0.1"),
        book_age_ms=10,
        trend_regime=TrendRegime.DOWN,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("synthetic-test-only",),
    )


class _ShortScriptedEngine:
    def __init__(self, config: BaselineReplayConfig) -> None:
        self._state = RecordedStateBook(
            microstructure_window_ms=config.microstructure_window_ms
        )
        self._emitted = False

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def seed(self, record: ReplayRecord, now_ms: int) -> None:
        self._state.apply(record, now_ms)

    def observe(
        self, record: ReplayRecord, now_ms: int,
    ) -> tuple[DecisionEpoch, ...]:
        self._state.apply(record, now_ms)
        if record.event_key != "epoch-trigger" or self._emitted:
            return ()
        self._emitted = True
        feature = _feature()
        return (DecisionEpoch(
            boundary_ms=EVALUATED_MS - 30_000,
            evaluated_at_ms=EVALUATED_MS,
            markets=(EpochMarketEvaluation(
                feature=feature,
                eligibility=EligibilityDecision(
                    market=MARKET, rankable=True, deep_ready=True, reasons=(),
                ),
                decision=StrategyDecision(
                    market=MARKET,
                    direction=Direction.SHORT,
                    score=Decimal("80"),
                    timestamp_ms=EVALUATED_MS,
                    feature_snapshot_id=feature.snapshot_id,
                    lead_strategy="breakout",
                    invalidation_price=Decimal("105"),
                    signal_ids=("fixture-short-signal",),
                    reason_codes=("fixture-only",),
                ),
            ),),
        ),)

    def flush(self, end_ms: int) -> tuple[DecisionEpoch, ...]:
        return ()


def _paired(
    path: Path, rank: ObservedRankWitness | None,
) -> ShortRankIndependentPairedPaperReplay:
    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    return ShortRankIndependentPairedPaperReplay(
        freeze=FREEZE,
        config=config,
        manifest=_manifest(),
        selected_markets=(MARKET,),
        rank_witness_provider=lambda market, at_ms: rank,
        state_root=path,
        decision_engine_factory=lambda: _ShortScriptedEngine(config),
    )


def test_two_real_simulated_paper_accounts_do_not_invent_skipped_fills(
    tmp_path: Path,
) -> None:
    replay = _paired(
        tmp_path / "trial",
        ObservedRankWitness(ordinal=7, observed_at_ms=EVALUATED_MS - 1_000),
    )
    try:
        for record in _records():
            replay.on_record(record)
        result = replay.summary()
    finally:
        replay.close()
    baseline = result["baseline"]
    candidate = result["candidate"]
    assert isinstance(baseline, dict)
    assert isinstance(candidate, dict)
    assert baseline["opening_fills"] == 1
    assert candidate["opening_fills"] == 0
    assert baseline["closed_trades"] == 1
    assert candidate["closed_trades"] == 0
    assert Decimal(str(baseline["marked_account_pnl"])) < 0
    assert candidate["marked_account_pnl"] == "0"
    assert Decimal(str(result["candidate_minus_baseline_marked_account_pnl"])) > 0
    assert Decimal(str(baseline["fill_fees"])) > 0
    assert (tmp_path / "trial" / "baseline-execution.sqlite3").exists()
    assert (tmp_path / "trial" / "candidate-execution.sqlite3").exists()
    assert result["independent_simulated_paper_accounts"] is True
    assert result["source_manifest_independently_authenticated"] is False
    assert result["ready_for_review"] is False
    assert result["full_account_trial"] is False
    assert result["execution_authority"] is False


def test_missing_rank_retains_loser_in_both_real_paper_simulations(
    tmp_path: Path,
) -> None:
    replay = _paired(tmp_path / "missing", None)
    try:
        for record in _records():
            replay.on_record(record)
        result = replay.summary()
    finally:
        replay.close()
    baseline = result["baseline"]
    candidate = result["candidate"]
    assert isinstance(baseline, dict) and isinstance(candidate, dict)
    assert baseline["closed_trades"] == candidate["closed_trades"] == 1
    assert baseline["marked_account_pnl"] == candidate["marked_account_pnl"]
    admission = result["candidate_admission"]
    assert isinstance(admission, dict)
    assert admission["unverifiable_by_reason"] == {"missing_rank_witness": 1}


def test_duplicate_source_is_fatal_and_never_publishes_report(
    tmp_path: Path,
) -> None:
    replay = _paired(tmp_path / "bad-order", None)
    try:
        replay.on_record(_records()[0])
        with pytest.raises(ShortRankPairedReplayError, match="duplicate"):
            replay.on_record(_records()[0])
        with pytest.raises(ShortRankPairedReplayError, match="valid"):
            replay.summary()
    finally:
        replay.close()


def test_unchanged_second_run_cannot_reuse_or_reset_an_account(
    tmp_path: Path,
) -> None:
    root = tmp_path / "existing"
    first = _paired(root, None)
    first.close()
    with pytest.raises(ShortRankPairedReplayError, match="new and empty"):
        _paired(root, None)


def test_out_of_order_market_observation_fails_closed(tmp_path: Path) -> None:
    replay = _paired(tmp_path / "out-of-order", None)
    try:
        replay.on_record(_records()[1])
        with pytest.raises(ShortRankPairedReplayError, match="nonmonotonic"):
            replay.on_record(_records()[0])
        with pytest.raises(ShortRankPairedReplayError, match="valid"):
            replay.summary()
    finally:
        replay.close()



def test_baseline_and_candidate_share_single_immutable_rank_snapshot(
    tmp_path: Path,
) -> None:
    calls = 0

    def alternating_provider(
        market: MarketId, timestamp_ms: int,
    ) -> ObservedRankWitness | None:
        nonlocal calls
        calls += 1
        # A second call would make the candidate keep a losing entry,
        # retrospectively changing the frozen comparison.
        if calls == 1:
            return ObservedRankWitness(ordinal=8, observed_at_ms=EVALUATED_MS - 1_000)
        return None

    config = BaselineReplayConfig(execution=PaperExecutionConfig())
    replay = ShortRankIndependentPairedPaperReplay(
        freeze=FREEZE,
        config=config,
        manifest=_manifest(),
        selected_markets=(MARKET,),
        rank_witness_provider=alternating_provider,
        state_root=tmp_path / "shared-source",
        decision_engine_factory=lambda: _ShortScriptedEngine(config),
    )
    try:
        for record in _records():
            replay.on_record(record)
        result = replay.summary()
    finally:
        replay.close()
    assert calls == 1
    assert result["rank_witness_values_shared_between_lanes"] is True
    admission = result["candidate_admission"]
    assert isinstance(admission, dict)
    assert admission["rank4plus_blocked"] == 1
