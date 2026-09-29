from __future__ import annotations

from cocomelon.research.prospective_replacement_exit_robustness import (
    MIN_EXACT_OPTIONS_FOR_REVIEW,
    prospective_replacement_exit_robustness,
)


def _policy(
    rows: tuple[tuple[str, str, int, str | None], ...],
) -> dict[str, object]:
    option_results = []
    for suffix, market, timestamp_ms, pnl in rows:
        option_results.append(
            {
                "option_id": f"option-{suffix}",
                "opportunity_id": f"opp-{suffix}",
                "opportunity_timestamp_ms": timestamp_ms,
                "opportunity_market": market,
                "exact_realized_pnl": pnl,
                "incomplete_reason": (
                    None if pnl is not None else "missing_exit_result"
                ),
            }
        )
    exact = sum(1 for *_, pnl in rows if pnl is not None)
    return {
        "enabled": True,
        "candidate_id": "prospective-replacement-5m-real-l2-exit-v1",
        "started_at_ms": 1_000,
        "exit_horizon_ms": 300_000,
        "discovery_cohort_reused_for_validation": False,
        "cross_horizon_selection_frozen": True,
        "prospective_options": len(rows),
        "exact_realized_pnl_options": exact,
        "incomplete_options": len(rows) - exact,
        "option_results": option_results,
    }


def test_replacement_exit_robustness_reports_concentration() -> None:
    result = prospective_replacement_exit_robustness(
        _policy(
            (
                ("a", "SOL", 1_100, "5"),
                ("b", "ETH", 1_200, "4"),
                ("c", "BTC", 1_300, "-2"),
                ("d", "BTC", 1_400, "1"),
                ("e", "ENA", 1_500, None),
            )
        )
    )

    assert result["prospective_options"] == 5
    assert result["exact_options"] == 4
    assert result["incomplete_options"] == 1
    assert result["exact_coverage_fraction"] == "0.8"
    assert result["total_exact_realized_pnl"] == "8"
    assert result["gross_profit"] == "10"
    assert result["gross_loss_abs"] == "2"
    assert result["profit_factor"] == "5"
    assert result["largest_abs_option_pnl"] == "5"
    assert result["largest_abs_option_market"] == "SOL"
    assert result["largest_abs_option_share"] == "0.4166666666666666666666666667"
    assert result["leave_one_option_out_min_pnl"] == "3"
    assert result["positive_after_any_single_option_removed"] is True
    assert result["largest_abs_market"] == "SOL"
    assert result["largest_abs_market_pnl"] == "5"
    assert result["leave_one_market_out_min_pnl"] == "3"
    assert result["positive_after_any_single_market_removed"] is True
    assert result["minimum_exact_options_for_review"] == (
        MIN_EXACT_OPTIONS_FOR_REVIEW
    )
    assert result["sample_ready_for_review"] is False
    assert result["changes_candidate_rule"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_replacement_exit_robustness_detects_market_dependency() -> None:
    result = prospective_replacement_exit_robustness(
        _policy(
            (
                ("a", "SOL", 1_100, "8"),
                ("b", "SOL", 1_200, "5"),
                ("c", "ETH", 1_300, "-4"),
            )
        )
    )

    assert result["total_exact_realized_pnl"] == "9"
    assert result["largest_abs_market"] == "SOL"
    assert result["largest_abs_market_pnl"] == "13"
    assert result["leave_one_market_out_min_pnl"] == "-4"
    assert result["positive_after_any_single_market_removed"] is False


def test_replacement_exit_robustness_reports_four_full_time_blocks() -> None:
    rows = tuple(
        (
            str(index),
            f"M{index % 4}",
            10_000 + index * 1_000,
            "1",
        )
        for index in range(20)
    )
    result = prospective_replacement_exit_robustness(_policy(rows))

    temporal = result["temporal"]
    assert isinstance(temporal, dict)
    assert temporal["full_blocks"] == 4
    assert temporal["positive_full_blocks"] == 4
    assert temporal["all_full_blocks_positive"] is True
    blocks = temporal["chronological_blocks"]
    assert isinstance(blocks, list)
    assert [block["options"] for block in blocks] == [5, 5, 5, 5]
    assert [block["exact_realized_pnl"] for block in blocks] == [
        "5",
        "5",
        "5",
        "5",
    ]
