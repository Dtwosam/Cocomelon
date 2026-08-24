from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.evaluation import (
    AccountEquityFact,
    PerformanceMetrics,
    TradeEvaluationSample,
)

ZERO = Decimal("0")
ONE = Decimal("1")
DAY_MS = 86_400_000
SEVEN_DAYS_MS = 7 * DAY_MS
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


def _sum_decimal(values: Sequence[Decimal]) -> Decimal:
    with localcontext(AUTHORITATIVE_CONTEXT):
        return sum(values, ZERO)


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    with localcontext(AUTHORITATIVE_CONTEXT):
        return _sum_decimal(values) / Decimal(len(values))


def _median_decimal(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return ZERO
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    with localcontext(AUTHORITATIVE_CONTEXT):
        return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _median_int(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) // 2


def _nearest_rank_index(sample_size: int, numerator: int, denominator: int) -> int:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    rank = (numerator * sample_size + denominator - 1) // denominator
    return max(0, rank - 1)


def _max_drawdown_fraction(equities: Sequence[Decimal]) -> Decimal | None:
    if not equities:
        return None
    peak = equities[0]
    maximum = ZERO
    with localcontext(AUTHORITATIVE_CONTEXT):
        for equity in equities:
            if equity > peak:
                peak = equity
                continue
            if peak <= ZERO:
                raise ValueError("equity curve values must remain positive")
            drawdown = (peak - equity) / peak
            if drawdown > maximum:
                maximum = drawdown
    return maximum


def _realized_drawdown(samples: Sequence[TradeEvaluationSample]) -> Decimal | None:
    if not samples:
        return None
    ordered = sorted(samples, key=lambda item: (item.closed_at_ms, item.trade_id))
    running = ordered[0].equity_before
    equities: list[Decimal] = [running]
    with localcontext(AUTHORITATIVE_CONTEXT):
        for item in ordered:
            running += item.net_pnl
            if running <= ZERO:
                raise ValueError("realized closed-trade equity must remain positive")
            equities.append(running)
    return _max_drawdown_fraction(equities)


def _account_drawdown(
    equity_facts: Sequence[AccountEquityFact],
    *,
    equity_curve_complete: bool,
) -> tuple[Decimal | None, str | None]:
    if not equity_curve_complete:
        return None, "INCOMPLETE_EQUITY_CURVE"
    if not equity_facts:
        return None, "NO_EQUITY_FACTS"
    ordered = sorted(equity_facts, key=lambda item: (item.timestamp_ms, item.fact_id))
    return _max_drawdown_fraction(tuple(item.equity for item in ordered)), None


def _positive_group_concentration(
    samples: Sequence[TradeEvaluationSample],
    *,
    key: str,
) -> Decimal | None:
    grouped: dict[object, Decimal] = defaultdict(lambda: ZERO)
    with localcontext(AUTHORITATIVE_CONTEXT):
        for item in samples:
            if key == "market":
                group_key: object = item.market.canonical
            elif key == "strategy":
                group_key = item.lead_strategy
            elif key == "seven_day":
                group_key = item.closed_at_ms // SEVEN_DAYS_MS
            else:
                raise ValueError(f"unsupported concentration key: {key}")
            grouped[group_key] += item.net_pnl

        positive = tuple(value for value in grouped.values() if value > ZERO)
        if not positive:
            return None
        denominator = sum(positive, ZERO)
        if denominator <= ZERO:
            return None
        return max(positive) / denominator


def compute_performance_metrics(
    samples: Sequence[TradeEvaluationSample],
    *,
    equity_facts: Sequence[AccountEquityFact] = (),
    equity_curve_complete: bool = False,
) -> PerformanceMetrics:
    ordered = tuple(sorted(samples, key=lambda item: (item.closed_at_ms, item.trade_id)))
    net_rs = tuple(item.net_r for item in ordered)
    winners = tuple(item for item in ordered if item.net_pnl > ZERO)
    losers = tuple(item for item in ordered if item.net_pnl < ZERO)

    gross_pnl = _sum_decimal(tuple(item.gross_realized_pnl for item in ordered))
    total_fees = _sum_decimal(
        tuple(item.entry_fees + item.exit_fees for item in ordered)
    )
    funding_cash_pnl = _sum_decimal(tuple(item.funding_cash_pnl for item in ordered))
    signed_slippage_amount = _sum_decimal(
        tuple(item.entry_slippage_amount + item.exit_slippage_amount for item in ordered)
    )
    net_pnl = _sum_decimal(tuple(item.net_pnl for item in ordered))
    total_net_r = _sum_decimal(net_rs)
    mean_net_r = _mean(net_rs)
    median_net_r = _median_decimal(net_rs)

    with localcontext(AUTHORITATIVE_CONTEXT):
        win_rate = ZERO if not ordered else Decimal(len(winners)) / Decimal(len(ordered))

    average_winner_r = _mean(tuple(item.net_r for item in winners)) if winners else None
    average_loser_r = _mean(tuple(item.net_r for item in losers)) if losers else None
    largest_winner_r = max((item.net_r for item in winners), default=None)
    largest_loser_r = min((item.net_r for item in losers), default=None)

    if not ordered:
        profit_factor = None
        profit_factor_reason = "NO_TRADES"
    elif not losers:
        profit_factor = None
        profit_factor_reason = "NO_LOSING_TRADES"
    else:
        positive_pnl = _sum_decimal(tuple(item.net_pnl for item in winners))
        negative_pnl = _sum_decimal(tuple(item.net_pnl for item in losers))
        with localcontext(AUTHORITATIVE_CONTEXT):
            profit_factor = positive_pnl / abs(negative_pnl)
        profit_factor_reason = None

    if net_rs:
        ordered_rs = sorted(net_rs)
        tail_index = _nearest_rank_index(len(ordered_rs), 5, 100)
        p05_net_r = ordered_rs[tail_index]
        expected_shortfall_5pct = _mean(ordered_rs[: tail_index + 1])
    else:
        p05_net_r = None
        expected_shortfall_5pct = None

    durations = tuple(item.holding_duration_ms for item in ordered)
    median_holding_duration_ms = _median_int(durations)
    if durations:
        ordered_durations = sorted(durations)
        p95_holding_duration_ms = ordered_durations[
            _nearest_rank_index(len(ordered_durations), 95, 100)
        ]
    else:
        p95_holding_duration_ms = None

    realized_drawdown = _realized_drawdown(ordered)
    account_drawdown, account_drawdown_reason = _account_drawdown(
        equity_facts,
        equity_curve_complete=equity_curve_complete,
    )

    return PerformanceMetrics(
        trade_count=len(ordered),
        covered_days=len({item.closed_at_ms // DAY_MS for item in ordered}),
        gross_pnl=gross_pnl,
        total_fees=total_fees,
        funding_cash_pnl=funding_cash_pnl,
        signed_slippage_amount=signed_slippage_amount,
        net_pnl=net_pnl,
        total_net_r=total_net_r,
        mean_net_r=mean_net_r,
        median_net_r=median_net_r,
        win_rate=win_rate,
        average_winner_r=average_winner_r,
        average_loser_r=average_loser_r,
        profit_factor=profit_factor,
        profit_factor_unavailable_reason=profit_factor_reason,
        largest_winner_r=largest_winner_r,
        largest_loser_r=largest_loser_r,
        p05_net_r=p05_net_r,
        expected_shortfall_5pct=expected_shortfall_5pct,
        median_holding_duration_ms=median_holding_duration_ms,
        p95_holding_duration_ms=p95_holding_duration_ms,
        realized_closed_trade_max_drawdown_fraction=realized_drawdown,
        account_equity_max_drawdown_fraction=account_drawdown,
        account_drawdown_unavailable_reason=account_drawdown_reason,
        max_market_positive_pnl_share=_positive_group_concentration(
            ordered,
            key="market",
        ),
        max_strategy_positive_pnl_share=_positive_group_concentration(
            ordered,
            key="strategy",
        ),
        max_seven_day_positive_pnl_share=_positive_group_concentration(
            ordered,
            key="seven_day",
        ),
    )
