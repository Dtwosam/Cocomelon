from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.entry_mid_markout_readiness import (
    MAX_NON_FRESH_FRACTION,
    MIN_FRESH_OBSERVATIONS_PER_HORIZON,
    EntryMidMarkoutReadinessError,
    EntryMidMarkoutReadinessStatus,
    entry_mid_markout_readiness,
)
from cocomelon.research.entry_mid_markout_shadow import (
    ENTRY_MID_MARKOUT_HORIZONS_MS,
    ENTRY_MID_MARKOUT_MAX_LAG_MS,
)


def _summary(
    *,
    fresh: int,
    stale: int = 0,
    missing_at_close: int = 0,
    censored: int = 0,
    attribution_misses: int = 0,
    unmatched_closed: int = 0,
    lineage_mismatch: int = 0,
    orphaned: int = 0,
) -> dict[str, object]:
    return {
        "source": "allMids_mid_px",
        "horizons_ms": list(
            ENTRY_MID_MARKOUT_HORIZONS_MS
        ),
        "max_observation_lag_ms": (
            ENTRY_MID_MARKOUT_MAX_LAG_MS
        ),
        "unmatched_closed_trades": unmatched_closed,
        "lineage_mismatch_closed_trades": lineage_mismatch,
        "orphaned_restored_positions": orphaned,
        "by_horizon_ms": {
            str(horizon_ms): {
                "fresh": fresh,
                "stale": stale,
                "missing_at_close": missing_at_close,
                "censored": censored,
                "decision_attribution_misses": (
                    attribution_misses
                ),
            }
            for horizon_ms in ENTRY_MID_MARKOUT_HORIZONS_MS
        },
    }


def test_allmids_readiness_collects_until_each_horizon_has_volume() -> None:
    result = entry_mid_markout_readiness(
        _summary(fresh=0)
    )

    assert result.all_horizons_ready_for_review is False
    assert result.promotion_authority is False
    assert result.execution_authority is False
    assert len(result.horizons) == 3
    for horizon in result.horizons:
        assert horizon.fresh == 0
        assert horizon.missing_fresh_observations == (
            MIN_FRESH_OBSERVATIONS_PER_HORIZON
        )
        assert horizon.non_fresh_fraction is None
        assert horizon.coverage_quality_ready is False
        assert (
            horizon.status
            is EntryMidMarkoutReadinessStatus.COLLECTING
        )


def test_allmids_readiness_accepts_small_non_fresh_fraction() -> None:
    result = entry_mid_markout_readiness(
        _summary(
            fresh=30,
            stale=2,
            missing_at_close=1,
            censored=5,
        )
    )

    assert result.all_horizons_ready_for_review is True
    for horizon in result.horizons:
        assert horizon.missing_fresh_observations == 0
        assert horizon.non_fresh_fraction == (
            Decimal(3) / Decimal(33)
        )
        assert (
            horizon.non_fresh_fraction
            <= MAX_NON_FRESH_FRACTION
        )
        assert horizon.coverage_quality_ready is True
        assert (
            horizon.status
            is EntryMidMarkoutReadinessStatus.READY_FOR_REVIEW
        )


def test_allmids_readiness_blocks_degraded_observation_coverage() -> None:
    result = entry_mid_markout_readiness(
        _summary(
            fresh=30,
            stale=4,
        )
    )

    assert result.all_horizons_ready_for_review is False
    for horizon in result.horizons:
        assert horizon.missing_fresh_observations == 0
        assert horizon.non_fresh_fraction == (
            Decimal(4) / Decimal(34)
        )
        assert (
            horizon.non_fresh_fraction
            > MAX_NON_FRESH_FRACTION
        )
        assert horizon.coverage_quality_ready is False
        assert (
            horizon.status
            is EntryMidMarkoutReadinessStatus.COLLECTING
        )


def test_allmids_readiness_blocks_decision_attribution_miss() -> None:
    result = entry_mid_markout_readiness(
        _summary(
            fresh=30,
            attribution_misses=1,
        )
    )

    assert result.all_horizons_ready_for_review is False
    assert all(
        horizon.coverage_quality_ready is False
        for horizon in result.horizons
    )


def test_allmids_readiness_blocks_unmatched_closed_trade_globally() -> None:
    result = entry_mid_markout_readiness(
        _summary(
            fresh=30,
            unmatched_closed=1,
        )
    )

    assert all(
        horizon.status
        is EntryMidMarkoutReadinessStatus.READY_FOR_REVIEW
        for horizon in result.horizons
    )
    assert result.unmatched_closed_trades == 1
    assert result.all_horizons_ready_for_review is False


def test_allmids_readiness_fails_closed_on_protocol_mismatch() -> None:
    summary = _summary(fresh=30)
    summary["max_observation_lag_ms"] = 120_000

    with pytest.raises(
        EntryMidMarkoutReadinessError,
        match="lag protocol mismatch",
    ):
        entry_mid_markout_readiness(summary)


def test_allmids_readiness_blocks_research_integrity_mismatch() -> None:
    result = entry_mid_markout_readiness(
        _summary(
            fresh=MIN_FRESH_OBSERVATIONS_PER_HORIZON,
            lineage_mismatch=1,
            orphaned=1,
        )
    )

    assert result.lineage_mismatch_closed_trades == 1
    assert result.orphaned_restored_positions == 1
    assert result.all_horizons_ready_for_review is False
