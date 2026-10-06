from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookEvidence,
    CapacityReleaseBookRegistration,
    PendingCapacityReleaseExecution,
    paper_execution_config_payload,
)
from cocomelon.research.correlation_holder_release_execution import (
    CorrelationHolderReleaseExecutionError,
    correlation_holder_release_execution_summary,
)

BTC = MarketId("", "BTC")


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=BTC,
        sz_decimals=3,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _book(
    *,
    received_ms: int,
    bid_size: str = "2",
    bid_px: str = "100.9",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=BTC,
        exchange_time_ms=received_ms - 1,
        receive_time=datetime.fromtimestamp(
            received_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:BTC:{received_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal(bid_px),
                    "sz": Decimal(bid_size),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal("101.1"),
                    "sz": Decimal("10"),
                    "n": 1,
                },
            ),
        },
    )


def _position(*, quantity: str = "1") -> PaperPosition:
    return PaperPosition(
        market=BTC,
        side=PositionSide.LONG,
        quantity=Decimal(quantity),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id="holder-plan-btc",
        opened_at_ms=500,
        updated_at_ms=1_000,
        initial_risk_decision_id="risk-holder-btc",
        correlation_bucket="majors",
        planned_risk=Decimal("20"),
        cumulative_realized_gross_pnl=Decimal("0.05"),
        cumulative_fees=Decimal("0.1"),
        cumulative_funding=Decimal("0.02"),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )


def _evidence(
    *,
    quantity: str = "1",
    execution_bid_size: str = "2",
    execution_received_ms: int = 1_360,
    config: PaperExecutionConfig | None = None,
    bind_config: bool = True,
) -> CapacityReleaseBookEvidence:
    registration = CapacityReleaseBookRegistration(
        opportunity_id="opportunity-sol-short-1",
        opportunity_timestamp_ms=1_000,
        opportunity_market="SOL",
        opportunity_direction="short",
        release_market="BTC",
        release_direction="long",
        release_correlation_bucket="majors",
        strategy_decision_id="strategy-sol",
        risk_decision_id="risk-sol",
    )
    instrument = _instrument()
    resolved_config = PaperExecutionConfig() if config is None else config
    pending = PendingCapacityReleaseExecution(
        registration=registration,
        release_position=_position(quantity=quantity),
        plan_observed_at_ms=1_100,
        plan_reference_price=Decimal("101"),
        plan_book_event=_book(received_ms=1_100),
        plan_instrument=instrument,
        execution_config=(
            paper_execution_config_payload(resolved_config)
            if bind_config
            else None
        ),
    )
    return CapacityReleaseBookEvidence(
        pending=pending,
        execution_observed_at_ms=execution_received_ms,
        execution_book_event=_book(
            received_ms=execution_received_ms,
            bid_size=execution_bid_size,
        ),
        execution_instrument=instrument,
    )


def test_holder_release_full_close_exposes_exact_terminal_contribution() -> None:
    result = correlation_holder_release_execution_summary(
        (_evidence(),),
        PaperExecutionConfig(),
    )

    assert result["captured_release_books"] == 1
    assert result["planned_release_exits"] == 1
    assert result["full_release_fills"] == 1
    assert result["partial_release_fills"] == 0
    assert result["no_release_fills"] == 0
    assert result["gross_realized_pnl"] == "0.9"
    assert result["close_fees"] == "0.045405"
    assert result["fully_closed_terminal_contribution"] == "0.824595"
    assert result["unclosed_quantity"] == "0.000"
    assert result["full_close_terminal_contribution_by_plan"] == {
        "holder-plan-btc": "0.824595"
    }
    rows = result["release_results"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict)
    assert row["opportunity_id"] == "opportunity-sol-short-1"
    assert row["release_market"] == "BTC"
    assert row["release_opening_plan_id"] == "holder-plan-btc"
    assert row["execution_result"] == "full"
    assert row["filled_quantity"] == "1.000"
    assert row["average_exit_price"] == "100.9"
    assert row["gross_realized_pnl"] == "0.9"
    assert row["close_fee"] == "0.045405"
    assert row["incremental_release_net_pnl"] == "0.854595"
    assert row["full_close_terminal_contribution"] == "0.824595"
    assert row["complete_close"] is True
    assert result["holder_release_execution_modeled"] is True
    assert result["newcomer_entry_modeled"] is False
    assert result["replacement_trade_modeled"] is False
    assert result["execution_authority"] is False
    assert result["changes_positions"] is False


