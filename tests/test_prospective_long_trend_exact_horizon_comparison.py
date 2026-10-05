from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.prospective_long_trend_exact_horizon_comparison import (
    COMMON_FROZEN_STARTED_AT_MS,
    FIFTEEN_MINUTE_HORIZON_MS,
    FIVE_MINUTE_HORIZON_MS,
    ProspectiveLongTrendExactHorizonComparisonError,
    prospective_long_trend_exact_horizon_comparison,
)

DIGEST = "a" * 64


def _row(
    index: int,
    *,
    pnl: str | None,
    market: str | None = None,
    return_fraction: str | None = None,
) -> dict[str, object]:
    normalized_return = (
        None
        if pnl is None
        else return_fraction
        if return_fraction is not None
        else str(Decimal(pnl) / Decimal("100"))
    )
    return {
        "opportunity_id": f"opp-{index:02d}",
        "timestamp_ms": COMMON_FROZEN_STARTED_AT_MS + index * 60_000,
        "market": market or f"M{index % 4}",
        "direction": "long",
        "exact_realized_pnl": pnl,
        "exact_realized_return_fraction": normalized_return,
    }


def _summary(
    horizon_ms: int,
    rows: list[dict[str, object]],
    *,
    started_at_ms: int = COMMON_FROZEN_STARTED_AT_MS,
    digest: str = DIGEST,
) -> dict[str, object]:
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "discovery_cohort_reused_for_validation": False,
        "cross_horizon_selection_frozen": True,
        "started_at_ms": started_at_ms,
        "exit_horizon_ms": horizon_ms,
        "execution_config_sha256": digest,
        "option_results": rows,
    }


def test_common_future_sample_can_robustly_prefer_five_minutes() -> None:
    five_rows = [_row(index, pnl="2") for index in range(12)]
    fifteen_rows = [_row(index, pnl="1") for index in range(12)]

    result = prospective_long_trend_exact_horizon_comparison(
        _summary(FIVE_MINUTE_HORIZON_MS, five_rows),
        _summary(FIFTEEN_MINUTE_HORIZON_MS, fifteen_rows),
    )

    assert result["paired_exact_options"] == 12
    assert result["market_count"] == 4
    assert result["minimum_sample_met"] is True
    assert result["five_minute_total_pnl_on_paired"] == "24"
    assert result["fifteen_minute_total_pnl_on_paired"] == "12"
    assert result["total_pnl_delta_5m_minus_15m"] == "12"
    assert Decimal(result["leave_one_trade_min_delta"]) > 0
    assert Decimal(result["leave_one_market_min_delta"]) > 0
    assert Decimal(result["chronological_first_half_delta"]) > 0
    assert Decimal(result["chronological_second_half_delta"]) > 0
    assert result["five_minute_robustly_better"] is True
    assert result["fifteen_minute_robustly_better"] is False
    assert result["preferred_horizon"] == "5m"
    assert result["total_return_fraction_delta_5m_minus_15m"] == "0.12"
    assert (
        Decimal(result["size_normalized_leave_one_trade_min_delta"])
        > 0
    )
    assert (
        Decimal(result["size_normalized_leave_one_market_min_delta"])
        > 0
    )
    assert result["five_minute_size_normalized_robustly_better"] is True
    assert result["fifteen_minute_size_normalized_robustly_better"] is False
    assert result["size_normalized_preferred_horizon"] == "5m"
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["changes_execution"] is False
    assert result["changes_risk_limits"] is False
    assert result["changes_candidate_readiness"] is False


def test_common_future_sample_can_robustly_prefer_fifteen_minutes() -> None:
    five_rows = [_row(index, pnl="-1") for index in range(12)]
    fifteen_rows = [_row(index, pnl="2") for index in range(12)]

    result = prospective_long_trend_exact_horizon_comparison(
        _summary(FIVE_MINUTE_HORIZON_MS, five_rows),
        _summary(FIFTEEN_MINUTE_HORIZON_MS, fifteen_rows),
    )

    assert result["total_pnl_delta_5m_minus_15m"] == "-36"
    assert Decimal(result["leave_one_trade_max_delta"]) < 0
    assert Decimal(result["leave_one_market_max_delta"]) < 0
    assert Decimal(result["chronological_first_half_delta"]) < 0
    assert Decimal(result["chronological_second_half_delta"]) < 0
    assert result["five_minute_robustly_better"] is False
    assert result["fifteen_minute_robustly_better"] is True
    assert result["preferred_horizon"] == "15m"
    assert result["five_minute_size_normalized_robustly_better"] is False
    assert result["fifteen_minute_size_normalized_robustly_better"] is True
    assert result["size_normalized_preferred_horizon"] == "15m"


