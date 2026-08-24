from decimal import ROUND_UP, Context, Decimal, localcontext

from cocomelon.domain.evaluation import AccountEquityFact, EquityFactKind, TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.metrics import compute_performance_metrics

DAY_MS = 86_400_000
SOL = MarketId("", "SOL")
ETH = MarketId("", "ETH")


def sample(
    suffix: str,
    *,
    market: MarketId,
    lead_strategy: str,
    day: int,
    gross_pnl: str,
    entry_fee: str,
    exit_fee: str,
    funding: str,
    net_pnl: str,
    net_r: str,
    equity_before: str,
    equity_after: str,
    holding_ms: int,
    entry_slippage: str = "0",
    exit_slippage: str = "0",
) -> TradeEvaluationSample:
    closed_at_ms = day * DAY_MS + 10_000
    opened_at_ms = closed_at_ms - holding_ms
    return TradeEvaluationSample(
        trade_id=f"trade-{suffix}",
        replay_run_id="run-1",
        strategy_decision_id=f"strategy-{suffix}",
        market=market,
        direction=Direction.LONG,
        decision_timestamp_ms=max(0, opened_at_ms - 100),
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        score=Decimal("70"),
        lead_strategy=lead_strategy,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=Decimal(gross_pnl),
        entry_fees=Decimal(entry_fee),
        exit_fees=Decimal(exit_fee),
        funding_cash_pnl=Decimal(funding),
        net_pnl=Decimal(net_pnl),
        entry_slippage_amount=Decimal(entry_slippage),
        exit_slippage_amount=Decimal(exit_slippage),
        net_r=Decimal(net_r),
        equity_before=Decimal(equity_before),
        equity_after=Decimal(equity_after),
        holding_duration_ms=holding_ms,
        reason_codes=("TEST",),
    )


def fixture_samples() -> tuple[TradeEvaluationSample, ...]:
    return (
        sample(
            "a",
            market=SOL,
            lead_strategy="trend",
            day=0,
            gross_pnl="20",
            entry_fee="1",
            exit_fee="1",
            funding="-1",
            net_pnl="17",
            net_r="0.68",
            equity_before="10000",
            equity_after="10017",
            holding_ms=1_000,
            entry_slippage="0.5",
            exit_slippage="0.5",
        ),
        sample(
            "b",
            market=ETH,
            lead_strategy="breakout",
            day=1,
            gross_pnl="-7",
            entry_fee="0.5",
            exit_fee="0.5",
            funding="0",
            net_pnl="-8",
            net_r="-0.32",
            equity_before="10017",
            equity_after="10009",
            holding_ms=2_000,
            entry_slippage="0.2",
            exit_slippage="-0.1",
        ),
        sample(
            "c",
            market=SOL,
            lead_strategy="trend",
            day=2,
            gross_pnl="5",
            entry_fee="0.5",
            exit_fee="0.5",
            funding="1",
            net_pnl="5",
            net_r="0.20",
            equity_before="10009",
            equity_after="10014",
            holding_ms=3_000,
            entry_slippage="-0.2",
        ),
        sample(
            "d",
            market=ETH,
            lead_strategy="breakout",
            day=7,
            gross_pnl="-2",
            entry_fee="0.5",
            exit_fee="0.5",
            funding="0",
            net_pnl="-3",
            net_r="-0.12",
            equity_before="10014",
            equity_after="10011",
            holding_ms=4_000,
        ),
    )


def equity_fact(suffix: str, *, timestamp_ms: int, equity: str) -> AccountEquityFact:
    return AccountEquityFact(
        replay_run_id="run-1",
        account_state_id=f"state-{suffix}",
        timestamp_ms=timestamp_ms,
        kind=EquityFactKind.MARK,
        equity=Decimal(equity),
        cash=Decimal(equity),
        unrealized_pnl=Decimal("0"),
        realized_gross_pnl=Decimal("0"),
        cumulative_fees=Decimal("0"),
        cumulative_funding=Decimal("0"),
        gross_open_notional=Decimal("0"),
        open_position_count=0,
    )


