from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore

ZERO: Final = Decimal("0")


class ClosedTradeFrictionError(RuntimeError):
    pass


def _decision_fact(
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
        raise ClosedTradeFrictionError(
            "friction decision market does not match trade"
        )
    if fact.direction is not trade.direction:
        raise ClosedTradeFrictionError(
            "friction decision direction does not match trade"
        )
    if fact.feature_snapshot_id != trade.feature_snapshot_id:
        raise ClosedTradeFrictionError(
            "friction feature lineage does not match trade"
        )
    return fact


def _trade_reference_gross(trade: TradeJournalEntry) -> Decimal:
    return (
        trade.gross_realized_pnl
        + trade.entry_slippage_amount
        + trade.exit_slippage_amount
    )


def _trade_signed_slippage(trade: TradeJournalEntry) -> Decimal:
    return trade.entry_slippage_amount + trade.exit_slippage_amount


def _group_summary(
    trades: Sequence[TradeJournalEntry],
) -> dict[str, object]:
    items = tuple(trades)
    count = len(items)
    if not items:
        return {
            "trades": 0,
            "reference_gross_pnl": "0",
            "signed_slippage_amount": "0",
            "adverse_slippage_amount": "0",
            "favorable_slippage_amount": "0",
            "actual_gross_realized_pnl": "0",
            "fees": "0",
            "funding_cash_pnl": "0",
            "net_pnl": "0",
            "net_cost_drag": "0",
            "reference_gross_positive_trades": 0,
            "actual_gross_positive_trades": 0,
            "net_positive_trades": 0,
            "friction_flipped_trades": 0,
            "fee_funding_flipped_trades": 0,
            "friction_rescued_trades": 0,
            "mean_reference_gross_r": None,
            "mean_slippage_drag_r": None,
            "mean_fee_drag_r": None,
            "mean_funding_r": None,
            "mean_net_r": None,
            "mean_net_cost_drag_r": None,
        }

    reference_gross = sum(
        (_trade_reference_gross(trade) for trade in items),
        ZERO,
    )
    signed_slippage = sum(
        (_trade_signed_slippage(trade) for trade in items),
        ZERO,
    )
    adverse_slippage = sum(
        (
            max(ZERO, trade.entry_slippage_amount)
            + max(ZERO, trade.exit_slippage_amount)
            for trade in items
        ),
        ZERO,
    )
    favorable_slippage = sum(
        (
            abs(min(ZERO, trade.entry_slippage_amount))
            + abs(min(ZERO, trade.exit_slippage_amount))
            for trade in items
        ),
        ZERO,
    )
    actual_gross = sum(
        (trade.gross_realized_pnl for trade in items),
        ZERO,
    )
    fees = sum(
        (trade.entry_fees + trade.exit_fees for trade in items),
        ZERO,
    )
    funding = sum(
        (trade.funding_cash_pnl for trade in items),
        ZERO,
    )
    net_pnl = sum((trade.net_pnl for trade in items), ZERO)

    expected_actual_gross = reference_gross - signed_slippage
    expected_net = actual_gross - fees + funding
    if expected_actual_gross != actual_gross:
        raise ClosedTradeFrictionError(
            "reference gross does not reconcile through slippage"
        )
    if expected_net != net_pnl:
        raise ClosedTradeFrictionError(
            "actual gross does not reconcile to net PnL"
        )

    net_cost_drag = reference_gross - net_pnl
    mean_reference_gross_r = sum(
        (
            _trade_reference_gross(trade)
            / trade.initial_risk_amount
            for trade in items
        ),
        ZERO,
    ) / Decimal(count)
    mean_slippage_drag_r = sum(
        (
            _trade_signed_slippage(trade)
            / trade.initial_risk_amount
            for trade in items
        ),
        ZERO,
    ) / Decimal(count)
    mean_fee_drag_r = sum(
        (
            (trade.entry_fees + trade.exit_fees)
            / trade.initial_risk_amount
            for trade in items
        ),
        ZERO,
    ) / Decimal(count)
    mean_funding_r = sum(
        (
            trade.funding_cash_pnl / trade.initial_risk_amount
            for trade in items
        ),
        ZERO,
    ) / Decimal(count)
    mean_net_r = sum(
        (trade.net_r for trade in items),
        ZERO,
    ) / Decimal(count)
    mean_net_cost_drag_r = (
        mean_slippage_drag_r
        + mean_fee_drag_r
        - mean_funding_r
    )
    if (
        mean_reference_gross_r - mean_net_cost_drag_r
        != mean_net_r
    ):
        raise ClosedTradeFrictionError(
            "mean R friction decomposition does not reconcile"
        )

    return {
        "trades": count,
        "reference_gross_pnl": str(reference_gross),
        "signed_slippage_amount": str(signed_slippage),
        "adverse_slippage_amount": str(adverse_slippage),
        "favorable_slippage_amount": str(favorable_slippage),
        "actual_gross_realized_pnl": str(actual_gross),
        "fees": str(fees),
        "funding_cash_pnl": str(funding),
        "net_pnl": str(net_pnl),
        "net_cost_drag": str(net_cost_drag),
        "reference_gross_positive_trades": sum(
            1
            for trade in items
            if _trade_reference_gross(trade) > ZERO
        ),
        "actual_gross_positive_trades": sum(
            1 for trade in items if trade.gross_realized_pnl > ZERO
        ),
        "net_positive_trades": sum(
            1 for trade in items if trade.net_pnl > ZERO
        ),
        "friction_flipped_trades": sum(
            1
            for trade in items
            if _trade_reference_gross(trade) > ZERO
            and trade.net_pnl <= ZERO
        ),
        "fee_funding_flipped_trades": sum(
            1
            for trade in items
            if trade.gross_realized_pnl > ZERO
            and trade.net_pnl <= ZERO
        ),
        "friction_rescued_trades": sum(
            1
            for trade in items
            if _trade_reference_gross(trade) <= ZERO
            and trade.net_pnl > ZERO
        ),
        "mean_reference_gross_r": str(mean_reference_gross_r),
        "mean_slippage_drag_r": str(mean_slippage_drag_r),
        "mean_fee_drag_r": str(mean_fee_drag_r),
        "mean_funding_r": str(mean_funding_r),
        "mean_net_r": str(mean_net_r),
        "mean_net_cost_drag_r": str(mean_net_cost_drag_r),
    }


def closed_trade_friction_summary(
    trades: Sequence[TradeJournalEntry],
    fact_store: EvaluationFactStore,
) -> dict[str, object]:
    items = tuple(trades)
    by_side: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    by_strategy: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    attribution_misses = 0

    for trade in items:
        by_side[trade.direction.value].append(trade)
        fact = _decision_fact(trade, fact_store)
        if fact is None or fact.lead_strategy is None:
            attribution_misses += 1
            by_strategy["unknown"].append(trade)
        else:
            by_strategy[fact.lead_strategy].append(trade)

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "reference_gross_minus_slippage_minus_fees_plus_funding"
        ),
        "decision_fact_attribution_misses": attribution_misses,
        "overall": _group_summary(items),
        "by_side": {
            label: _group_summary(group)
            for label, group in sorted(by_side.items())
        },
        "by_lead_strategy": {
            label: _group_summary(group)
            for label, group in sorted(by_strategy.items())
        },
    }
