from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)
from cocomelon.research.prospective_short_rank_full_feature_artifact import (
    VerifiedGithubOriginalRankInputs,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatch,
)
from cocomelon.research.prospective_short_rank_score_recomputation import (
    OriginalRankScoreRecomputationError,
    recompute_original_short_rank_coarse_scores,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    VerifiedGithubShortRankEvidence,
)
from cocomelon.scanner.ranker import rank_opportunities

D = Decimal
RUN = 38173963878
HEAD = "f" * 40
NOW = 1_790_000_000_000


def _feature(coin: str, now: int, multiple: int) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", coin),
        as_of_ms=now - 50,
        source_received_at_ms=now - 80,
        schema_version=1,
        day_return=D(multiple) / D(100),
        funding=D(multiple) / D(10000),
        open_interest=D(multiple * 1000),
        day_notional_volume=D(multiple * 100000),
        oi_change_fraction=D(multiple) / D(1000),
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=None,
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.MIXED,
        volatility_regime=VolatilityRegime.NORMAL,
        provenance=("synthetic-coarse-ranking",),
    )


def _observation(
    *,
    now: int = NOW,
    eligible_markets: frozenset[str] | None = None,
) -> tuple[FirstSeenRankSnapshot, OriginalRankFeatureInputBatch]:
    values = (
        _feature("A", now, 1),
        _feature("B", now, 3),
        _feature("C", now, 4),
        _feature("D", now, 5),
        _feature("E", now, 6),
    )
    if eligible_markets is None:
        eligible_markets = frozenset(("B", "C", "D", "E"))
    decisions = tuple(
        EligibilityDecision(
            market=feature.market,
            rankable=feature.market.canonical in eligible_markets,
            deep_ready=False,
            reasons=(
                () if feature.market.canonical in eligible_markets
                else ("synthetic_excluded",)
            ),
        )
        for feature in values
    )
    recomputed = rank_opportunities(values, decisions, mode="coarse")
    inputs = {feature.market.canonical: feature for feature in values}
    rank = FirstSeenRankSnapshot.from_observation(
        observed_at_ms=now,
        captured_at_ms=now + 25,
        features=inputs,
        ranks=recomputed,
    )
    return rank, OriginalRankFeatureInputBatch.from_original_rank(rank, inputs)


def _sources(
    rankings: tuple[FirstSeenRankSnapshot, ...],
    batches: tuple[OriginalRankFeatureInputBatch, ...],
    *,
    legacy_count: int = 0,
) -> tuple[VerifiedGithubShortRankEvidence, VerifiedGithubOriginalRankInputs]:
    ranked = VerifiedGithubShortRankEvidence(
        snapshots=rankings,
        rank_state_digest="a" * 64,
        archive_sha256="b" * 64,
        worker_run_id=RUN,
        worker_head_sha=HEAD,
        worker_run_attempt=1,
    )
    inputs = VerifiedGithubOriginalRankInputs(
        batches=batches,
        historical_rank_snapshots_without_inputs=legacy_count,
        source_digest="c" * 64,
        archive_sha256="d" * 64,
        original_rank_state_digest=ranked.rank_state_digest,
        worker_run_id=RUN,
        worker_head_sha=HEAD,
        worker_attempt=1,
    )
    return ranked, inputs


