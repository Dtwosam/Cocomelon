from __future__ import annotations

from cocomelon.research.entry_markout_readiness import (
    MIN_OBSERVATIONS_PER_HORIZON,
    EntryMarkoutReadinessStatus,
    entry_markout_readiness,
)


def _summary(
    observations: int,
) -> dict[str, object]:
    return {
        "observations": observations,
        "positive": 0,
        "negative": observations,
        "flat": 0,
        "mean_signed_return_bps": None,
        "mean_gross_r": None,
        "mean_observation_lag_ms": None,
        "max_observation_lag_ms": None,
        "censored_before_horizon": 0,
        "missing_observed_mark": 0,
        "by_side": {},
        "by_lead_strategy": {},
    }


def test_entry_markout_readiness_collects_until_every_horizon_has_30() -> None:
    summary = {
        "by_horizon_ms": {
            "60000": _summary(30),
            "300000": _summary(29),
            "900000": _summary(10),
        }
    }

    result = entry_markout_readiness(summary)

    assert MIN_OBSERVATIONS_PER_HORIZON == 30
    assert result.all_horizons_ready_for_review is False
    assert result.promotion_authority is False
    assert result.execution_authority is False
    one, five, fifteen = result.horizons
    assert one.status is EntryMarkoutReadinessStatus.READY_FOR_REVIEW
    assert one.missing_observations == 0
    assert five.status is EntryMarkoutReadinessStatus.COLLECTING
    assert five.missing_observations == 1
    assert fifteen.status is EntryMarkoutReadinessStatus.COLLECTING
    assert fifteen.missing_observations == 20


def test_entry_markout_readiness_is_volume_only() -> None:
    summary = {
        "by_horizon_ms": {
            "60000": _summary(30),
            "300000": _summary(31),
            "900000": _summary(40),
        }
    }
    for item in summary["by_horizon_ms"].values():
        assert isinstance(item, dict)
        item["mean_gross_r"] = "-99"
        item["mean_signed_return_bps"] = "-9999"

    result = entry_markout_readiness(summary)

    assert result.all_horizons_ready_for_review is True
    assert all(
        item.status
        is EntryMarkoutReadinessStatus.READY_FOR_REVIEW
        for item in result.horizons
    )
