"""Recompute recorded SHORT coarse scores from original complete feature inputs.

This is a READ-ONLY independent arithmetic check, conditional on the original
worker's claimed rankable universe. Reconstructing complete eligibility needs
separately authenticated market meta/context; a numerically correct score is
not a profitable trading edge or proof of exchange feed authenticity.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Final

from cocomelon.domain.features import EligibilityDecision
from cocomelon.research.prospective_short_rank_full_feature_artifact import (
    VerifiedGithubOriginalRankInputs,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankInputBatchError,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    VerifiedGithubShortRankEvidence,
)
from cocomelon.scanner.eligibility import (
    EligibilityConfig,
    derive_eligibility_thresholds,
)
from cocomelon.scanner.ranker import rank_opportunities

ZERO: Final = Decimal("0")


class OriginalRankScoreRecomputationError(RuntimeError):
    """The original ranked-source arithmetic or binding is not reproducible."""


def recompute_original_short_rank_coarse_scores(
    *,
    original_rank: VerifiedGithubShortRankEvidence,
    original_inputs: VerifiedGithubOriginalRankInputs,
) -> dict[str, object]:
    """Fail if a claimed ordinal, score, or reason differs from replayed inputs.

    Full-input suffix batches must already have been checked against the
    separately authenticated worker rank ZIP and immutable rank state digest.
    This verifier NEVER infers omitted legacy feature payloads.
    """
    if (
        original_rank.worker_run_id != original_inputs.worker_run_id
        or original_rank.worker_run_attempt != original_inputs.worker_attempt
        or original_rank.worker_head_sha != original_inputs.worker_head_sha
        or original_rank.rank_state_digest != original_inputs.original_rank_state_digest
    ):
        raise OriginalRankScoreRecomputationError(
            "rank and full-input source are not the same verified original worker"
        )
    prefix = original_inputs.historical_rank_snapshots_without_inputs
    batches = original_inputs.batches
    snapshots = original_rank.snapshots
    if (
        type(prefix) is not int or prefix < 0
        or not batches
        or prefix + len(batches) != len(snapshots)
    ):
        raise OriginalRankScoreRecomputationError(
            "full rank-input suffix does not cover the declared original source"
        )
    total_ranked = 0
    total_features = 0
    diagnostic_unranked = 0
    default_eligibility = EligibilityConfig()
    for source, batch in zip(snapshots[prefix:], batches, strict=True):
        try:
            batch.bind_to(source)
        except OriginalRankInputBatchError as exc:
            raise OriginalRankScoreRecomputationError(
                "saved full feature inputs do not match exact original ranked source"
            ) from exc
        features = batch.features
        if not features:
            raise OriginalRankScoreRecomputationError(
                "original coarse rank observation has no full feature universe"
            )
        claimed_rankable = {market for market, _, _, _ in source.ranks}
        feature_by_market = {item.market.canonical: item for item in features}
        if not claimed_rankable.issubset(feature_by_market):
            raise OriginalRankScoreRecomputationError(
                "ranked market missing from full original input universe"
            )
        thresholds = derive_eligibility_thresholds(features, default_eligibility)
        # These are *necessary* observed eligibility criteria, not sufficient.
        # Meta status, context prices/leverage/age are unavailable here and
        # never synthesized to classify omitted markets independently.
        for market in claimed_rankable:
            feature = feature_by_market[market]
            if (
                feature.day_notional_volume < thresholds.min_day_notional_volume
                or feature.open_interest < thresholds.min_open_interest
            ):
                raise OriginalRankScoreRecomputationError(
                    "ranked market violates derived observed volume/OI floor"
                )
        decisions = tuple(
            EligibilityDecision(
                market=feature.market,
                rankable=feature.market.canonical in claimed_rankable,
                deep_ready=False,
                reasons=(
                    () if feature.market.canonical in claimed_rankable
                    else ("recorded_unrankable_not_independently_proven",)
                ),
            )
            for feature in features
        )
        reconstructed = rank_opportunities(
            features, decisions, mode="coarse",
        )
        if len(reconstructed) != len(source.ranks):
            raise OriginalRankScoreRecomputationError(
                "full feature rank reconstruction size differs from original"
            )
        for rank, (market, ordinal, score, reasons) in zip(
            reconstructed, source.ranks, strict=True,
        ):
            if (
                rank.market.canonical != market
                or rank.ordinal != ordinal
                or str(rank.score) != score
                or rank.reason_codes != reasons
            ):
                raise OriginalRankScoreRecomputationError(
                    "original coarse rank ordinal/score/reasons cannot be recomputed"
                )
        total_ranked += len(source.ranks)
        total_features += len(features)
        diagnostic_unranked += len(features) - len(source.ranks)
    if total_ranked == 0:
        raise OriginalRankScoreRecomputationError(
            "no original ranked-market score exists in complete input suffix"
        )
    return {
        "schema_version": 1,
        "worker_run_id": original_rank.worker_run_id,
        "worker_run_attempt": original_rank.worker_run_attempt,
        "worker_head_sha": original_rank.worker_head_sha,
        "original_rank_state_digest": original_rank.rank_state_digest,
        "full_input_source_digest": original_inputs.source_digest,
        "recomputed_complete_rank_batches": len(batches),
        "recomputed_original_ranked_markets": total_ranked,
        "full_original_source_feature_inputs_examined": total_features,
        "recorded_unrankable_inputs_not_independently_classified": (
            diagnostic_unranked
        ),
        "old_original_rank_batches_without_features": prefix,
        "original_coarse_ordinal_score_reason_recomputed": True,
        "rankable_membership_taken_from_original_rank_source": True,
        "rankable_membership_independently_reconstructed": False,
        "market_meta_context_and_age_inputs_authenticated": False,
        "original_market_gap_coverage_authenticated": False,
        "score_ranking_arithmetic_matches_original": True,
        "after_fee_risk_matched_profits_certified": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
