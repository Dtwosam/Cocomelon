from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathMark,
)
from cocomelon.research.prospective_capacity_reflow_forward_markout import (
    DEFAULT_FORWARD_MARKOUT_HORIZONS_MS,
    MAX_FORWARD_MARKOUT_LAG_MS,
    ProspectiveCapacityReflowForwardMarkoutError,
    prospective_capacity_reflow_forward_markout_summary,
)


def _fill_payload() -> dict[str, object]:
    return {
        "replacement_entry_fills_modeled": True,
        "option_results": [
            {
                "option_id": "opp-1:release-plan-1",
                "opportunity_id": "opp-1",
                "opportunity_timestamp_ms": 10_000,
                "opportunity_market": "SOL",
                "opportunity_direction": "long",
                "release_market": "BTC",
                "release_opening_plan_id": "release-plan-1",
                "execution_result": "partial",
                "attempt_id": "attempt-1",
                "filled_quantity": "2",
                "average_fill_price": "100",
                "gross_fill_notional": "200",
                "taker_fee": "0.2",
            }
        ],
    }


def _path(
    *marks: tuple[int, str],
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
        marks=tuple(
            ContinuousPaperOpeningOpportunityPathMark(
                observed_at_ms=observed_at_ms,
                mark_px=Decimal(mark_px),
                source="metaAndAssetCtxs",
            )
            for observed_at_ms, mark_px in marks
        ),
    )


def test_forward_markout_uses_first_bounded_mark_after_each_horizon() -> None:
    path = _path(
        (310_000, "99"),
        (340_000, "102"),
        (950_000, "99"),
        (3_620_000, "105"),
    )
    result = prospective_capacity_reflow_forward_markout_summary(
        _fill_payload(),
        (path,),
    )

    assert result["horizons_ms"] == list(
        DEFAULT_FORWARD_MARKOUT_HORIZONS_MS
    )
    assert result["max_mark_lag_ms"] == MAX_FORWARD_MARKOUT_LAG_MS
    assert result["fillable_options"] == 1
    assert result["paths_available"] == 1
    assert result["paths_missing"] == 0
    assert result["replacement_entry_fills_modeled"] is True
    assert result["replacement_forward_markouts_modeled"] is True
    assert result["replacement_exits_modeled"] is False
    assert result["realized_pnl_modeled"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False

    option = result["option_markouts"][0]
    assert option["option_id"] == "opp-1:release-plan-1"
    assert option["opportunity_id"] == "opp-1"
    assert option["entry_price"] == "100"
    assert option["filled_quantity"] == "2"
    assert option["entry_fee"] == "0.2"

    markouts = option["markouts"]
    five = markouts["300000"]
    assert five["status"] == "settled"
    assert five["observed_at_ms"] == 310_000
    assert five["observation_lag_ms"] == 0
    assert five["mark_px"] == "99"
    assert five["directional_return_fraction"] == "-0.01"
    assert five["gross_mark_to_market_pnl"] == "-2"
    assert five["entry_fee_adjusted_mark_to_market_pnl"] == "-2.2"

    fifteen = markouts["900000"]
    assert fifteen["status"] == "settled"
    assert fifteen["observed_at_ms"] == 950_000
    assert fifteen["observation_lag_ms"] == 40_000
    assert fifteen["mark_px"] == "99"

    hour = markouts["3600000"]
    assert hour["status"] == "settled"
    assert hour["observed_at_ms"] == 3_620_000
    assert hour["observation_lag_ms"] == 10_000
    assert hour["directional_return_fraction"] == "0.05"
    assert hour["gross_mark_to_market_pnl"] == "10"
    assert hour["entry_fee_adjusted_mark_to_market_pnl"] == "9.8"

    six_hour = markouts["21600000"]
    assert six_hour["status"] == "pending"

    five_summary = result["by_horizon"]["300000"]
    assert five_summary["settled_options"] == 1
    assert five_summary["positive_options"] == 0
    assert five_summary["negative_options"] == 1
    assert five_summary["gross_mark_to_market_pnl"] == "-2"
    assert (
        five_summary["entry_fee_adjusted_mark_to_market_pnl"]
        == "-2.2"
    )


def test_forward_markout_marks_late_observation_stale() -> None:
    target = 10_000 + 300_000
    path = _path(
        (
            target + MAX_FORWARD_MARKOUT_LAG_MS + 1,
            "110",
        ),
    )
    result = prospective_capacity_reflow_forward_markout_summary(
        _fill_payload(),
        (path,),
        horizons_ms=(300_000,),
    )

    markout = result["option_markouts"][0]["markouts"]["300000"]
    assert markout["status"] == "stale"
    assert markout["observation_lag_ms"] == (
        MAX_FORWARD_MARKOUT_LAG_MS + 1
    )
    summary = result["by_horizon"]["300000"]
    assert summary["settled_options"] == 0
    assert summary["stale_options"] == 1


def test_forward_markout_reports_missing_path_without_inventing_mark() -> None:
    result = prospective_capacity_reflow_forward_markout_summary(
        _fill_payload(),
        (),
        horizons_ms=(300_000,),
    )

    assert result["paths_available"] == 0
    assert result["paths_missing"] == 1
    markout = result["option_markouts"][0]["markouts"]["300000"]
    assert markout["status"] == "missing_path"
    assert markout["mark_px"] is None
    assert result["by_horizon"]["300000"]["missing_path_options"] == 1


def test_forward_markout_rejects_path_lineage_mismatch() -> None:
    with pytest.raises(
        ProspectiveCapacityReflowForwardMarkoutError,
        match="forward path lineage mismatch",
    ):
        prospective_capacity_reflow_forward_markout_summary(
            _fill_payload(),
            (_path(direction="short"),),
            horizons_ms=(300_000,),
        )
