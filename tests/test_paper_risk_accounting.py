import importlib
from decimal import Decimal

from cocomelon.domain.execution import OrderSide, OrderType, PaperFill, PaperOrderPlan
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction

accounting = importlib.import_module("cocomelon.execution.accounting")

MARKET = MarketId("", "SOL")
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS


def opening_plan(*, side: OrderSide = OrderSide.BUY) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-paper-1",
        strategy_decision_id="strategy-paper-1",
        market=MARKET,
        side=side,
        requested_quantity=Decimal("5"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95") if side is OrderSide.BUY else Decimal("105"),
        approved_notional_ceiling=Decimal("600"),
        approved_risk_amount_ceiling=Decimal("60"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.0525"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
    )


def paper_fill(
    *,
    plan_id: str,
    side: OrderSide,
    price: str,
    quantity: str,
    fee: str,
    timestamp_ms: int,
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
        timestamp_ms=timestamp_ms,
    )


def open_long(*, timestamp_ms: int = 2_000):
    plan = opening_plan()
    entry = paper_fill(
        plan_id=plan.plan_id,
        side=OrderSide.BUY,
        price="100",
        quantity="5",
        fee="0.5",
        timestamp_ms=timestamp_ms,
        suffix="entry",
    )
    account = accounting.apply_opening_fills(
        accounting.empty_account(Decimal("10000"), 0),
        plan,
        (entry,),
        correlation_bucket="crypto_beta",
        venue_max_leverage=Decimal("20"),
    )
    return plan, account


def test_empty_account_initializes_phase6_control_state_and_rolling_peak() -> None:
    account = accounting.empty_account(Decimal("10000"), 0)

    assert account.day_start_equity == Decimal("10000")
    assert account.daily_realized_pnl == Decimal("0")
    assert account.reserved_margin == Decimal("0")
    assert account.available_margin == Decimal("10000")
    assert account.consecutive_losses == 0
    assert account.last_closed_trade_ms is None
    candidates = tuple(
        (point.timestamp_ms, point.equity) for point in account.rolling_peak_candidates
    )
    assert candidates == ((0, Decimal("10000")),)
    assert account.rolling_7d_peak_equity == Decimal("10000")


def test_open_position_preserves_planned_risk_bucket_and_entry_fee_cash_loss() -> None:
    plan, account = open_long()
    position = account.positions[0]

    assert position.correlation_bucket == "crypto_beta"
    assert position.initial_risk_decision_id == plan.risk_decision_id
    assert position.cost_buffer_fraction == Decimal("0.0025")
    assert position.planned_risk == Decimal("26.2500")
    assert position.cumulative_fees == Decimal("0.5")
    assert position.cumulative_funding == Decimal("0")
    assert position.realized_gross_pnl == Decimal("0")
    assert account.daily_realized_pnl == Decimal("-0.5")


def test_mark_to_market_computes_margin_available_equity_and_phase6_adapter() -> None:
    _, opened = open_long()
    marked = accounting.mark_to_market(opened, {MARKET: Decimal("105")}, 3_000)

    assert marked.unrealized_pnl == Decimal("25")
    assert marked.equity == Decimal("10024.5")
    assert marked.gross_open_notional == Decimal("525")
    assert marked.reserved_margin == Decimal("175")
    assert marked.available_margin == Decimal("9849.5")

    risk_account, open_risk = accounting.risk_state_from_paper(marked)
    assert risk_account.equity == marked.equity
    assert risk_account.available_margin == marked.available_margin
    assert risk_account.gross_open_notional == marked.gross_open_notional
    assert risk_account.daily_realized_pnl == Decimal("-0.5")
    assert risk_account.rolling_7d_peak_equity == marked.rolling_7d_peak_equity
    assert risk_account.consecutive_losses == 0
    assert risk_account.last_closed_trade_ms is None
    assert len(open_risk) == 1
    assert open_risk[0].direction is Direction.LONG
    assert open_risk[0].planned_risk == Decimal("26.2500")
    assert open_risk[0].notional == Decimal("525")
    assert open_risk[0].correlation_bucket == "crypto_beta"


def test_full_losing_close_books_net_result_and_increments_loss_streak() -> None:
    _, opened = open_long()
    exit_fill = paper_fill(
        plan_id="reduce-loss",
        side=OrderSide.SELL,
        price="94",
        quantity="5",
        fee="0.235",
        timestamp_ms=4_000,
        suffix="loss-exit",
    )

    closed = accounting.apply_reduce_only_fills(opened, MARKET, (exit_fill,), 4_000)

    assert closed.positions == ()
    assert closed.realized_gross_pnl == Decimal("-30")
    assert closed.cumulative_fees == Decimal("0.735")
    assert closed.cash == Decimal("9969.265")
    assert closed.daily_realized_pnl == Decimal("-30.735")
    assert closed.consecutive_losses == 1
    assert closed.last_closed_trade_ms == 4_000


def test_partial_reduce_does_not_change_loss_streak_and_scales_planned_risk() -> None:
    _, opened = open_long()
    partial = paper_fill(
        plan_id="reduce-partial",
        side=OrderSide.SELL,
        price="94",
        quantity="2",
        fee="0.094",
        timestamp_ms=4_000,
        suffix="partial",
    )

    reduced = accounting.apply_reduce_only_fills(opened, MARKET, (partial,), 4_000)
    position = reduced.positions[0]

    assert reduced.consecutive_losses == 0
    assert reduced.last_closed_trade_ms is None
    assert position.quantity == Decimal("3")
    assert position.planned_risk == Decimal("15.7500")
    assert position.realized_gross_pnl == Decimal("-12")
    assert position.cumulative_fees == Decimal("0.594")


def test_profitable_full_close_resets_existing_loss_streak() -> None:
    _, opened = open_long()
    seeded = accounting.replace_loss_state(
        opened,
        consecutive_losses=2,
        last_closed_trade_ms=1_500,
    )
    exit_fill = paper_fill(
        plan_id="reduce-win",
        side=OrderSide.SELL,
        price="110",
        quantity="5",
        fee="0.275",
        timestamp_ms=4_000,
        suffix="win-exit",
    )

    closed = accounting.apply_reduce_only_fills(seeded, MARKET, (exit_fill,), 4_000)

    assert closed.consecutive_losses == 0
    assert closed.last_closed_trade_ms == 4_000


def test_rolling_peak_queue_is_exact_and_expires_only_when_older_than_seven_days() -> None:
    candidates = ()
    candidates = accounting.update_rolling_peak(candidates, 0, Decimal("10000"))
    candidates = accounting.update_rolling_peak(candidates, DAY_MS, Decimal("10100"))
    candidates = accounting.update_rolling_peak(candidates, 2 * DAY_MS, Decimal("10050"))
    candidates = accounting.update_rolling_peak(candidates, 3 * DAY_MS, Decimal("10200"))

    assert tuple(point.equity for point in candidates) == (Decimal("10200"),)

    at_exact_seven_days = accounting.update_rolling_peak(
        candidates,
        3 * DAY_MS + WEEK_MS,
        Decimal("10100"),
    )
    assert at_exact_seven_days[0].equity == Decimal("10200")

    after_expiry = accounting.update_rolling_peak(
        at_exact_seven_days,
        3 * DAY_MS + WEEK_MS + 1,
        Decimal("10110"),
    )
    assert after_expiry[0].equity == Decimal("10110")


def test_new_utc_day_resets_daily_realized_baseline_without_changing_cash() -> None:
    _, opened = open_long(timestamp_ms=2_000)
    assert opened.daily_realized_pnl == Decimal("-0.5")

    next_day = accounting.roll_account_day(opened, DAY_MS)

    assert next_day.cash == opened.cash
    assert next_day.daily_realized_pnl == Decimal("0")
    assert next_day.day_start_equity == opened.equity
    assert next_day.day_start_ms == DAY_MS
