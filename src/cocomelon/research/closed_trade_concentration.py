from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.engine import (
    MARKET_CONCENTRATION_LIMIT,
    SEVEN_DAY_CONCENTRATION_LIMIT,
)
from cocomelon.evaluation.store import EvaluationFactStore

ZERO: Final = Decimal("0")
SEVEN_DAYS_MS: Final = 7 * 86_400_000
MIN_CLOSED_TRADES_FOR_REVIEW: Final = 30


class ClosedTradeConcentrationError(RuntimeError):
    pass


def _lead_strategy(
    trade: TradeJournalEntry,
    fact_store: EvaluationFactStore,
) -> str | None:
    if trade.replay_run_id is None:
        return None
    fact = fact_store.load_decision_by_strategy_id(
        trade.strategy_decision_id,
        trade.replay_run_id,
    )
    if fact is None:
        return None
    if (
        fact.market != trade.market
        or fact.direction is not trade.direction
        or fact.feature_snapshot_id != trade.feature_snapshot_id
    ):
        raise ClosedTradeConcentrationError(
            "concentration decision lineage mismatch"
        )
    return fact.lead_strategy


def _group_payload(
    trades: Sequence[TradeJournalEntry],
    labeler: Callable[[TradeJournalEntry], str],
) -> dict[str, object]:
    pnl_by_group: dict[str, Decimal] = defaultdict(lambda: ZERO)
    count_by_group: dict[str, int] = defaultdict(int)
    wins_by_group: dict[str, int] = defaultdict(int)
    losses_by_group: dict[str, int] = defaultdict(int)

    for trade in trades:
        label = labeler(trade)
        if not label:
            raise ClosedTradeConcentrationError(
                "concentration group label must not be empty"
            )
        pnl_by_group[label] += trade.net_pnl
        count_by_group[label] += 1
        if trade.net_pnl > ZERO:
            wins_by_group[label] += 1
        elif trade.net_pnl < ZERO:
            losses_by_group[label] += 1

    positive_groups = {
        label: pnl
        for label, pnl in pnl_by_group.items()
        if pnl > ZERO
    }
    total_positive_group_pnl = sum(
        positive_groups.values(),
        ZERO,
    )
    rows = []
    for label in sorted(
        pnl_by_group,
        key=lambda item: (
            pnl_by_group[item],
            item,
        ),
        reverse=True,
    ):
        pnl = pnl_by_group[label]
        share = (
            None
            if pnl <= ZERO or total_positive_group_pnl <= ZERO
            else pnl / total_positive_group_pnl
        )
        rows.append(
            {
                "group": label,
                "trades": count_by_group[label],
                "wins": wins_by_group[label],
                "losses": losses_by_group[label],
                "net_pnl": str(pnl),
                "positive_group_pnl_share": (
                    None if share is None else str(share)
                ),
            }
        )

    max_positive_label: str | None = None
    max_positive_share: Decimal | None = None
    if positive_groups and total_positive_group_pnl > ZERO:
        max_positive_label = max(
            positive_groups,
            key=lambda item: (
                positive_groups[item],
                item,
            ),
        )
        max_positive_share = (
            positive_groups[max_positive_label]
            / total_positive_group_pnl
        )

    return {
        "groups": rows,
        "group_count": len(rows),
        "positive_group_count": len(positive_groups),
        "total_positive_group_pnl": str(
            total_positive_group_pnl
        ),
        "max_positive_group": max_positive_label,
        "max_positive_pnl_share": (
            None
            if max_positive_share is None
            else str(max_positive_share)
        ),
    }


def closed_trade_concentration(
    trades: Sequence[TradeJournalEntry],
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    items = tuple(
        sorted(
            trades,
            key=lambda trade: (
                trade.closed_at_ms,
                trade.trade_id,
            ),
        )
    )
    strategies: dict[str, str] = {}
    strategy_misses = 0
    for trade in items:
        strategy = _lead_strategy(trade, fact_store)
        if strategy is None:
            strategy_misses += 1
            strategy = "unknown"
        strategies[trade.trade_id] = strategy

    market = _group_payload(
        items,
        lambda trade: trade.market.canonical,
    )
    strategy = _group_payload(
        items,
        lambda trade: strategies[trade.trade_id],
    )
    seven_day = _group_payload(
        items,
        lambda trade: str(
            (trade.closed_at_ms // SEVEN_DAYS_MS)
            * SEVEN_DAYS_MS
        ),
    )

    market_share_raw = market["max_positive_pnl_share"]
    market_share = (
        None
        if market_share_raw is None
        else Decimal(str(market_share_raw))
    )
    seven_day_share_raw = seven_day["max_positive_pnl_share"]
    seven_day_share = (
        None
        if seven_day_share_raw is None
        else Decimal(str(seven_day_share_raw))
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "group_net_pnl_then_share_of_positive_group_pnl"
        ),
        "closed_trades": len(items),
        "strategy_attribution_misses": strategy_misses,
        "market": {
            **market,
            "formal_limit": str(MARKET_CONCENTRATION_LIMIT),
            "within_formal_limit_current_sample": (
                None
                if market_share is None
                else market_share <= MARKET_CONCENTRATION_LIMIT
            ),
        },
        "lead_strategy": strategy,
        "seven_day": {
            **seven_day,
            "formal_limit": str(
                SEVEN_DAY_CONCENTRATION_LIMIT
            ),
            "within_formal_limit_current_sample": (
                None
                if seven_day_share is None
                else seven_day_share
                <= SEVEN_DAY_CONCENTRATION_LIMIT
            ),
        },
        "readiness": {
            "min_closed_trades": MIN_CLOSED_TRADES_FOR_REVIEW,
            "missing_closed_trades": max(
                0,
                MIN_CLOSED_TRADES_FOR_REVIEW - len(items),
            ),
            "ready_for_review": (
                len(items) >= MIN_CLOSED_TRADES_FOR_REVIEW
            ),
        },
    }
