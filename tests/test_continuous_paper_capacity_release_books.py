from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.continuous_paper_capacity_release_books import (
    CapacityReleaseBookCapture,
    CapacityReleaseBookRegistration,
    CapacityReleaseBookStore,
)

BTC = MarketId("", "BTC")
SOL = MarketId("", "SOL")


def _position() -> PaperPosition:
    return PaperPosition(
        market=BTC,
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id="holder-plan-btc",
        opened_at_ms=500,
        updated_at_ms=900,
        correlation_bucket="majors",
        planned_risk=Decimal("20"),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("101"),
    )


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
    exchange_ms: int | None = None,
) -> StreamEvent:
    resolved_exchange = (
        received_ms - 10 if exchange_ms is None else exchange_ms
    )
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=BTC,
        exchange_time_ms=resolved_exchange,
        receive_time=datetime.fromtimestamp(
            received_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:BTC:{resolved_exchange}:{received_ms}",
        payload={
            "bids": (
                {
                    "px": Decimal("100.9"),
                    "sz": Decimal("2"),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal("101.1"),
                    "sz": Decimal("3"),
                    "n": 2,
                },
            ),
        },
    )


def _registration() -> CapacityReleaseBookRegistration:
    return CapacityReleaseBookRegistration(
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


def _store(root: Path) -> CapacityReleaseBookStore:
    return CapacityReleaseBookStore(
        root,
        capture_started_at_ms=900,
        latency_ms=250,
        max_book_age_ms=1_000,
    )


def test_release_books_stage_plan_then_capture_latency_eligible_execution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "capacity-release-books"
    store = _store(root)
    registration = _registration()

    assert store.register(registration) is True
    assert store.register(registration) is False
    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_100),
            reference_price=Decimal("101"),
            now_ms=1_100,
        )
        == 0
    )
    pending = store.iter_pending()
    assert len(pending) == 1
    assert pending[0].registration == registration
    assert pending[0].release_opening_plan_id == "holder-plan-btc"
    assert pending[0].plan_observed_at_ms == 1_100
    assert pending[0].plan_reference_price == Decimal("101")
    assert store.iter_records() == ()

    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_300),
            reference_price=Decimal("101"),
            now_ms=1_300,
        )
        == 0
    )
    assert len(store.iter_pending()) == 1

    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_360),
            reference_price=Decimal("101"),
            now_ms=1_360,
        )
        == 1
    )
    records = store.iter_records()
    assert len(records) == 1
    evidence = records[0]
    assert evidence.registration == registration
    assert evidence.release_opening_plan_id == "holder-plan-btc"
    assert evidence.release_position == _position()
    assert evidence.pending.plan_book_event == _book(received_ms=1_100)
    assert evidence.pending.plan_instrument == _instrument()
    assert evidence.execution_book_event == _book(received_ms=1_360)
    assert evidence.execution_instrument == _instrument()
    assert store.iter_pending() == ()


def test_release_plan_survives_restart_before_execution_book(
    tmp_path: Path,
) -> None:
    root = tmp_path / "capacity-release-books"
    first = _store(root)
    first.register(_registration())
    first.capture(
        positions=(_position(),),
        instrument=_instrument(),
        book=_book(received_ms=1_100),
        reference_price=Decimal("101"),
        now_ms=1_100,
    )

    restored = CapacityReleaseBookStore(
        root,
        capture_started_at_ms=50_000,
        latency_ms=250,
        max_book_age_ms=1_000,
    )
    assert restored.capture_started_at_ms == 900
    assert len(restored.iter_pending()) == 1
    assert (
        restored.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_360),
            reference_price=Decimal("101"),
            now_ms=1_360,
        )
        == 1
    )
    assert len(restored.iter_records()) == 1
    assert restored.iter_pending() == ()


def test_release_books_never_accept_stale_plan_or_execution_book(
    tmp_path: Path,
) -> None:
    plan_store = _store(tmp_path / "late-plan")
    plan_store.register(_registration())
    assert (
        plan_store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=2_001, exchange_ms=2_000),
            reference_price=Decimal("101"),
            now_ms=2_001,
        )
        == 0
    )
    assert plan_store.iter_pending() == ()
    plan_summary = plan_store.summary(now_ms=2_001)
    assert plan_summary["missed_plan"] == 1
    assert plan_summary["captured"] == 0

    execution_store = _store(tmp_path / "late-execution")
    execution_store.register(_registration())
    execution_store.capture(
        positions=(_position(),),
        instrument=_instrument(),
        book=_book(received_ms=1_100),
        reference_price=Decimal("101"),
        now_ms=1_100,
    )
    assert (
        execution_store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=2_351, exchange_ms=2_350),
            reference_price=Decimal("101"),
            now_ms=2_351,
        )
        == 0
    )
    execution_summary = execution_store.summary(now_ms=2_351)
    assert execution_summary["missed_execution"] == 1
    assert execution_summary["captured"] == 0


def test_release_plan_rejects_pre_opportunity_exchange_timestamp(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "capacity-release-books")
    store.register(_registration())

    assert (
        store.capture(
            positions=(_position(),),
            instrument=_instrument(),
            book=_book(received_ms=1_100, exchange_ms=990),
            reference_price=Decimal("101"),
            now_ms=1_100,
        )
        == 0
    )
    assert store.iter_pending() == ()
    assert store.iter_records() == ()


def test_release_book_capture_registers_only_same_bucket_correlation_holders(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "capacity-release-books")
    capture = CapacityReleaseBookCapture(store)
    risk_decision = SimpleNamespace(
        approved=False,
        reason_codes=("correlation_bucket_exhausted",),
        risk_decision_id="risk-sol",
    )
    request = SimpleNamespace(
        timestamp_ms=1_000,
        market=SOL,
        direction=Direction.SHORT,
        correlation_bucket="majors",
        strategy_decision_id="strategy-sol",
        open_positions=(
            SimpleNamespace(
                market=BTC,
                direction=Direction.LONG,
                correlation_bucket="majors",
            ),
            SimpleNamespace(
                market=MarketId("", "ETH"),
                direction=Direction.SHORT,
                correlation_bucket="alts",
            ),
            SimpleNamespace(
                market=SOL,
                direction=Direction.LONG,
                correlation_bucket="majors",
            ),
        ),
    )
    trace = SimpleNamespace(
        submission=SimpleNamespace(risk_decision=risk_decision),
        risk_request=request,
    )

    capture.register_from_trace(  # type: ignore[arg-type]
        trace,
        opportunity_id="canonical-opportunity-id",
    )

    assert capture.error is None
    registrations = store.iter_registrations()
    assert len(registrations) == 1
    registration = registrations[0]
    assert registration.opportunity_id == "canonical-opportunity-id"
    assert registration.release_market == "BTC"
    assert registration.release_direction == "long"


def test_release_book_capture_ignores_non_correlation_rejections(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "capacity-release-books")
    capture = CapacityReleaseBookCapture(store)
    trace = SimpleNamespace(
        submission=SimpleNamespace(
            risk_decision=SimpleNamespace(
                approved=False,
                reason_codes=("below_venue_min_notional",),
                risk_decision_id="risk-sol",
            )
        ),
        risk_request=SimpleNamespace(
            timestamp_ms=1_000,
            market=SOL,
            direction=Direction.SHORT,
            correlation_bucket="majors",
            strategy_decision_id="strategy-sol",
            open_positions=(),
        ),
    )

    capture.register_from_trace(  # type: ignore[arg-type]
        trace,
        opportunity_id="canonical-opportunity-id",
    )

    assert store.iter_registrations() == ()
    assert capture.error is None
