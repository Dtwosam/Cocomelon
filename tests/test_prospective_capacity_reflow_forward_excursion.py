from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathMark,
)
from cocomelon.research.prospective_capacity_reflow_forward_excursion import (
    ProspectiveCapacityReflowForwardExcursionError,
    prospective_capacity_reflow_forward_excursion_summary,
)


def _forward_markout() -> dict[str, object]:
    return {
        "replacement_forward_markouts_modeled": True,
        "horizons_ms": [300_000, 900_000],
        "option_markouts": [
            {
                "option_id": "opp-1:release-plan-1",
                "opportunity_id": "opp-1",
                "opportunity_timestamp_ms": 10_000,
                "opportunity_market": "SOL",
                "opportunity_direction": "long",
                "release_market": "BTC",
                "release_opening_plan_id": "release-plan-1",
                "attempt_id": "attempt-1",
                "entry_price": "100",
                "filled_quantity": "2",
                "gross_fill_notional": "200",
                "entry_fee": "0.2",
                "markouts": {
                    "300000": {
                        "status": "settled",
                        "horizon_ms": 300_000,
                        "target_at_ms": 310_000,
                        "observed_at_ms": 310_000,
                        "observation_lag_ms": 0,
                        "mark_px": "98",
                        "directional_return_fraction": "-0.02",
                        "gross_mark_to_market_pnl": "-4",
                        "entry_fee_adjusted_mark_to_market_pnl": "-4.2",
                    },
                    "900000": {
                        "status": "pending",
                        "horizon_ms": 900_000,
                        "target_at_ms": 910_000,
                        "observed_at_ms": None,
                        "observation_lag_ms": None,
                        "mark_px": None,
                        "directional_return_fraction": None,
                        "gross_mark_to_market_pnl": None,
                        "entry_fee_adjusted_mark_to_market_pnl": None,
                    },
                },
            }
        ],
    }


def _path(
    *,
    direction: str = "long",
    market: str = "SOL",
) -> ContinuousPaperOpeningOpportunityPath:
    return ContinuousPaperOpeningOpportunityPath(
        opportunity_id="opp-1",
        market=market,
        direction=direction,
        opportunity_timestamp_ms=10_000,
        max_path_age_ms=21_600_000,
        max_completion_lag_ms=120_000,
        marks=(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=70_000,
                mark_px=Decimal("101"),
                source="metaAndAssetCtxs",
            ),
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=190_000,
                mark_px=Decimal("105"),
                source="metaAndAssetCtxs",
            ),
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=310_000,
                mark_px=Decimal("98"),
                source="metaAndAssetCtxs",
            ),
        ),
    )


def test_forward_excursion_exposes_peak_giveback_and_reversal() -> None:
    result = prospective_capacity_reflow_forward_excursion_summary(
        _forward_markout(),
        (_path(),),
    )

    assert result["fillable_options"] == 1
    assert result["paths_available"] == 1
    assert result["paths_missing"] == 0
    assert result["replacement_forward_excursions_modeled"] is True
    assert result["replacement_exits_modeled"] is False
    assert result["realized_pnl_modeled"] is False

    option = result["option_excursions"][0]
    five = option["excursions"]["300000"]
    assert five["status"] == "settled"
    assert five["observed_marks"] == 3
    assert five["best_mark_px"] == "105"
    assert five["best_observed_at_ms"] == 190_000
    assert five["time_to_best_ms"] == 180_000
    assert five["worst_mark_px"] == "98"
    assert five["worst_observed_at_ms"] == 310_000
    assert five["best_entry_fee_adjusted_mtm_pnl"] == "9.8"
    assert five["worst_entry_fee_adjusted_mtm_pnl"] == "-4.2"
    assert five["ending_entry_fee_adjusted_mtm_pnl"] == "-4.2"
    assert five["peak_to_end_giveback_pnl"] == "14.0"
    assert five["positive_peak_to_negative_end"] is True

    fifteen = option["excursions"]["900000"]
    assert fifteen["status"] == "pending"

    aggregate = result["by_horizon"]["300000"]
    assert aggregate["settled_options"] == 1
    assert aggregate["positive_peak_options"] == 1
    assert aggregate["negative_end_options"] == 1
    assert aggregate["positive_peak_to_negative_end_options"] == 1
    assert aggregate["best_entry_fee_adjusted_mtm_pnl"] == "9.8"
    assert aggregate["ending_entry_fee_adjusted_mtm_pnl"] == "-4.2"
    assert aggregate["peak_to_end_giveback_pnl"] == "14.0"


def test_forward_excursion_rejects_path_lineage_mismatch() -> None:
    with pytest.raises(
        ProspectiveCapacityReflowForwardExcursionError,
        match="forward excursion path lineage mismatch",
    ):
        prospective_capacity_reflow_forward_excursion_summary(
            _forward_markout(),
            (_path(direction="short"),),
        )
