"""New frozen LONG-only challenger cannot reuse losing prior paired accounts."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest, ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import EpochMarketEvaluation
from cocomelon.research import fresh_long_trend_forward_pair as study
from cocomelon.research.loss_context_portfolio_shadow_entry import (
    CONTEXT_BLOCK_REASON,
    PRE_BOUNDARY_REASON,
    LossContextPortfolioShadowEntryFilter,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    both_side_trend_matched_shadow_v2_freeze,
)

MARKET = MarketId("", "TEST")


def _evaluation(
    *, direction: Direction, lead: str,
) -> EpochMarketEvaluation:
    ts = study.FORWARD_NOT_BEFORE_MS + 60_000
    feature = FeatureSnapshot(
        market=MARKET,
        as_of_ms=ts,
        source_received_at_ms=ts - 1_000,
        schema_version=1,
        day_return=Decimal("-0.01"),
        funding=Decimal("0"),
        open_interest=Decimal("1000000"),
        day_notional_volume=Decimal("500000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("0"),
        return_5m=Decimal("-0.001"),
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
        provenance=("original-received-research-fixture",),
    )
    decision = StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("80"),
        timestamp_ms=ts,
        feature_snapshot_id=feature.snapshot_id,
        lead_strategy=lead,
        invalidation_price=Decimal("95"),
        signal_ids=("fixed-study-test",),
        reason_codes=("fixed-study-test",),
    )
    return EpochMarketEvaluation(
        feature=feature,
        decision=decision,
        eligibility=EligibilityDecision(
            market=MARKET, rankable=True, deep_ready=True, reasons=(),
        ),
    )


def _manifest(*, start_offset: int = -1) -> ReplayManifest:
    return cast(ReplayManifest, SimpleNamespace(
        start_ms=study.FORWARD_NOT_BEFORE_MS + start_offset,
        end_ms=study.FORWARD_NOT_BEFORE_MS + 1_000,
        manifest_id="0123456789abcdef01234567",
    ))


class _Source:
    loaded: tuple[ReplayRecord, ...] = ()
    last_forward: int | None = None
    deny = False

    def __init__(
        self, *, root: Path, manifest: ReplayManifest, expected_manifest_id: str,
    ) -> None:
        if expected_manifest_id != manifest.manifest_id:
            raise ValueError("manifest identity mismatch")
        self.root = root

    def verified_records(
        self, *, forward_not_before_ms: int,
    ) -> tuple[ReplayRecord, ...]:
        _Source.last_forward = forward_not_before_ms
        if _Source.deny:
            raise ValueError("source manifest incomplete or tampered")
        return _Source.loaded

    def verification_receipt(
        self, records: tuple[ReplayRecord, ...],
    ) -> dict[str, object]:
        assert records == _Source.loaded
        return {"pin_origin_independently_authenticated": False}


def _original_snapshot(at_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at_ms,
        source="test-captured-mainnet-paper-record",
        schema_version=1,
        market=MARKET.canonical,
        exchange_time_ms=at_ms - 1,
        event_key=f"original-{at_ms}",
        event_kind="market_snapshot",
        payload_json=json.dumps({
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
        }, sort_keys=True),
    )


def test_new_long_only_candidate_distinct_and_embargo_immutable() -> None:
    freeze = study.fresh_long_trend_freeze()
    previous = both_side_trend_matched_shadow_v2_freeze()
    assert freeze.candidate_id != previous.candidate_id
    assert freeze.loss_context_candidate_id != previous.loss_context_candidate_id
    assert freeze.source_composition_digest != previous.source_composition_digest
    assert freeze.dimensions == ("lead_strategy", "direction")
    assert freeze.values == ("trend", "long")
    assert freeze.source_paper_run_id == 38737278661
    assert freeze.source_paper_run_attempt == 1
    assert freeze.source_paper_head_sha == (
        "bcfd0eab058cda4ba9270dcd449a8cdf67b9199c"
    )
    assert freeze.source_max_timestamp_ms == 1_792_074_581_000
    assert freeze.source_max_timestamp_ms < freeze.frozen_at_ms
    assert freeze.frozen_at_ms == 1_792_108_800_000
    assert freeze.prospective_not_before_ms == study.FORWARD_NOT_BEFORE_MS
    assert freeze.prospective_not_before_ms - freeze.frozen_at_ms == 6 * 3_600_000
    assert study.PRECOMMITMENT["minimum_forward_ms"] == 72 * 3_600_000
    assert study.PRECOMMITMENT["previous_v1_v2_accounts_and_signed_records_admissible"] is False
    assert freeze.paper_only and freeze.research_only
    assert not freeze.promotion_authority and not freeze.execution_authority


def test_only_original_long_trend_entries_are_blocked() -> None:
    freeze = study.fresh_long_trend_freeze()
    baseline = LossContextPortfolioShadowEntryFilter(
        freeze, block_matching_context=False,
    )
    candidate = LossContextPortfolioShadowEntryFilter(
        freeze, block_matching_context=True,
    )
    open_at = study.FORWARD_NOT_BEFORE_MS + 60_001
    long_trend = _evaluation(direction=Direction.LONG, lead="trend")
    assert candidate.block_reason(
        long_trend, attempt_timestamp_ms=open_at - 100_000,
    ) == PRE_BOUNDARY_REASON
    assert baseline.block_reason(
        long_trend, attempt_timestamp_ms=open_at,
    ) is None
    assert candidate.block_reason(
        long_trend, attempt_timestamp_ms=open_at,
    ) == CONTEXT_BLOCK_REASON
    for direction, strategy in (
        (Direction.SHORT, "trend"),
        (Direction.LONG, "breakout"),
        (Direction.SHORT, "breakout"),
        (Direction.LONG, "mean_reversion"),
    ):
        assert candidate.block_reason(
            _evaluation(direction=direction, lead=strategy),
            attempt_timestamp_ms=open_at,
        ) is None
    assert candidate.matching_context_blocked == 1
    assert candidate.matching_context_blocked_by_market == {"TEST": 1}
    assert candidate.admitted_after_boundary == 4


def test_fresh_source_replay_constructs_new_independent_account_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "new-long-study"
    _Source.deny = False
    _Source.loaded = (_original_snapshot(study.FORWARD_NOT_BEFORE_MS + 10),)
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    response = study.run_digest_pinned_long_trend_matched_paper(
        source_root=tmp_path / "untrusted-replay-placeholder",
        manifest=_manifest(),
        expected_manifest_id="0123456789abcdef01234567",
        config=BaselineReplayConfig(execution=PaperExecutionConfig()),
        selected_markets=(MARKET,),
        account_root=root,
    )
    assert _Source.last_forward == study.FORWARD_NOT_BEFORE_MS
    assert response["source_records_replayed"] == 1
    assert response["minimum_forward_elapsed"] is False
    assert response["after_cost_72h_profitability_verified"] is False
    assert response["full_account_study_admissible"] is False
    assert response["promotion_authority"] is False
    assert response["execution_authority"] is False
    summary = response["paired_account_original_runtime_summary"]
    assert isinstance(summary, dict)
    baseline = summary["baseline"]
    candidate = summary["candidate"]
    assert isinstance(baseline, dict) and isinstance(candidate, dict)
    assert baseline["equity"] == candidate["equity"]
    assert baseline["closed_trade_count"] == candidate["closed_trade_count"]
    assert summary["candidate_difference_is_opening_admission_only"] is True
    assert (root / "baseline-execution.sqlite3").is_file()
    assert (root / "candidate-execution.sqlite3").is_file()
    with pytest.raises(study.LongTrendForwardTrialError, match="empty root"):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path,
            manifest=_manifest(),
            expected_manifest_id="0123456789abcdef01234567",
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            account_root=root,
        )


@pytest.mark.parametrize("rootname", [
    "both-side-trend-paired-shadow-v1",
    "both-side-trend-paired-shadow-v2",
    "loss-context-paired-v5",
])
def test_prior_trial_roots_are_forbidden_before_account_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rootname: str,
) -> None:
    _Source.deny = False
    _Source.loaded = (_original_snapshot(study.FORWARD_NOT_BEFORE_MS + 10),)
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    root = tmp_path / rootname
    with pytest.raises(study.LongTrendForwardTrialError, match="prior shadow root"):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path,
            manifest=_manifest(),
            expected_manifest_id="0123456789abcdef01234567",
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            account_root=root,
        )
    assert not root.exists()


def test_invalid_source_fails_before_creating_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(study, "PinnedShortRankReplaySource", _Source)
    _Source.deny = True
    root = tmp_path / "fresh-only"
    try:
        with pytest.raises(ValueError, match="source manifest incomplete"):
            study.run_digest_pinned_long_trend_matched_paper(
                source_root=tmp_path,
                manifest=_manifest(),
                expected_manifest_id="0123456789abcdef01234567",
                config=BaselineReplayConfig(execution=PaperExecutionConfig()),
                selected_markets=(MARKET,),
                account_root=root,
            )
        assert not root.exists()
    finally:
        _Source.deny = False


def test_manifest_left_censored_starts_late_without_account_side_effects(
    tmp_path: Path,
) -> None:
    root = tmp_path / "never-created"
    with pytest.raises(study.LongTrendForwardTrialError, match="left-censored"):
        study.run_digest_pinned_long_trend_matched_paper(
            source_root=tmp_path,
            manifest=_manifest(start_offset=1),
            expected_manifest_id="0123456789abcdef01234567",
            config=BaselineReplayConfig(execution=PaperExecutionConfig()),
            selected_markets=(MARKET,),
            account_root=root,
        )
    assert not root.exists()
