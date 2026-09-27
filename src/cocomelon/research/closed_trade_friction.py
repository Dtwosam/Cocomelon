from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)

ZERO: Final = Decimal("0")
MAX_FRICTION_RANK_AGE_MS: Final = 300_000


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


def _rank_bucket(ordinal: int) -> str:
    if ordinal <= 0:
        raise ValueError("scanner rank ordinal must be positive")
    if ordinal <= 5:
        return "1-5"
    if ordinal <= 10:
        return "6-10"
    if ordinal <= 20:
        return "11-20"
    return "21+"


def _fresh_rank_bucket(
    trade: TradeJournalEntry,
    rank_store: ContinuousPaperOpeningRankStore,
) -> tuple[str | None, str | None]:
    evidence = rank_store.load(trade.opening_plan_id)
    if evidence is None:
        return None, "missing"
    if (
        evidence.market != trade.market.canonical
        or evidence.opened_at_ms != trade.opened_at_ms
    ):
        raise ClosedTradeFrictionError(
            "friction opening-rank evidence does not match trade"
        )
    if evidence.rank_age_ms > MAX_FRICTION_RANK_AGE_MS:
        return None, "stale"
    return _rank_bucket(evidence.ordinal), None


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
    reference_gross = actual_gross + signed_slippage
    net_cost_drag = reference_gross - net_pnl
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
    mean_reference_gross_r = (
        mean_net_r + mean_net_cost_drag_r
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
    rank_store: ContinuousPaperOpeningRankStore | None = None,
) -> dict[str, object]:
    items = tuple(trades)
    by_side: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    by_strategy: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    by_rank: dict[str, list[TradeJournalEntry]] = defaultdict(list)
    attribution_misses = 0
    fresh_rank_attributions = 0
    missing_rank_evidence = 0
    stale_rank_evidence = 0

    for trade in items:
        by_side[trade.direction.value].append(trade)
        fact = _decision_fact(trade, fact_store)
        if fact is None or fact.lead_strategy is None:
            attribution_misses += 1
            by_strategy["unknown"].append(trade)
        else:
            by_strategy[fact.lead_strategy].append(trade)

        if rank_store is not None:
            bucket, rank_error = _fresh_rank_bucket(
                trade,
                rank_store,
            )
            if rank_error == "missing":
                missing_rank_evidence += 1
            elif rank_error == "stale":
                stale_rank_evidence += 1
            elif bucket is not None:
                fresh_rank_attributions += 1
                by_rank[bucket].append(trade)

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "definition": (
            "reference_gross_minus_slippage_minus_fees_plus_funding"
        ),
        "decision_fact_attribution_misses": attribution_misses,
        "opening_rank_attribution": {
            "enabled": rank_store is not None,
            "max_rank_age_ms": MAX_FRICTION_RANK_AGE_MS,
            "fresh_attributed_trades": fresh_rank_attributions,
            "missing_rank_evidence": missing_rank_evidence,
            "stale_rank_evidence": stale_rank_evidence,
        },
        "overall": _group_summary(items),
        "by_side": {
            label: _group_summary(group)
            for label, group in sorted(by_side.items())
        },
        "by_lead_strategy": {
            label: _group_summary(group)
            for label, group in sorted(by_strategy.items())
        },
        "by_scanner_rank_bucket": {
            label: _group_summary(group)
            for label, group in sorted(by_rank.items())
        },
    }