def test_holder_release_partial_fill_never_claims_terminal_contribution() -> None:
    result = correlation_holder_release_execution_summary(
        (
            _evidence(
                quantity="3",
                execution_bid_size="1",
            ),
        ),
        PaperExecutionConfig(),
    )

    assert result["full_release_fills"] == 0
    assert result["partial_release_fills"] == 1
    assert result["unclosed_quantity"] == "2.000"
    assert result["full_close_terminal_contribution_by_plan"] == {}
    rows = result["release_results"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    assert row["execution_result"] == "partial"
    assert row["filled_quantity"] == "1.000"
    assert row["unfilled_quantity"] == "2.000"
    assert row["full_close_terminal_contribution"] is None
    assert row["complete_close"] is False


def test_holder_release_no_fill_is_visible_without_faking_close() -> None:
    config = PaperExecutionConfig(max_ioc_slippage_bps=Decimal("1"))
    result = correlation_holder_release_execution_summary(
        (
            _evidence(
                execution_bid_size="2",
                execution_received_ms=1_360,
                config=config,
            ),
        ),
        config,
    )

    assert result["full_release_fills"] == 0
    assert result["partial_release_fills"] == 0
    assert result["no_release_fills"] == 1
    assert result["execution_rejected_release_exits"] == 0
    rows = result["release_results"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    assert row["execution_result"] == "no_fill"
    assert row["filled_quantity"] == "0.000"
    assert row["full_close_terminal_contribution"] is None
    assert row["complete_close"] is False


def test_holder_release_refuses_latency_config_that_evidence_cannot_support() -> None:
    config = PaperExecutionConfig(latency_ms=500)
    with pytest.raises(
        CorrelationHolderReleaseExecutionError,
        match="predates configured paper latency",
    ):
        correlation_holder_release_execution_summary(
            (_evidence(config=config),),
            config,
        )


def test_holder_release_refuses_duplicate_registration_evidence() -> None:
    item = _evidence()

    with pytest.raises(
        CorrelationHolderReleaseExecutionError,
        match="duplicate capacity release execution evidence",
    ):
        correlation_holder_release_execution_summary(
            (item, item),
            PaperExecutionConfig(),
        )



def test_holder_release_skips_legacy_unbound_execution_config() -> None:
    result = correlation_holder_release_execution_summary(
        (_evidence(bind_config=False),),
        PaperExecutionConfig(),
    )

    assert result["captured_release_books"] == 1
    assert result["exact_execution_config_records"] == 0
    assert result["unbound_execution_config_records"] == 1
    assert result["execution_config_mismatch_records"] == 0
    assert result["planned_release_exits"] == 0
    assert result["full_release_fills"] == 0
    assert result["full_close_terminal_contribution_by_plan"] == {}
    rows = result["release_results"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    assert row["status"] == "unbound_execution_config"
    assert row["execution_result"] is None


def test_holder_release_skips_execution_config_mismatch() -> None:
    result = correlation_holder_release_execution_summary(
        (_evidence(),),
        PaperExecutionConfig(max_ioc_slippage_bps=Decimal("20")),
    )

    assert result["exact_execution_config_records"] == 0
    assert result["unbound_execution_config_records"] == 0
    assert result["execution_config_mismatch_records"] == 1
    assert result["planned_release_exits"] == 0
    rows = result["release_results"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    assert row["status"] == "execution_config_mismatch"
