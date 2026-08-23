from decimal import ROUND_DOWN, Context, Decimal, getcontext, setcontext

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.journal.analytics import ExcursionPoint, build_trade_summary

MARKET = MarketId(dex="", coin="SOL")


def build(
    *,
    direction: Direction,
    entry_price: str,
    exit_price: str,
    points: tuple[ExcursionPoint, ...],
):
    return build_trade_summary(
        trade_id="trade-1",
        decision_id="decision-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-1",
        replay_run_id="run-1",
        market=MARKET,
        direction=direction,
        entry_timestamp_ms=1_000,
        exit_timestamp_ms=5_000,
        entry_price=Decimal(entry_price),
        exit_price=Decimal(exit_price),
        quantity=Decimal("10"),
        initial_stop_price=Decimal("95") if direction is Direction.LONG else Decimal("105"),
        approved_risk_amount=Decimal("50"),
        maximum_actual_notional=Decimal("1000"),
        fees=Decimal("1.5"),
        funding=Decimal("-0.5"),
        entry_slippage=Decimal("0.4"),
        exit_slippage=Decimal("0.6"),
        exit_reason="THESIS_EXIT",
        reason_trace=("TREND", "RISK_APPROVED", "THESIS_EXIT"),
        equity_before=Decimal("10000"),
        excursion_points=points,
    )


def test_long_summary_reports_gross_net_mfe_mae_and_net_r() -> None:
    summary = build(
        direction=Direction.LONG,
        entry_price="100",
        exit_price="102",
        points=(
            ExcursionPoint(500, Decimal("80")),
            ExcursionPoint(1_500, Decimal("98")),
            ExcursionPoint(2_000, Decimal("103")),
            ExcursionPoint(3_000, Decimal("105")),
            ExcursionPoint(4_000, Decimal("99")),
            ExcursionPoint(6_000, Decimal("140")),
        ),
    )

    assert summary.gross_pnl == Decimal("20")
    assert summary.net_pnl == Decimal("17.0")
    assert summary.mfe_pnl == Decimal("50")
    assert summary.mae_pnl == Decimal("-20")
    assert summary.net_r == Decimal("0.34")
    assert summary.mfe_r == Decimal("1")
    assert summary.mae_r == Decimal("-0.4")
    assert summary.holding_ms == 4_000
    assert summary.equity_after == Decimal("10017.0")


def test_short_summary_reverses_excursion_and_pnl_signs() -> None:
    summary = build(
        direction=Direction.SHORT,
        entry_price="100",
        exit_price="97",
        points=(
            ExcursionPoint(1_000, Decimal("100")),
            ExcursionPoint(2_000, Decimal("102")),
            ExcursionPoint(3_000, Decimal("94")),
            ExcursionPoint(4_000, Decimal("99")),
        ),
    )

    assert summary.gross_pnl == Decimal("30")
    assert summary.net_pnl == Decimal("27.0")
    assert summary.mfe_pnl == Decimal("60")
    assert summary.mae_pnl == Decimal("-20")
    assert summary.net_r == Decimal("0.54")


def test_positive_funding_is_received_and_increases_net_pnl() -> None:
    summary = build_trade_summary(
        trade_id="trade-funding",
        decision_id="decision-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-1",
        replay_run_id="run-1",
        market=MARKET,
        direction=Direction.LONG,
        entry_timestamp_ms=1_000,
        exit_timestamp_ms=2_000,
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        quantity=Decimal("1"),
        initial_stop_price=Decimal("95"),
        approved_risk_amount=Decimal("5"),
        maximum_actual_notional=Decimal("100"),
        fees=Decimal("0"),
        funding=Decimal("2"),
        entry_slippage=Decimal("0"),
        exit_slippage=Decimal("0"),
        exit_reason="TIME_EXIT",
        reason_trace=("TIME_EXIT",),
        equity_before=Decimal("100"),
        excursion_points=(),
    )

    assert summary.gross_pnl == Decimal("0")
    assert summary.net_pnl == Decimal("2")
    assert summary.equity_after == Decimal("102")


def test_analytics_ignore_ambient_decimal_context() -> None:
    original = getcontext().copy()
    try:
        setcontext(Context(prec=4, rounding=ROUND_DOWN))
        summary = build(
            direction=Direction.LONG,
            entry_price="100.123456789",
            exit_price="101.987654321",
            points=(ExcursionPoint(2_000, Decimal("102.111111111")),),
        )
    finally:
        setcontext(original)

    assert summary.gross_pnl == Decimal("18.641975320")
    assert summary.mfe_pnl == Decimal("19.876543220")


def test_empty_excursion_window_reports_zero_mfe_and_mae() -> None:
    summary = build(
        direction=Direction.LONG,
        entry_price="100",
        exit_price="101",
        points=(ExcursionPoint(500, Decimal("80")), ExcursionPoint(6_000, Decimal("120"))),
    )

    assert summary.mfe_pnl == Decimal("0")
    assert summary.mae_pnl == Decimal("0")
