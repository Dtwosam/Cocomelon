from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.domain.execution import (
    ExecutionResult,
    InstrumentExecutionSpec,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.ioc import simulate_ioc

MARKET = MarketId(dex="", coin="SOL")


def instrument(*, sz_decimals: int = 2) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=sz_decimals,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def plan(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("5"),
    reference_price: Decimal = Decimal("100"),
    risk_ceiling: Decimal = Decimal("60"),
    notional_ceiling: Decimal = Decimal("1000"),
) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-1",
        strategy_decision_id="strategy-1",
        market=MARKET,
        side=side,
        requested_quantity=quantity,
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=reference_price,
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95") if side is OrderSide.BUY else Decimal("105"),
        approved_notional_ceiling=notional_ceiling,
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=risk_ceiling,
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )


def book(
    *,
    bids: tuple[tuple[str, str], ...] = (("99.9", "10"),),
    asks: tuple[tuple[str, str], ...] = (("100.1", "10"),),
    exchange_ms: int = 1_250,
    receive_ms: int = 1_260,
    market: MarketId = MARKET,
) -> StreamEvent:
    payload = {
        "bids": tuple(
            {"px": Decimal(px), "sz": Decimal(sz), "n": 1} for px, sz in bids
        ),
        "asks": tuple(
            {"px": Decimal(px), "sz": Decimal(sz), "n": 1} for px, sz in asks
        ),
    }
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=market,
        exchange_time_ms=exchange_ms,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2:{market.canonical}:{exchange_ms}",
        payload=payload,
    )


def simulate(
    order: PaperOrderPlan,
    snapshot: StreamEvent,
    config: PaperExecutionConfig | None = None,
    *,
    spec: InstrumentExecutionSpec | None = None,
    attempt_timestamp_ms: int = 1_260,
):
    return simulate_ioc(
        order,
        snapshot,
        spec or instrument(),
        config or PaperExecutionConfig(),
        attempt_timestamp_ms=attempt_timestamp_ms,
    )


def test_buy_walks_asks_in_price_order_and_caps_visible_quantity() -> None:
    result = simulate(
        plan(quantity=Decimal("5")),
        book(asks=(("100.1", "2"), ("100.2", "2"), ("100.24", "10"))),
    )

    assert result.attempt.result is ExecutionResult.FULL
    assert tuple(fill.price for fill in result.fills) == (
        Decimal("100.1"),
        Decimal("100.2"),
        Decimal("100.24"),
    )
    assert tuple(fill.quantity for fill in result.fills) == (
        Decimal("2"),
        Decimal("2"),
        Decimal("1"),
    )
    assert result.attempt.filled_quantity == Decimal("5")


def test_sell_walks_bids_from_best_downward() -> None:
    result = simulate(
        plan(side=OrderSide.SELL, quantity=Decimal("3")),
        book(bids=(("99.9", "1"), ("99.8", "2"), ("99.7", "10"))),
    )

    assert result.attempt.result is ExecutionResult.FULL
    assert tuple(fill.price for fill in result.fills) == (Decimal("99.9"), Decimal("99.8"))


def test_input_order_does_not_change_fill_result() -> None:
    ascending = simulate(
        plan(quantity=Decimal("3")),
        book(asks=(("100.1", "1"), ("100.2", "2"), ("100.24", "5"))),
    )
    scrambled = simulate(
        plan(quantity=Decimal("3")),
        book(asks=(("100.24", "5"), ("100.2", "2"), ("100.1", "1"))),
    )

    assert tuple((fill.price, fill.quantity) for fill in ascending.fills) == tuple(
        (fill.price, fill.quantity) for fill in scrambled.fills
    )
    assert ascending.attempt.gross_fill_notional == scrambled.attempt.gross_fill_notional


def test_slippage_guard_stops_before_worse_level_and_returns_partial() -> None:
    result = simulate(
        plan(quantity=Decimal("5")),
        book(asks=(("100.1", "2"), ("100.25", "1"), ("100.26", "10"))),
    )

    assert result.attempt.result is ExecutionResult.PARTIAL
    assert result.attempt.filled_quantity == Decimal("3")
    assert result.attempt.unfilled_quantity == Decimal("2")
    assert all(fill.price <= Decimal("100.25") for fill in result.fills)


def test_insufficient_visible_depth_never_assumes_hidden_liquidity() -> None:
    result = simulate(
        plan(quantity=Decimal("5")),
        book(asks=(("100.1", "1.5"),)),
    )

    assert result.attempt.result is ExecutionResult.PARTIAL
    assert result.attempt.filled_quantity == Decimal("1.5")
    assert result.attempt.unfilled_quantity == Decimal("3.5")


def test_all_depth_outside_guard_returns_no_fill() -> None:
    result = simulate(
        plan(quantity=Decimal("2")),
        book(asks=(("100.26", "10"),)),
    )

    assert result.attempt.result is ExecutionResult.NO_FILL
    assert result.fills == ()


def test_taker_fee_is_charged_on_actual_fill_notional() -> None:
    result = simulate(
        plan(quantity=Decimal("2")),
        book(asks=(("100", "2"),)),
        PaperExecutionConfig(taker_fee_rate=Decimal("0.001")),
    )

    assert result.attempt.gross_fill_notional == Decimal("200")
    assert result.attempt.fee == Decimal("0.200")
    assert sum(fill.taker_fee for fill in result.fills) == Decimal("0.200")