def test_original_coarse_rank_scores_recomputed_exactly_from_full_market_inputs(
) -> None:
    rank, batch = _observation()
    source, inputs = _sources((rank,), (batch,))
    result = recompute_original_short_rank_coarse_scores(
        original_rank=source, original_inputs=inputs,
    )
    assert result["recomputed_complete_rank_batches"] == 1
    assert result["recomputed_original_ranked_markets"] == 4
    assert result["full_original_source_feature_inputs_examined"] == 5
    assert result["recorded_unrankable_inputs_not_independently_classified"] == 1
    assert result["original_coarse_ordinal_score_reason_recomputed"] is True
    assert result["rankable_membership_taken_from_original_rank_source"] is True
    assert result["rankable_membership_independently_reconstructed"] is False
    assert result["market_meta_context_and_age_inputs_authenticated"] is False
    assert result["original_market_gap_coverage_authenticated"] is False
    assert result["full_account_trial"] is False
    assert result["ready_for_review"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_self_sealed_changed_score_fails_even_when_full_feature_ids_still_match(
) -> None:
    rank, batch = _observation()
    first = rank.ranks[0]
    changed = replace(rank, ranks=(
        (first[0], first[1], "0.999999", first[3]),
        *rank.ranks[1:],
    ))
    changed_batch = replace(
        batch, rank_snapshot_digest=changed.snapshot_digest,
    )
    assert changed_batch.bind_to(changed) is None
    source, inputs = _sources((changed,), (changed_batch,))
    with pytest.raises(OriginalRankScoreRecomputationError, match="cannot be recomputed"):
        recompute_original_short_rank_coarse_scores(
            original_rank=source, original_inputs=inputs,
        )


def test_changed_original_reason_or_order_fails_with_valid_feature_source() -> None:
    rank, batch = _observation()
    first, second, *rest = rank.ranks
    reasons = tuple(reversed(first[3]))
    changed = replace(rank, ranks=((first[0], first[1], first[2], reasons),) +
        tuple(rank.ranks[1:]))
    source, inputs = _sources(
        (changed,), (replace(batch, rank_snapshot_digest=changed.snapshot_digest),),
    )
    with pytest.raises(OriginalRankScoreRecomputationError, match="cannot be recomputed"):
        recompute_original_short_rank_coarse_scores(
            original_rank=source, original_inputs=inputs,
        )
    altered_order = replace(
        rank,
        ranks=(
            (second[0], 1, second[2], second[3]),
            (first[0], 2, first[2], first[3]),
            *rest,
        ),
    )
    source, inputs = _sources(
        (altered_order,),
        (replace(batch, rank_snapshot_digest=altered_order.snapshot_digest),),
    )
    with pytest.raises(OriginalRankScoreRecomputationError, match="cannot be recomputed"):
        recompute_original_short_rank_coarse_scores(
            original_rank=source, original_inputs=inputs,
        )


def test_ranked_market_below_observed_quantile_floor_cannot_pass() -> None:
    rank, batch = _observation(
        eligible_markets=frozenset(("A", "B", "C", "D", "E")),
    )
    source, inputs = _sources((rank,), (batch,))
    with pytest.raises(
        OriginalRankScoreRecomputationError, match="volume/OI floor"
    ):
        recompute_original_short_rank_coarse_scores(
            original_rank=source, original_inputs=inputs,
        )


def test_honest_old_rank_input_holes_are_never_retroactively_reconstructed() -> None:
    earlier, _ = _observation(now=NOW)
    after, batch = _observation(now=NOW + 30_000)
    source, inputs = _sources(
        (earlier, after), (batch,), legacy_count=1,
    )
    result = recompute_original_short_rank_coarse_scores(
        original_rank=source, original_inputs=inputs,
    )
    assert result["recomputed_complete_rank_batches"] == 1
    assert result["old_original_rank_batches_without_features"] == 1
    assert result["full_account_trial"] is False
    assert result["after_fee_risk_matched_profits_certified"] is False


def test_mismatched_original_worker_or_rank_population_fails_without_salvage() -> None:
    rank, batch = _observation()
    source, inputs = _sources((rank,), (batch,))
    with pytest.raises(OriginalRankScoreRecomputationError, match="same verified"):
        recompute_original_short_rank_coarse_scores(
            original_rank=source,
            original_inputs=replace(inputs, worker_run_id=RUN + 1),
        )
    with pytest.raises(OriginalRankScoreRecomputationError, match="declared"):
        recompute_original_short_rank_coarse_scores(
            original_rank=source,
            original_inputs=replace(inputs, historical_rank_snapshots_without_inputs=1),
        )
    with pytest.raises(OriginalRankScoreRecomputationError, match="declared"):
        recompute_original_short_rank_coarse_scores(
            original_rank=source,
            original_inputs=replace(inputs, batches=()),
        )


def test_original_rank_universe_membership_is_not_proven_by_score_recomputation() -> None:
    # Deliberately omit one otherwise-qualifying market. The scores for the
    # remaining claimed subset should still match, but the result MUST say
    # full original eligibility membership was not independently verified.
    rank, batch = _observation(
        eligible_markets=frozenset(("B", "C", "E")),
    )
    source, inputs = _sources((rank,), (batch,))
    result = recompute_original_short_rank_coarse_scores(
        original_rank=source, original_inputs=inputs,
    )
    assert result["recomputed_original_ranked_markets"] == 3
    assert result["recorded_unrankable_inputs_not_independently_classified"] == 2
    assert result["rankable_membership_independently_reconstructed"] is False
    assert result["ready_for_review"] is False
