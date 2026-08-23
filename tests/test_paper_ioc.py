from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.execution.ioc import simulate_ioc

from cocomelon.domain.execution import (
    ExecutionResult,
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind

MARKET = MarketId(dex="", coin="SOL")


def plan(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("5"),
    reference_price: Decimal = Decimal("100"),
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
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
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


def test_buy_walks_asks_in_price_order_and_caps_visible_quantity() -> None:
    result = simulate_ioc(
        plan(quantity=Decimal("5")),
        book(asks=(("100.1", "2"), ("100.2", "2"), ("100.24", "10"))),
        PaperExecutionConfig(),
        attempt_timestamp_ms=1_260,
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
    result = simulate_ioc(
        plan(side=OrderSide.SELL, quantity=Decimal("3")),
        book(bids=(("99.9", "1"), ("99.8", "2"), ("99.7", "10"))),
        PaperExecutionConfig(),
        attempt_timestamp_ms=1_260,
    )

    assert result.attempt.result is ExecutionResult.FULL
    assert tuple(fill.price for fill in result.fills) == (Decimal("99.9"), Decimal("99.8"))


def test_slippage_guard_stops_before_worse_level_and_returns_partial() -> None:
    result = simulate_ioc(
        plan(quantity=Decimal("5")),
        book(asks=(("100.1", "2"), ("100.25", "1"), ("100.26", "10"))),
        PaperExecutionConfig(),
        attempt_timestamp_ms=1_260,
    )

    assert result.attempt.result is ExecutionResult.PARTIAL
    assert result.attempt.filled_quantity == Decimal("3")
    assert result.attempt.unfilled_quantity == Decimal("2")
    assert all(fill.price <= Decimal("100.25") for fill in result.fills)


def test_insufficient_visible_depth_never_assumes_hidden_liquidity() -> None:
    result = simulate_ioc(
        plan(quantity=Decimal("5")),
        book(asks=(("100.1", "1.5"),)),
        PaperExecutionConfig(),
        attempt_timestamp_ms=1_260,
    )

    assert result.attempt.result is ExecutionResult.PARTIAL
    assert result.attempt.filled_quantity == Decimal("1.5")
    assert result.attempt.unfilled_quantity == Decimal("3.5")


def test_all_depth_outside_guard_returns_no_fill() -> None:
    result = simulate_ioc(
        plan(quantity=Decimal("2")),
        book(asks=(("100.26", "10"),)),
        PaperExecutionConfig(),
        attempt_timestamp_ms=1_260,
    )

    assert result.attempt.result is ExecutionResult.NO_FILL
    assert result.fills == ()


def test_taker_fee_is_charged_on_actual_fill_notional() -> None:
    result = simulate_ioc(
        plan(quantity=Decimal("2")),
        book(asks=(("100", "2"),)),
        PaperExecutionConfig(taker_fee_rate=Decimal("0.001")),
        attempt_timestamp_ms=1_260,
    )

    assert result.attempt.gross_fill_notional == Decimal("200")
    assert result.attempt.fee == Decimal("0.200")
    assert sum(fill.taker_fee for fill in result.fills) == Decimal("0.200")


def test_before_latency_rejects_without_fill() -> None:
    result = simulate_ioc(
        plan(), book(), PaperExecutionConfig(), attempt_timestamp_ms=1_249
    )

    assert result.attempt.result is ExecutionResult.REJECTED
    assert "LATENCY_NOT_ELAPSED" in result.attempt.reason_codes
    assert result.fills == ()


def test_stale_crossed_and_mismatched_books_fail_closed() -> None:
    config = PaperExecutionConfig(max_book_age_ms=100)
    stale = simulate_ioc(plan(), book(receive_ms=1_000), config, attempt_timestamp_ms=1_260)
    crossed = simulate_ioc(
        plan(),
        book(bids=(("100.2", "2"),), asks=(("100.1", "2"),)),
        config,
        attempt_timestamp_ms=1_260,
    )
    mismatched = simulate_ioc(
        plan(),
        book(market=MarketId(dex="", coin="BTC")),
        config,
        attempt_timestamp_ms=1_260,
    )

    assert stale.attempt.result is ExecutionResult.REJECTED
    assert "STALE_BOOK" in stale.attempt.reason_codes
    assert crossed.attempt.result is ExecutionResult.REJECTED
    assert "CROSSED_BOOK" in crossed.attempt.reason_codes
    assert mismatched.attempt.result is ExecutionResult.REJECTED
    assert "MARKET_MISMATCH" in mismatched.attempt.reason_codes
