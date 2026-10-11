"""Fail-closed identity join of original first-seen ranks to stored features.

The original paper worker has two distinct feature producers: ranking's
complete coarse-universe source and decision-learning's selected snapshots.
A checksum on either separately does not demonstrate that a rank input was
actually preserved for independent reconstruction. Never credit an unmatched
feature, and never turn a matched internal record into proof of mainnet L2.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from cocomelon.research.learning_feature_snapshots import (
    VerifiedLearningFeatureSnapshot,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)

MAX_UNMATCHED_EXAMPLES: Final = 16
HEX: Final = frozenset("0123456789abcdef")


class ShortRankFeatureSourceError(RuntimeError):
    """Invalid internal feature input, or missing inputs under strict closure."""


def rank_feature_source_coverage(
    snapshots: Sequence[FirstSeenRankSnapshot],
    verified_feature_index: Mapping[str, VerifiedLearningFeatureSnapshot],
) -> dict[str, object]:
    """Count exact source-feature references; do not fill unrecorded ranking rows.

    'Verified' here means the individual feature payload passed the existing
    local immutable LearningFeatureSnapshotStore validation. The *source*
    GitHub artifact origin and original mainnet event stream still need
    independent proof, regardless of 100% local reference coverage.
    """
    if not snapshots:
        raise ShortRankFeatureSourceError(
            "original first-seen rank snapshot cohort is empty"
        )
    for key, record in verified_feature_index.items():
        if (
            not isinstance(key, str)
            or len(key) != 24
            or any(char not in HEX for char in key)
            or record.snapshot.snapshot_id != key
            or len(record.record_sha256) != 64
            or any(char not in HEX for char in record.record_sha256)
        ):
            raise ShortRankFeatureSourceError(
                "supplied feature source index contains falsified identity"
            )
    referenced: dict[str, tuple[str, int]] = {}
    missing_counts: Counter[str] = Counter()
    verified_count = 0
    total_count = 0
    for rank_snapshot in snapshots:
        for market, snapshot_id, received_ms in rank_snapshot.features:
            total_count += 1
            if (
                len(snapshot_id) != 24
                or any(char not in HEX for char in snapshot_id)
                or received_ms > rank_snapshot.observed_at_ms
            ):
                raise ShortRankFeatureSourceError(
                    "original ranked feature reference is not causal/canonical"
                )
            current = (market, received_ms)
            if snapshot_id in referenced and referenced[snapshot_id] != current:
                raise ShortRankFeatureSourceError(
                    "original rank reused feature ID with incompatible identity"
                )
            referenced[snapshot_id] = current
            source = verified_feature_index.get(snapshot_id)
            if source is None:
                missing_counts[market] += 1
                continue
            feature = source.snapshot
            if (
                feature.market.canonical != market
                or feature.source_received_at_ms != received_ms
                or feature.as_of_ms > rank_snapshot.observed_at_ms
            ):
                raise ShortRankFeatureSourceError(
                    "source feature identity or as-of clock disagrees with ranking"
                )
            verified_count += 1
    if total_count == 0:
        raise ShortRankFeatureSourceError(
            "original first-seen ranked universe has no source feature references"
        )
    missing_ids = sorted(
        key for key in referenced if key not in verified_feature_index
    )
    # The number of unique identifiers can be smaller than the number of
    # observations when a complete unchanged feature is reused legitimately.
    return {
        "rank_snapshot_count": len(snapshots),
        "rank_feature_reference_count": total_count,
        "rank_feature_unique_reference_id_count": len(referenced),
        "source_feature_store_record_count": len(verified_feature_index),
        "exact_rank_feature_reference_match_count": verified_count,
        "unmatched_rank_feature_reference_count": total_count - verified_count,
        "unmatched_unique_rank_feature_id_count": len(missing_ids),
        "unmatched_market_counts": dict(sorted(missing_counts.items())),
        "unmatched_reference_id_examples": missing_ids[:MAX_UNMATCHED_EXAMPLES],
        "unmatched_reference_examples_capped": (
            len(missing_ids) > MAX_UNMATCHED_EXAMPLES
        ),
        "rank_feature_internal_id_closure_complete": (
            verified_count == total_count
        ),
        "rank_feature_source_github_artifact_authenticated_by_caller": False,
        "rank_features_independently_reconstructed_from_mainnet": False,
        "full_market_microstructure_source_gap_coverage_certified": False,
        "original_paper_feature_to_trade_cashflow_attested": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def require_full_rank_feature_source_closure(
    snapshots: Sequence[FirstSeenRankSnapshot],
    verified_feature_index: Mapping[str, VerifiedLearningFeatureSnapshot],
) -> dict[str, object]:
    """Refuse economic attribution with any unverified original rank input."""
    receipt = rank_feature_source_coverage(
        snapshots, verified_feature_index,
    )
    if receipt["rank_feature_internal_id_closure_complete"] is not True:
        raise ShortRankFeatureSourceError(
            "ORIGINAL_RANK_FEATURE_SOURCE_CLOSURE_INCOMPLETE"
        )
    return receipt