def test_cost_aware_trade_metrics_are_exact_and_context_independent() -> None:
    items = fixture_samples()
    expected = compute_performance_metrics(items)

    with localcontext(Context(prec=5, rounding=ROUND_UP)):
        hostile = compute_performance_metrics(tuple(reversed(items)))

    assert hostile == expected
    assert expected.trade_count == 4
    assert expected.covered_days == 4
    assert expected.gross_pnl == Decimal("16")
    assert expected.total_fees == Decimal("5")
    assert expected.funding_cash_pnl == Decimal("0")
    assert expected.signed_slippage_amount == Decimal("0.9")
    assert expected.net_pnl == Decimal("11")
    assert expected.total_net_r == Decimal("0.44")
    assert expected.mean_net_r == Decimal("0.11")
    assert expected.median_net_r == Decimal("0.04")
    assert expected.win_rate == Decimal("0.5")
    assert expected.average_winner_r == Decimal("0.44")
    assert expected.average_loser_r == Decimal("-0.22")
    assert expected.profit_factor == Decimal("2")
    assert expected.profit_factor_unavailable_reason is None
    assert expected.largest_winner_r == Decimal("0.68")
    assert expected.largest_loser_r == Decimal("-0.32")
    assert expected.p05_net_r == Decimal("-0.32")
    assert expected.expected_shortfall_5pct == Decimal("-0.32")
    assert expected.median_holding_duration_ms == 2_500
    assert expected.p95_holding_duration_ms == 4_000


def test_all_winning_set_marks_profit_factor_unavailable_instead_of_infinity() -> None:
    winners = tuple(item for item in fixture_samples() if item.net_pnl > 0)

    metrics = compute_performance_metrics(winners)

    assert metrics.profit_factor is None
    assert metrics.profit_factor_unavailable_reason == "NO_LOSING_TRADES"


def test_realized_closed_trade_drawdown_uses_realized_equity_path() -> None:
    metrics = compute_performance_metrics(fixture_samples())

    with localcontext(Context(prec=28)):
        expected = Decimal("8") / Decimal("10017")
    assert metrics.realized_closed_trade_max_drawdown_fraction == expected
    assert metrics.account_equity_max_drawdown_fraction is None
    assert metrics.account_drawdown_unavailable_reason == "INCOMPLETE_EQUITY_CURVE"


def test_complete_genuine_account_equity_curve_has_distinct_mark_to_market_drawdown() -> None:
    facts = (
        equity_fact("a", timestamp_ms=1_000, equity="10000"),
        equity_fact("b", timestamp_ms=2_000, equity="10200"),
        equity_fact("c", timestamp_ms=3_000, equity="9690"),
        equity_fact("d", timestamp_ms=4_000, equity="10000"),
    )

    metrics = compute_performance_metrics(
        fixture_samples(),
        equity_facts=tuple(reversed(facts)),
        equity_curve_complete=True,
    )

    assert metrics.account_equity_max_drawdown_fraction == Decimal("0.05")
    assert metrics.account_drawdown_unavailable_reason is None


def test_incomplete_equity_curve_never_substitutes_realized_drawdown() -> None:
    metrics = compute_performance_metrics(
        fixture_samples(),
        equity_facts=(equity_fact("a", timestamp_ms=1_000, equity="10000"),),
        equity_curve_complete=False,
    )

    assert metrics.realized_closed_trade_max_drawdown_fraction is not None
    assert metrics.account_equity_max_drawdown_fraction is None
    assert metrics.account_drawdown_unavailable_reason == "INCOMPLETE_EQUITY_CURVE"


def test_positive_pnl_concentration_is_grouped_by_market_strategy_and_seven_day_bucket() -> None:
    items = (
        sample(
            "a",
            market=SOL,
            lead_strategy="trend",
            day=0,
            gross_pnl="6",
            entry_fee="0.5",
            exit_fee="0.5",
            funding="0",
            net_pnl="5",
            net_r="0.5",
            equity_before="10000",
            equity_after="10005",
            holding_ms=1_000,
        ),
        sample(
            "b",
            market=ETH,
            lead_strategy="breakout",
            day=7,
            gross_pnl="4",
            entry_fee="0.5",
            exit_fee="0.5",
            funding="0",
            net_pnl="3",
            net_r="0.3",
            equity_before="10005",
            equity_after="10008",
            holding_ms=1_000,
        ),
        sample(
            "c",
            market=ETH,
            lead_strategy="breakout",
            day=8,
            gross_pnl="3",
            entry_fee="0.5",
            exit_fee="0.5",
            funding="0",
            net_pnl="2",
            net_r="0.2",
            equity_before="10008",
            equity_after="10010",
            holding_ms=1_000,
        ),
    )

    metrics = compute_performance_metrics(items)

    assert metrics.max_market_positive_pnl_share == Decimal("0.5")
    assert metrics.max_strategy_positive_pnl_share == Decimal("0.5")
    assert metrics.max_seven_day_positive_pnl_share == Decimal("0.5")
