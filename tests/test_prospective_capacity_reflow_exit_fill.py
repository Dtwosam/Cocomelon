from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.prospective_capacity_reflow_exit_fill import (
    ProspectiveCapacityReflowExitFillError,
    prospective_capacity_reflow_exit_fill_summary,
)

MARKET = MarketId(dex="", coin="SOL")


def _fill_feasibility() -> dict[str, object]:
    return {
        "replacement_entry_fills_modeled": True,
        "execution_config": {
            "config_version": "phase7-v1",
            "latency_ms": 250,
            "max_book_age_ms": 1000,
            "max_ioc_slippage_bps": "25",
            "taker_fee_rate": "0.00045",
            "fee_schedule_id": "hyperliquid-native-base-2026-08-23",
        },
        "fillable_option_ids": ["opp-1:release-plan-1"],
        "option_results": [
            {
                "option_id": "opp-1:release-plan-1",
                "opportunity_id": "opp-1",
                "opportunity_timestamp_ms": 10_000,
                "opportunity_market": "SOL",
                "opportunity_direction": "long",
                "release_market": "BTC",
                "release_opening_plan_id": "release-plan-1",
                "release_block_reason": "long_trend",
                "counterfactual_equity_delta": "1",
                "risk_approved": True,
                "risk_reason_codes": ["APPROVED"],
                "planning_approved": True,
                "planning_rejection": None,
                "execution_result": "full",
                "attempt_id": "entry-attempt-1",
                "entry_attempt_timestamp_ms": 10_000,
                "opening_plan_id": "replacement-open-plan-1",
                "opening_risk_decision_id": "replacement-risk-1",
                "opening_strategy_decision_id": "replacement-strategy-1",
                "opening_stop_price": "95",
                "correlation_bucket": "majors",
                "venue_max_leverage": "5",
                "requested_quantity": "2",
                "filled_quantity": "2",
                "average_fill_price": "100",
                "gross_fill_notional": "200",
                "taker_fee": "0.2",
                "unfilled_quantity": "0",
            }
        ],
    }


def _exit_book(
    *,
    direction: str = "long",
) -> OpeningOpportunityExitBookEvidence:
    book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=310_040,
        receive_time=datetime.fromtimestamp(310.05, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-info",
        event_key="l2Book:SOL:310040:fixture",
        payload={
            "bids": (
                {"px": Decimal("104"), "sz": Decimal("1"), "n": 1},
                {"px": Decimal("103"), "sz": Decimal("5"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("105"), "sz": Decimal("5"), "n": 1},
            ),
        },
    )
    instrument = InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=0,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=310_000,
        metadata_source="hyperliquid-mainnet-info",
    )
    return OpeningOpportunityExitBookEvidence(
        opportunity_id="opp-1",
        market="SOL",
        direction=direction,
        opportunity_timestamp_ms=10_000,
        horizon_ms=300_000,
        target_at_ms=310_000,
        observed_at_ms=310_050,
        observation_lag_ms=50,
        book_event=book,
        instrument=instrument,
    )