def test_size_normalized_readout_can_disagree_with_dollar_weighting() -> None:
    five_rows = [
        _row(
            index,
            pnl=("20" if index == 0 else "1"),
            return_fraction=("0.01" if index == 0 else "0.02"),
        )
        for index in range(12)
    ]
    fifteen_rows = [
        _row(
            index,
            pnl=("0" if index == 0 else "2"),
            return_fraction=("0.00" if index == 0 else "0.01"),
        )
        for index in range(12)
    ]

    result = prospective_long_trend_exact_horizon_comparison(
        _summary(FIVE_MINUTE_HORIZON_MS, five_rows),
        _summary(FIFTEEN_MINUTE_HORIZON_MS, fifteen_rows),
    )

    assert result["total_pnl_delta_5m_minus_15m"] == "9"
    assert result["preferred_horizon"] == "none"
    assert result["total_return_fraction_delta_5m_minus_15m"] == "0.12"
    assert result["size_normalized_preferred_horizon"] == "5m"


def test_unpaired_exact_rows_receive_no_comparison_credit() -> None:
    five_rows = [
        _row(0, pnl="2"),
        _row(1, pnl="3"),
        _row(2, pnl=None),
    ]
    fifteen_rows = [
        _row(0, pnl="1"),
        _row(1, pnl=None),
        _row(2, pnl="4"),
    ]

    result = prospective_long_trend_exact_horizon_comparison(
        _summary(FIVE_MINUTE_HORIZON_MS, five_rows),
        _summary(FIFTEEN_MINUTE_HORIZON_MS, fifteen_rows),
    )

    assert result["five_minute_exact_options"] == 2
    assert result["fifteen_minute_exact_options"] == 2
    assert result["paired_exact_options"] == 1
    assert result["five_minute_only_exact_options"] == 1
    assert result["fifteen_minute_only_exact_options"] == 1
    assert result["minimum_sample_met"] is False
    assert result["preferred_horizon"] == "none"
    assert result["paired_results"] == [
        {
            "opportunity_id": "opp-00",
            "timestamp_ms": COMMON_FROZEN_STARTED_AT_MS,
            "market": "M0",
            "direction": "long",
            "five_minute_exact_realized_pnl": "2",
            "fifteen_minute_exact_realized_pnl": "1",
            "pnl_delta_5m_minus_15m": "1",
        }
    ]


def test_comparison_rejects_mismatched_freeze() -> None:
    with pytest.raises(
        ProspectiveLongTrendExactHorizonComparisonError,
        match="freeze",
    ):
        prospective_long_trend_exact_horizon_comparison(
            _summary(
                FIVE_MINUTE_HORIZON_MS,
                [_row(0, pnl="1")],
                started_at_ms=COMMON_FROZEN_STARTED_AT_MS - 1,
            ),
            _summary(
                FIFTEEN_MINUTE_HORIZON_MS,
                [_row(0, pnl="1")],
            ),
        )


def test_comparison_rejects_execution_config_mismatch() -> None:
    with pytest.raises(
        ProspectiveLongTrendExactHorizonComparisonError,
        match="different execution configs",
    ):
        prospective_long_trend_exact_horizon_comparison(
            _summary(
                FIVE_MINUTE_HORIZON_MS,
                [_row(0, pnl="1")],
            ),
            _summary(
                FIFTEEN_MINUTE_HORIZON_MS,
                [_row(0, pnl="1")],
                digest="b" * 64,
            ),
        )


def test_comparison_rejects_authority_drift() -> None:
    five = _summary(FIVE_MINUTE_HORIZON_MS, [_row(0, pnl="1")])
    five["execution_authority"] = True

    with pytest.raises(
        ProspectiveLongTrendExactHorizonComparisonError,
        match="authority drift",
    ):
        prospective_long_trend_exact_horizon_comparison(
            five,
            _summary(
                FIFTEEN_MINUTE_HORIZON_MS,
                [_row(0, pnl="1")],
            ),
        )
