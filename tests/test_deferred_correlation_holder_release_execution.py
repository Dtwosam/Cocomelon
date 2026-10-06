from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookRegistration,
    CapacityReleaseBookStore,
)
from cocomelon.research.deferred_correlation_holder_release_execution import (
    write_deferred_correlation_holder_release_execution,
)

BTC = MarketId("", "BTC")


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=BTC,
        sz_decimals=3,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="fixture",
    )


def _book(received_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=BTC,
        exchange_time_ms=received_ms - 1,
        receive_time=datetime.fromtimestamp(received_ms / 1000, tz=UTC),
        schema_version=1,
        source="fixture",
        event_key=f"book-btc-{received_ms}",
        payload={
            "bids": (
                {"px": Decimal("100.9"), "sz": Decimal("2"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("101.1"), "sz": Decimal("2"), "n": 1},
            ),
        },
    )


def _position() -> PaperPosition:
    return PaperPosition(
        market=BTC,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id="holder-plan",
        opened_at_ms=500,
        updated_at_ms=1_000,
        initial_risk_decision_id="holder-risk",
        correlation_bucket="majors",
        cumulative_fees=Decimal("0.1"),
        cumulative_funding=Decimal("0.02"),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )


def _registration() -> CapacityReleaseBookRegistration:
    return CapacityReleaseBookRegistration(
        opportunity_id="opportunity-sol",
        opportunity_timestamp_ms=1_000,
        opportunity_market="SOL",
        opportunity_direction="short",
        release_market="BTC",
        release_direction="long",
        release_correlation_bucket="majors",
        strategy_decision_id="strategy-sol",
        risk_decision_id="risk-sol",
    )


def test_deferred_holder_release_rebuild_uses_bound_record_config(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    store = CapacityReleaseBookStore(
        root / "capacity-release-books",
        capture_started_at_ms=900,
        latency_ms=250,
        max_book_age_ms=1_000,
        execution_config=PaperExecutionConfig(),
    )
    store.register(_registration())
    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(1_100),
            reference_price=Decimal("101"),
            now_ms=1_100,
        )
        == 0
    )
    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(1_360),
            reference_price=Decimal("101"),
            now_ms=1_360,
        )
        == 1
    )

    output = write_deferred_correlation_holder_release_execution(root)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["captured_release_books"] == 1
    assert payload["exact_execution_config_records"] == 1
    assert payload["unbound_execution_config_records"] == 0
    assert payload["full_release_fills"] == 1
    assert payload["full_close_terminal_contribution_by_plan"] == {
        "holder-plan": "0.774595"
    }
    assert payload["execution_config_authority"] == "bound_per_record"
    assert payload["deferred_post_handoff_rebuild"] is True
    assert payload["execution_authority"] is False
    assert payload["strategy_authority"] is False


def test_deferred_holder_release_rebuild_does_not_reprice_legacy_records(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    store = CapacityReleaseBookStore(
        root / "capacity-release-books",
        capture_started_at_ms=900,
        latency_ms=250,
        max_book_age_ms=1_000,
    )
    store.register(_registration())
    store.capture(
        positions=(_position(),),
        instrument=_instrument(),
        book=_book(1_100),
        reference_price=Decimal("101"),
        now_ms=1_100,
    )
    store.capture(
        positions=(_position(),),
        instrument=_instrument(),
        book=_book(1_360),
        reference_price=Decimal("101"),
        now_ms=1_360,
    )

    output = write_deferred_correlation_holder_release_execution(root)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["captured_release_books"] == 1
    assert payload["exact_execution_config_records"] == 0
    assert payload["unbound_execution_config_records"] == 1
    assert payload["full_release_fills"] == 0
    assert payload["full_close_terminal_contribution_by_plan"] == {}