def test_replacement_exit_uses_reduce_only_ioc_and_real_l2_depth() -> None:
    result = prospective_capacity_reflow_exit_fill_summary(
        _fill_feasibility(),
        (_exit_book(),),
        PaperExecutionConfig(),
        horizons_ms=(300_000,),
    )

    assert result["fillable_options"] == 1
    assert result["exit_book_records"] == 1
    assert result["cross_horizon_economics_aggregated"] is False
    assert result["replacement_entry_fills_modeled"] is True
    assert result["replacement_exit_fills_modeled"] is True
    assert result["funding_modeled"] is False
    assert result["replacement_trade_pnl_complete"] is False
    assert result["realized_pnl_claimed"] is False

    option = result["option_exits"][0]
    exit_result = option["exits"]["300000"]
    assert exit_result["status"] == "simulated"
    assert exit_result["execution_result"] == "partial"
    assert exit_result["requested_quantity"] == "2"
    assert exit_result["filled_quantity"] == "1"
    assert exit_result["unfilled_quantity"] == "1"
    assert exit_result["average_exit_price"] == "104"
    assert exit_result["gross_realized_pnl"] == "4"
    assert exit_result["allocated_entry_fee"] == "0.1"
    assert exit_result["exit_fee"] == "0.04680"
    assert exit_result["entry_exit_fee_adjusted_pnl"] == "3.85320"
    assert exit_result["complete_close"] is False
    assert exit_result["attempt_timestamp_ms"] == 310_300

    horizon = result["by_horizon"]["300000"]
    assert horizon["captured_exit_books"] == 1
    assert horizon["partial_exit_fills"] == 1
    assert horizon["full_exit_fills"] == 0
    assert horizon["entry_exit_fee_adjusted_pnl"] == "3.85320"
    assert horizon["unclosed_quantity"] == "1"
    assert result["by_execution_result"] == {"partial": 1}


def test_replacement_exit_reports_missing_book_without_inventing_exit() -> None:
    result = prospective_capacity_reflow_exit_fill_summary(
        _fill_feasibility(),
        (),
        PaperExecutionConfig(),
        horizons_ms=(300_000,),
    )

    option = result["option_exits"][0]
    assert option["exits"]["300000"] == {
        "status": "missing_exit_book",
        "horizon_ms": 300_000,
    }
    horizon = result["by_horizon"]["300000"]
    assert horizon["captured_exit_books"] == 0
    assert horizon["missing_exit_books"] == 1
    assert result["by_execution_result"] == {}


def test_replacement_exit_rejects_execution_config_drift() -> None:
    with pytest.raises(
        ProspectiveCapacityReflowExitFillError,
        match="execution config drift",
    ):
        prospective_capacity_reflow_exit_fill_summary(
            _fill_feasibility(),
            (_exit_book(),),
            PaperExecutionConfig(max_ioc_slippage_bps=Decimal("20")),
            horizons_ms=(300_000,),
        )


def test_replacement_exit_rejects_book_lineage_mismatch() -> None:
    with pytest.raises(
        ProspectiveCapacityReflowExitFillError,
        match="exit book lineage mismatch",
    ):
        prospective_capacity_reflow_exit_fill_summary(
            _fill_feasibility(),
            (_exit_book(direction="short"),),
            PaperExecutionConfig(),
            horizons_ms=(300_000,),
        )


def test_replacement_exit_full_ioc_can_still_leave_rounding_residual() -> None:
    fill_feasibility = _fill_feasibility()
    option_results = fill_feasibility["option_results"]
    assert isinstance(option_results, list)
    option = option_results[0]
    assert isinstance(option, dict)
    option["requested_quantity"] = "2.5"
    option["filled_quantity"] = "2.5"
    option["gross_fill_notional"] = "250.0"
    option["taker_fee"] = "0.25"

    evidence = _exit_book()
    deep_book = replace(
        evidence.book_event,
        payload={
            "bids": (
                {"px": Decimal("104"), "sz": Decimal("10"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("105"), "sz": Decimal("10"), "n": 1},
            ),
        },
    )
    evidence = replace(evidence, book_event=deep_book)

    result = prospective_capacity_reflow_exit_fill_summary(
        fill_feasibility,
        (evidence,),
        PaperExecutionConfig(),
        horizons_ms=(300_000,),
    )

    exit_result = result["option_exits"][0]["exits"]["300000"]
    assert exit_result["execution_result"] == "full"
    assert exit_result["requested_quantity"] == "2"
    assert exit_result["filled_quantity"] == "2"
    assert exit_result["complete_close"] is False
    assert result["by_horizon"]["300000"]["full_exit_fills"] == 0
    assert result["by_horizon"]["300000"]["partial_exit_fills"] == 1
    assert result["by_horizon"]["300000"]["unclosed_quantity"] == "0.5"
