from decimal import Decimal

from cocomelon.execution.accounting import (
    apply_opening_fills,
    apply_reduce_only_fills,
    empty_account,
    mark_to_market,
)

from cocomelon.domain.execution import (
    OrderSide,
    OrderType,
    PaperFill,
    PaperOrderPlan,
    PositionSide,
)
from cocomelon.domain.market import MarketId

MARKET = MarketId(dex="", coin="SOL")


def opening_plan(*, side: OrderSide = OrderSide.BUY) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-1",
        strategy_decision_id="strategy-1",
        market=MARKET,
        side=side,
        requested_quantity=Decimal("10"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95") if side is OrderSide.BUY else Decimal("105"),
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("25"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
    )


def fill(
    *,
    plan_id: str,
    side: OrderSide,
    price: str,
    quantity: str,
    fee: str,
    suffix: str,
) -> PaperFill:
    px = Decimal(price)
    qty = Decimal(quantity)
    return PaperFill(
        plan_id=plan_id,
        attempt_id=f"attempt-{suffix}",
        market=MARKET,
        side=side,
        price=px,
        quantity=qty,
        notional=px * qty,
        taker_fee=Decimal(fee),
        source_event_key=f"l2:SOL:{suffix}",
        timestamp_ms=2_000,
    )


def test_long_opening_uses_actual_fill_weighted_average_and_fees() -> None:
    plan = opening_plan()
    fills = (
        fill(
            plan_id=plan.plan_id,
            side=OrderSide.BUY,
            price="100",
            quantity="4",
            fee="0.4",
            suffix="1",
        ),
        fill(
            plan_id=plan.plan_id,
            side=OrderSide.BUY,
            price="102",
            quantity="6",
            fee="0.612",
            suffix="2",
        ),
    )
    account = apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, fills)

    position = account.positions[0]
    assert position.side is PositionSide.LONG
    assert position.quantity == Decimal("10")
    assert position.average_entry_price == Decimal("101.2")
    assert account.cash == Decimal("9998.988")
    assert account.cumulative_fees == Decimal("1.012")


def test_short_exit_realized_pnl_sign_is_correct() -> None:
    plan = opening_plan(side=OrderSide.SELL)
    entry = fill(
        plan_id=plan.plan_id,
        side=OrderSide.SELL,
        price="100",
        quantity="5",
        fee="0.5",
        suffix="entry",
    )
    opened = apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, (entry,))
    exit_fill = fill(
        plan_id="reduce-1",
        side=OrderSide.BUY,
        price="90",
        quantity="2",
        fee="0.18",
        suffix="exit",
    )

    reduced = apply_reduce_only_fills(opened, MARKET, (exit_fill,), 3_000)

    assert reduced.positions[0].quantity == Decimal("3")
    assert reduced.realized_gross_pnl == Decimal("20")
    assert reduced.cash == Decimal("10019.32")
    assert reduced.cumulative_fees == Decimal("0.68")


def test_long_partial_exit_preserves_average_entry_and_remainder() -> None:
    plan = opening_plan()
    entry = fill(
        plan_id=plan.plan_id,
        side=OrderSide.BUY,
        price="100",
        quantity="10",
        fee="0.5",
        suffix="entry",
    )
    opened = apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, (entry,))
    exit_fill = fill(
        plan_id="reduce-1",
        side=OrderSide.SELL,
        price="110",
        quantity="4",
        fee="0.22",
        suffix="exit",
    )

    reduced = apply_reduce_only_fills(opened, MARKET, (exit_fill,), 3_000)

    position = reduced.positions[0]
    assert position.quantity == Decimal("6")
    assert position.average_entry_price == Decimal("100")
    assert reduced.realized_gross_pnl == Decimal("40")


def test_reduce_only_exit_cannot_reverse_or_use_opening_side() -> None:
    plan = opening_plan()
    entry = fill(
        plan_id=plan.plan_id,
        side=OrderSide.BUY,
        price="100",
        quantity="10",
        fee="0.5",
        suffix="entry",
    )
    opened = apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, (entry,))
    too_large = fill(
        plan_id="reduce-1",
        side=OrderSide.SELL,
        price="110",
        quantity="11",
        fee="0.6",
        suffix="large",
    )
    wrong_side = fill(
        plan_id="reduce-2",
        side=OrderSide.BUY,
        price="110",
        quantity="1",
        fee="0.1",
        suffix="wrong",
    )

    try:
        apply_reduce_only_fills(opened, MARKET, (too_large,), 3_000)
    except ValueError as exc:
        assert "reverse" in str(exc)
    else:
        raise AssertionError("reduce-only overfill must fail")

    try:
        apply_reduce_only_fills(opened, MARKET, (wrong_side,), 3_000)
    except ValueError as exc:
        assert "side" in str(exc)
    else:
        raise AssertionError("same-side reduce-only fill must fail")


def test_opening_fills_cannot_average_into_existing_position() -> None:
    plan = opening_plan()
    entry = fill(
        plan_id=plan.plan_id,
        side=OrderSide.BUY,
        price="100",
        quantity="5",
        fee="0.25",
        suffix="entry",
    )
    opened = apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, (entry,))

    try:
        apply_opening_fills(opened, plan, (entry,))
    except ValueError as exc:
        assert "existing position" in str(exc)
    else:
        raise AssertionError("Phase 7 must not average into an existing position")


def test_mark_to_market_updates_unrealized_equity_and_gross_notional() -> None:
    plan = opening_plan()
    entry = fill(
        plan_id=plan.plan_id,
        side=OrderSide.BUY,
        price="100",
        quantity="10",
        fee="0.5",
        suffix="entry",
    )
    opened = apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, (entry,))

    marked = mark_to_market(opened, {MARKET: Decimal("105")}, 3_000)

    assert marked.unrealized_pnl == Decimal("50")
    assert marked.gross_open_notional == Decimal("1050")
    assert marked.equity == Decimal("10049.5")


def test_replaying_same_account_events_produces_same_state_id() -> None:
    plan = opening_plan()
    entry = fill(
        plan_id=plan.plan_id,
        side=OrderSide.BUY,
        price="100",
        quantity="10",
        fee="0.5",
        suffix="entry",
    )

    first = mark_to_market(
        apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, (entry,)),
        {MARKET: Decimal("105")},
        3_000,
    )
    second = mark_to_market(
        apply_opening_fills(empty_account(Decimal("10000"), 1_000), plan, (entry,)),
        {MARKET: Decimal("105")},
        3_000,
    )

    assert first.state_id == second.state_id
