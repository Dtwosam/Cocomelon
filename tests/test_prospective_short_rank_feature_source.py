from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.research.learning_feature_snapshots import (
    VerifiedLearningFeatureSnapshot,
)
from cocomelon.research.prospective_short_rank_feature_source import (
    ShortRankFeatureSourceError,
    rank_feature_source_coverage,
    require_full_rank_feature_source_closure,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)

D = Decimal


def _feature(market: str, received_ms: int, *, as_of_offset: int = 10) -> (
    FeatureSnapshot
):
    return FeatureSnapshot(
        market=MarketId("", market),
        as_of_ms=received_ms + as_of_offset,
        source_received_at_ms=received_ms,
        schema_version=1,
        day_return=None,
        funding=D("0"),
        open_interest=D("12000"),
        day_notional_volume=D("100000"),
        oi_change_fraction=None,
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
        volatility_regime=VolatilityRegime.LOW,
        provenance=("hyperliquid-mainnet-info",),
    )


def _rank(
    features: tuple[FeatureSnapshot, ...],
    *,
    observed_ms: int = 10_100,
) -> FirstSeenRankSnapshot:
    return FirstSeenRankSnapshot(
        observed_at_ms=observed_ms,
        captured_at_ms=observed_ms + 25,
        features=tuple(sorted(
            (
                feature.market.canonical,
                feature.snapshot_id,
                feature.source_received_at_ms,
            )
            for feature in features
        )),
        ranks=tuple(
            (feature.market.canonical, i, "0.7", ("unit",))
            for i, feature in enumerate(features, start=1)
        ),
    )


def _record(feature: FeatureSnapshot) -> VerifiedLearningFeatureSnapshot:
    return VerifiedLearningFeatureSnapshot(
        snapshot=feature,
        record_sha256="a" * 64,
    )


def test_complete_local_rank_feature_source_closure_is_not_mainnet_authentication() -> None:
    a = _feature("BTC", 10_000)
    b = _feature("ETH", 10_010)
    rank = _rank((a, b))
    indexed = {
        a.snapshot_id: _record(a),
        b.snapshot_id: _record(b),
    }
    proof = require_full_rank_feature_source_closure((rank,), indexed)
    assert proof["rank_feature_reference_count"] == 2
    assert proof["exact_rank_feature_reference_match_count"] == 2
    assert proof["unmatched_rank_feature_reference_count"] == 0
    assert proof["rank_feature_internal_id_closure_complete"] is True
    assert proof["rank_feature_source_github_artifact_authenticated_by_caller"] is False
    assert proof["rank_features_independently_reconstructed_from_mainnet"] is False
    assert proof["full_account_trial"] is False
    assert proof["ready_for_review"] is False
    assert proof["promotion_authority"] is False
    assert proof["execution_authority"] is False


def test_missing_rank_input_never_counts_as_a_prospective_verified_skip() -> None:
    a = _feature("BTC", 10_000)
    b = _feature("ETH", 10_010)
    rank = _rank((a, b))
    source = {a.snapshot_id: _record(a)}
    proof = rank_feature_source_coverage((rank,), source)
    assert proof["exact_rank_feature_reference_match_count"] == 1
    assert proof["unmatched_rank_feature_reference_count"] == 1
    assert proof["unmatched_unique_rank_feature_id_count"] == 1
    assert proof["unmatched_market_counts"] == {"ETH": 1}
    assert proof["rank_feature_internal_id_closure_complete"] is False
    with pytest.raises(
        ShortRankFeatureSourceError, match="SOURCE_CLOSURE_INCOMPLETE"
    ):
        require_full_rank_feature_source_closure((rank,), source)


def test_absent_rank_feature_artifact_does_not_certify_any_input() -> None:
    rank = _rank((_feature("BTC", 10_000),))
    proof = rank_feature_source_coverage((rank,), {})
    assert proof["source_feature_store_record_count"] == 0
    assert proof["exact_rank_feature_reference_match_count"] == 0
    assert proof["unmatched_rank_feature_reference_count"] == 1
    assert proof["ready_for_review"] is False
    with pytest.raises(ShortRankFeatureSourceError, match="INCOMPLETE"):
        require_full_rank_feature_source_closure((rank,), {})


def test_corrupt_source_index_or_wrong_feature_received_clock_fails_closed() -> None:
    feature = _feature("BTC", 10_000)
    rank = _rank((feature,))
    with pytest.raises(ShortRankFeatureSourceError, match="falsified identity"):
        rank_feature_source_coverage(
            (rank,), {"b" * 24: _record(feature)}
        )
    altered = replace(
        rank,
        features=(("BTC", feature.snapshot_id, 9_999),),
    )
    with pytest.raises(ShortRankFeatureSourceError, match="disagrees"):
        rank_feature_source_coverage(
            (altered,), {feature.snapshot_id: _record(feature)}
        )


def test_snapshot_as_of_later_than_rank_observation_is_not_causal() -> None:
    feature = _feature("BTC", 10_000, as_of_offset=500)
    rank = _rank((feature,), observed_ms=10_100)
    with pytest.raises(ShortRankFeatureSourceError, match="clock"):
        rank_feature_source_coverage(
            (rank,), {feature.snapshot_id: _record(feature)}
        )


def test_one_unchanged_feature_can_legitimately_be_referenced_twice() -> None:
    feature = _feature("BTC", 10_000)
    before = _rank((feature,), observed_ms=10_100)
    after = _rank((feature,), observed_ms=10_130)
    proof = rank_feature_source_coverage(
        (before, after), {feature.snapshot_id: _record(feature)}
    )
    assert proof["rank_feature_reference_count"] == 2
    assert proof["rank_feature_unique_reference_id_count"] == 1
    assert proof["exact_rank_feature_reference_match_count"] == 2
    assert proof["rank_feature_internal_id_closure_complete"] is True


def test_empty_rank_archive_or_empty_rank_feature_cohort_is_not_an_edge() -> None:
    with pytest.raises(ShortRankFeatureSourceError, match="empty"):
        rank_feature_source_coverage((), {})
    empty = FirstSeenRankSnapshot(
        observed_at_ms=10_100,
        captured_at_ms=10_101,
        features=(),
        ranks=(),
    )
    with pytest.raises(ShortRankFeatureSourceError, match="no source"):
        rank_feature_source_coverage((empty,), {})