def test_before_latency_rejects_without_fill() -> None:
    result = simulate(plan(), book(), attempt_timestamp_ms=1_249)

    assert result.attempt.result is ExecutionResult.REJECTED
    assert "LATENCY_NOT_ELAPSED" in result.attempt.reason_codes
    assert result.fills == ()


def test_stale_crossed_future_and_mismatched_books_fail_closed() -> None:
    config = PaperExecutionConfig(max_book_age_ms=100)
    stale = simulate(plan(), book(receive_ms=1_000), config)
    crossed = simulate(
        plan(),
        book(bids=(("100.2", "2"),), asks=(("100.1", "2"),)),
        config,
    )
    future = simulate(plan(), book(receive_ms=1_261), config)
    mismatched = simulate(
        plan(),
        book(market=MarketId(dex="", coin="BTC")),
        config,
    )

    assert stale.attempt.result is ExecutionResult.REJECTED
    assert "STALE_BOOK" in stale.attempt.reason_codes
    assert crossed.attempt.result is ExecutionResult.REJECTED
    assert "CROSSED_BOOK" in crossed.attempt.reason_codes
    assert future.attempt.result is ExecutionResult.REJECTED
    assert "FUTURE_BOOK" in future.attempt.reason_codes
    assert mismatched.attempt.result is ExecutionResult.REJECTED
    assert "MARKET_MISMATCH" in mismatched.attempt.reason_codes


def test_instrument_market_mismatch_and_unsupported_namespace_fail_closed() -> None:
    mismatch = InstrumentExecutionSpec(
        market=MarketId(dex="", coin="BTC"),
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="meta",
    )
    unsupported = InstrumentExecutionSpec(
        market=MarketId(dex="xyz", coin="NVDA"),
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="meta",
    )

    mismatch_result = simulate(plan(), book(), spec=mismatch)
    unsupported_plan = PaperOrderPlan(
        risk_decision_id="risk-2",
        strategy_decision_id="strategy-2",
        market=unsupported.market,
        side=OrderSide.BUY,
        requested_quantity=Decimal("1"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95"),
        approved_notional_ceiling=Decimal("100"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("10"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )
    unsupported_result = simulate(
        unsupported_plan,
        book(market=unsupported.market),
        spec=unsupported,
    )

    assert mismatch_result.attempt.result is ExecutionResult.REJECTED
    assert "INSTRUMENT_MISMATCH" in mismatch_result.attempt.reason_codes
    assert unsupported_result.attempt.result is ExecutionResult.REJECTED
    assert "UNSUPPORTED_NON_NATIVE_PERP_DEX" in unsupported_result.attempt.reason_codes


def test_notional_ceiling_clips_final_level_to_lot_quantum() -> None:
    result = simulate(
        plan(
            quantity=Decimal("5"),
            notional_ceiling=Decimal("250.55"),
        ),
        book(asks=(("100", "5"),)),
        spec=instrument(sz_decimals=2),
    )

    assert result.attempt.result is ExecutionResult.PARTIAL
    assert result.attempt.filled_quantity == Decimal("2.50")
    assert result.attempt.gross_fill_notional == Decimal("250.00")
    assert result.attempt.gross_fill_notional <= Decimal("250.55")


def test_phase6_loss_ceiling_clips_final_level_without_upsizing() -> None:
    order = plan(
        quantity=Decimal("5"),
        risk_ceiling=Decimal("25"),
        notional_ceiling=Decimal("1000"),
    )
    result = simulate(
        order,
        book(asks=(("100", "5"),)),
        spec=instrument(sz_decimals=2),
    )

    assert result.attempt.result is ExecutionResult.PARTIAL
    assert result.attempt.filled_quantity == Decimal("4.76")
    assert result.attempt.gross_fill_notional == Decimal("476.00")
    avg_fill = result.attempt.average_fill_price
    assert avg_fill is not None
    actual_stop_fraction = abs(avg_fill - Decimal("95")) / avg_fill
    actual_effective_fraction = actual_stop_fraction + Decimal("0.0025")
    planned_loss = result.attempt.gross_fill_notional * actual_effective_fraction
    assert planned_loss == Decimal("24.990000")
    assert planned_loss <= Decimal("25")


def test_worse_buy_price_consumes_more_risk_and_clips_more_aggressively() -> None:
    order = plan(quantity=Decimal("5"), risk_ceiling=Decimal("25"))
    better = simulate(
        order,
        book(asks=(("100", "5"),)),
        spec=instrument(sz_decimals=2),
    )
    worse = simulate(
        order,
        book(asks=(("100.25", "5"),)),
        spec=instrument(sz_decimals=2),
    )

    assert worse.attempt.filled_quantity < better.attempt.filled_quantity
    assert worse.attempt.gross_fill_notional <= order.approved_notional_ceiling


def test_sell_loss_ceiling_is_symmetric_and_lot_rounded_down() -> None:
    order = plan(
        side=OrderSide.SELL,
        quantity=Decimal("5"),
        risk_ceiling=Decimal("25"),
    )
    result = simulate(
        order,
        book(bids=(("100", "5"),)),
        spec=instrument(sz_decimals=2),
    )

    assert result.attempt.result is ExecutionResult.PARTIAL
    assert result.attempt.filled_quantity == Decimal("4.76")
    assert result.attempt.gross_fill_notional == Decimal("476.00")
