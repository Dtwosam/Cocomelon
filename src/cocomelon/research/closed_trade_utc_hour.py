from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore

ZERO: Final = Decimal("0")
HOUR_MS: Final = 3_600_000
AUTHORITATIVE_CONTEXT: Final = Context(
    prec=28,
    rounding=ROUND_HALF_EVEN,
)


class ClosedTradeUtcHourError(RuntimeError):
    pass


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext(AUTHORITATIVE_CONTEXT):
        return sum(values, ZERO)


def _fact_for_trade(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
) -> DecisionEvaluationFact | None:
    if trade.replay_run_id is None:
        return None
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        trade.replay_run_id,
    )
    if fact is None:
        return None
    if fact.market != trade.market:
        raise ClosedTradeUtcHourError(
            "UTC-hour decision market does not match trade"
        )
    if fact.direction is not trade.direction:
        raise ClosedTradeUtcHourError(
            "UTC-hour decision direction does not match trade"
        )
    if fact.feature_snapshot_id != trade.feature_snapshot_id:
        raise ClosedTradeUtcHourError(
            "UTC-hour decision feature lineage does not match trade"
        )
    return fact


def _profit_factor(
    trades: tuple[TradeJournalEntry, ...],
) -> Decimal | None:
    gross_profit = _sum(
        tuple(trade.net_pnl for trade in trades if trade.net_pnl > ZERO)
    )
    gross_loss = -_sum(
        tuple(trade.net_pnl for trade in trades if trade.net_pnl < ZERO)
    )
    if gross_loss <= ZERO:
        return None
    with localcontext(AUTHORITATIVE_CONTEXT):
        return gross_profit / gross_loss


def _summary(
    trades: tuple[TradeJournalEntry, ...],
) -> dict[str, object]:
    count = len(trades)
    net_pnl = _sum(tuple(trade.net_pnl for trade in trades))
    total_net_r = _sum(tuple(trade.net_r for trade in trades))
    wins = sum(1 for trade in trades if trade.net_pnl > ZERO)
    losses = sum(1 for trade in trades if trade.net_pnl < ZERO)
    breakeven = count - wins - losses
    with localcontext(AUTHORITATIVE_CONTEXT):
        mean_net_r = (
            None
            if count == 0
            else total_net_r / Decimal(count)
        )
        win_rate = (
            None
            if count == 0
            else Decimal(wins) / Decimal(count)
        )
    profit_factor = _profit_factor(trades)
    return {
        "trades": count,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "net_pnl": str(net_pnl),
        "mean_net_r": (
            None if mean_net_r is None else str(mean_net_r)
        ),
        "win_rate": None if win_rate is None else str(win_rate),
        "profit_factor": (
            None if profit_factor is None else str(profit_factor)
        ),
    }


def closed_trade_utc_hour_summary(
    trades: tuple[TradeJournalEntry, ...],
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    ordered = tuple(
        sorted(
            trades,
            key=lambda trade: (trade.closed_at_ms, trade.trade_id),
        )
    )
    grouped: dict[int, list[TradeJournalEntry]] = defaultdict(list)
    attributed = 0
    attribution_misses = 0

    for trade in ordered:
        fact = _fact_for_trade(trade, fact_store)
        if fact is None:
            attribution_misses += 1
            continue
        hour = (fact.timestamp_ms // HOUR_MS) % 24
        grouped[hour].append(trade)
        attributed += 1

    rows: list[dict[str, object]] = []
    for hour in sorted(grouped):
        trades_for_hour = tuple(grouped[hour])
        row = _summary(trades_for_hour)
        row["utc_hour"] = hour
        row["label"] = f"{hour:02d}:00-{hour:02d}:59"
        with localcontext(AUTHORITATIVE_CONTEXT):
            row["trade_count_share"] = str(
                Decimal(len(trades_for_hour)) / Decimal(attributed)
            )
        rows.append(row)

    trade_shares = tuple(
        Decimal(str(row["trade_count_share"]))
        for row in rows
    )
    with localcontext(AUTHORITATIVE_CONTEXT):
        trade_count_hhi = (
            None
            if not trade_shares
            else sum(
                (share * share for share in trade_shares),
                ZERO,
            )
        )

    positive_hours = tuple(
        row
        for row in rows
        if Decimal(str(row["net_pnl"])) > ZERO
    )
    negative_hours = tuple(
        row
        for row in rows
        if Decimal(str(row["net_pnl"])) < ZERO
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": "strategy_decision_timestamp_utc_hour",
        "closed_trades": len(ordered),
        "attributed_trades": attributed,
        "attribution_misses": attribution_misses,
        "active_utc_hours": len(rows),
        "positive_net_pnl_hours": len(positive_hours),
        "negative_net_pnl_hours": len(negative_hours),
        "trade_count_hhi": (
            None
            if trade_count_hhi is None
            else str(trade_count_hhi)
        ),
        "rows": rows,
    }
