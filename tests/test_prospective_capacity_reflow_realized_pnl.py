from __future__ import annotations

from cocomelon.research.prospective_capacity_reflow_realized_pnl import (
    prospective_capacity_reflow_realized_pnl_summary,
)


def _exit_fill_payload() -> dict[str, object]:
    return {
        "replacement_entry_fills_modeled": True,
        "replacement_exit_fills_modeled": True,
        "cross_horizon_economics_aggregated": False,
        "horizons_ms": [300_000, 3_600_000],
        "option_exits": [
            {
                "option_id": "option-1",
                "opportunity_id": "opp-1",
                "entry_attempt_timestamp_ms": 10_000,
                "entry_price": "100",
                "entry_quantity": "2",
                "entry_fee": "0.2",
                "exits": {
                    "300000": {
                        "status": "simulated",
                        "attempt_timestamp_ms": 310_300,
                        "execution_result": "full",
                        "complete_close": True,
                        "entry_exit_fee_adjusted_pnl": "3.80",
                        "funding_pnl": None,
                    },
                    "3600000": {
                        "status": "simulated",
                        "attempt_timestamp_ms": 3_610_300,
                        "execution_result": "full",
                        "complete_close": True,
                        "entry_exit_fee_adjusted_pnl": "-2.25",
                        "funding_pnl": None,
                    },
                },
            }
        ],
    }


def test_realized_pnl_is_exact_only_when_no_funding_boundary_is_crossed() -> None:
    result = prospective_capacity_reflow_realized_pnl_summary(
        _exit_fill_payload()
    )

    five_minute = result["by_horizon"]["300000"]
    assert five_minute["complete_closes"] == 1
    assert five_minute["zero_funding_boundary_closes"] == 1
    assert five_minute["funding_evidence_required_closes"] == 0
    assert five_minute["exact_realized_pnl_options"] == 1
    assert five_minute["exact_realized_pnl"] == "3.80"

    one_hour = result["by_horizon"]["3600000"]
    assert one_hour["complete_closes"] == 1
    assert one_hour["zero_funding_boundary_closes"] == 0
    assert one_hour["funding_evidence_required_closes"] == 1
    assert one_hour["exact_realized_pnl_options"] == 0
    assert one_hour["exact_realized_pnl"] == "0"

    option = result["option_results"][0]
    assert option["exits"]["300000"]["funding_boundary_count"] == 0
    assert option["exits"]["300000"]["exact_realized_pnl"] == "3.80"
    assert option["exits"]["3600000"]["funding_boundary_count"] == 1
    assert option["exits"]["3600000"]["exact_realized_pnl"] is None
    assert option["exits"]["3600000"]["incomplete_reason"] == (
        "funding_evidence_required"
    )

    assert result["exact_realized_pnl_available"] is True
    assert result["cross_horizon_economics_aggregated"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_partial_close_never_claims_complete_trade_pnl() -> None:
    payload = _exit_fill_payload()
    option = payload["option_exits"][0]
    assert isinstance(option, dict)
    exits = option["exits"]
    assert isinstance(exits, dict)
    five = exits["300000"]
    assert isinstance(five, dict)
    five["complete_close"] = False
    five["execution_result"] = "partial"
    five["entry_exit_fee_adjusted_pnl"] = "1.25"

    result = prospective_capacity_reflow_realized_pnl_summary(payload)

    five_minute = result["by_horizon"]["300000"]
    assert five_minute["complete_closes"] == 0
    assert five_minute["incomplete_or_missing_exits"] == 1
    assert five_minute["exact_realized_pnl_options"] == 0
    classified = result["option_results"][0]["exits"]["300000"]
    assert classified["exact_realized_pnl"] is None
    assert classified["incomplete_reason"] == "position_not_fully_closed"


def test_close_exactly_on_funding_boundary_requires_funding_evidence() -> None:
    payload = _exit_fill_payload()
    option = payload["option_exits"][0]
    assert isinstance(option, dict)
    option["entry_attempt_timestamp_ms"] = 3_300_000
    exits = option["exits"]
    assert isinstance(exits, dict)
    five = exits["300000"]
    assert isinstance(five, dict)
    five["attempt_timestamp_ms"] = 3_600_000

    result = prospective_capacity_reflow_realized_pnl_summary(payload)

    classified = result["option_results"][0]["exits"]["300000"]
    assert classified["funding_boundary_count"] == 1
    assert classified["exact_realized_pnl"] is None
    assert classified["incomplete_reason"] == "funding_evidence_required"


def test_entry_exactly_on_boundary_does_not_owe_that_boundary() -> None:
    payload = _exit_fill_payload()
    option = payload["option_exits"][0]
    assert isinstance(option, dict)
    option["entry_attempt_timestamp_ms"] = 3_600_000
    exits = option["exits"]
    assert isinstance(exits, dict)
    five = exits["300000"]
    assert isinstance(five, dict)
    five["attempt_timestamp_ms"] = 3_900_000

    result = prospective_capacity_reflow_realized_pnl_summary(payload)

    classified = result["option_results"][0]["exits"]["300000"]
    assert classified["funding_boundary_count"] == 0
    assert classified["exact_realized_pnl"] == "3.80"
