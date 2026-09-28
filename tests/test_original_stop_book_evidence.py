from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperOrderPlan,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.original_stop_book_evidence import (
    OriginalStopBookCapture,
    OriginalStopBookEvidenceStore,
)

MARKET = MarketId("", "SOL")


def _plan(*, side: OrderSide = OrderSide.BUY) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-1",
        strategy_decision_id="strategy-1",
        market=MARKET,
        side=side,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=(
            Decimal("95")
            if side is OrderSide.BUY
            else Decimal("105")
        ),
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=900,
        earliest_execution_ms=1_000,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=800,
        approved_risk_amount_ceiling=Decimal("20"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.051"),
    )


def _position(
    plan: PaperOrderPlan,
    *,
    side: PositionSide = PositionSide.LONG,
) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=side,
        quantity=Decimal("2"),
        average_entry_price=Decimal("100"),
        stop_price=(
            Decimal("95")
            if side is PositionSide.LONG
            else Decimal("105")
        ),
        opening_plan_id=plan.plan_id,
        opened_at_ms=1_000,
        updated_at_ms=1_000,
        planned_risk=Decimal("20"),
    )


def _mark(price: str, receive_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(
            receive_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"mark:{receive_ms}",
        payload={"mark_px": Decimal(price)},
    )


def _book(receive_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(
            receive_ms / 1000,
            tz=UTC,
        ),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:{receive_ms}",
        payload={
            "bids": (
                {"px": Decimal("94.9"), "sz": Decimal("1"), "n": 2},
                {"px": Decimal("94.8"), "sz": Decimal("3"), "n": 1},
            ),
            "asks": (
                {"px": Decimal("95.1"), "sz": Decimal("4"), "n": 1},
            ),
        },
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=800,
        metadata_source="hyperliquid-mainnet-meta",
    )


def test_capture_persists_first_book_after_original_stop_crossing(
    tmp_path: Path,
) -> None:
    store = OriginalStopBookEvidenceStore(tmp_path / "stop-books")
    plan = _plan()
    position = _position(plan)
    capture = OriginalStopBookCapture(
        store,
        opening_plan_loader=lambda plan_id: (
            plan if plan_id == plan.plan_id else None
        ),
    )

    capture.observe_mark(
        (position,),
        _mark("96", 1_100),
        now_ms=1_100,
    )
    assert store.pending_count == 0
    assert store.record_count == 0

    capture.observe_mark(
        (position,),
        _mark("94.95", 1_200),
        now_ms=1_200,
    )
    assert store.pending_count == 1

    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_210),
        reference_price=Decimal("95"),
        now_ms=1_210,
    )

    assert capture.error is None
    assert store.pending_count == 0
    assert store.record_count == 1

    restored = OriginalStopBookEvidenceStore(
        tmp_path / "stop-books"
    )
    evidence = restored.evidence_for(plan.plan_id)
    assert evidence is not None
    assert evidence.crossing.original_stop == Decimal("95")
    assert evidence.crossing.crossing_mark_price == Decimal("94.95")
    assert evidence.book_event_key == "book:1210"
    assert evidence.reference_price == Decimal("95")
    assert evidence.book_source == "hyperliquid-mainnet-ws"
    assert evidence.book_schema_version == 1
    assert evidence.instrument_sz_decimals == 2
    assert evidence.instrument_venue_max_leverage == Decimal("20")
    assert (
        evidence.instrument_minimum_order_notional
        == Decimal("10")
    )
    assert evidence.instrument_metadata_received_at_ms == 800
    assert (
        evidence.instrument_metadata_source
        == "hyperliquid-mainnet-meta"
    )
    assert tuple(level.price for level in evidence.bids) == (
        Decimal("94.9"),
        Decimal("94.8"),
    )
    rebuilt = evidence.book_event()
    assert rebuilt.kind is StreamKind.L2_BOOK
    assert rebuilt.payload["bids"][0]["px"] == Decimal("94.9")
    spec = evidence.instrument_spec()
    assert spec.size_quantum == Decimal("0.01")
    assert spec.metadata_received_at_ms == 800


def test_pending_crossing_survives_store_restart_before_book(
    tmp_path: Path,
) -> None:
    root = tmp_path / "stop-books"
    plan = _plan()
    position = _position(plan)
    first = OriginalStopBookCapture(
        OriginalStopBookEvidenceStore(root),
        opening_plan_loader=lambda _plan_id: plan,
    )

    first.observe_mark(
        (position,),
        _mark("94.9", 1_200),
        now_ms=1_200,
    )
    assert first.store.pending_count == 1

    restored_store = OriginalStopBookEvidenceStore(root)
    restored = OriginalStopBookCapture(
        restored_store,
        opening_plan_loader=lambda _plan_id: plan,
    )
    restored.observe_book(
        (position,),
        _instrument(),
        _book(1_240),
        reference_price=Decimal("95"),
        now_ms=1_240,
    )

    assert restored.error is None
    assert restored_store.pending_count == 0
    evidence = restored_store.evidence_for(plan.plan_id)
    assert evidence is not None
    assert evidence.crossing.crossing_mark_event_key == "mark:1200"
    assert evidence.book_event_key == "book:1240"


def test_short_crossing_captures_ask_side_book(
    tmp_path: Path,
) -> None:
    store = OriginalStopBookEvidenceStore(tmp_path / "stop-books")
    plan = _plan(side=OrderSide.SELL)
    position = _position(plan, side=PositionSide.SHORT)
    capture = OriginalStopBookCapture(
        store,
        opening_plan_loader=lambda _plan_id: plan,
    )

    capture.observe_mark(
        (position,),
        _mark("105.1", 1_200),
        now_ms=1_200,
    )
    capture.observe_book(
        (position,),
        _instrument(),
        _book(1_205),
        reference_price=Decimal("95"),
        now_ms=1_205,
    )

    evidence = store.evidence_for(plan.plan_id)
    assert evidence is not None
    assert evidence.crossing.direction == "short"
    assert evidence.crossing.crossing_mark_price == Decimal("105.1")
    assert evidence.asks[0].price == Decimal("95.1")


def test_capture_is_fail_open_when_opening_plan_is_missing(
    tmp_path: Path,
) -> None:
    store = OriginalStopBookEvidenceStore(tmp_path / "stop-books")
    plan = _plan()
    capture = OriginalStopBookCapture(
        store,
        opening_plan_loader=lambda _plan_id: None,
    )

    capture.observe_mark(
        (_position(plan),),
        _mark("94", 1_200),
        now_ms=1_200,
    )

    assert capture.error is not None
    assert store.pending_count == 0
    assert store.record_count == 0
