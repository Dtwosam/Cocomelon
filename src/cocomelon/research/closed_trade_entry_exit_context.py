from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)
from cocomelon.research.loss_streak_context_audit import (
    try_resolve_entry_context_row,
)

ZERO: Final = Decimal("0")
EARLY_MOVE_R: Final = Decimal("0.25")
GIVEBACK_R: Final = Decimal("0.5")
UNKNOWN_CONTEXT: Final = "historical_context_unavailable"


class ClosedTradeEntryExitContextError(RuntimeError):
    pass


def _complete_mfe_r(trade: TradeJournalEntry) -> Decimal | None:
    if (
        trade.mfe is None
        or trade.mae is None
        or not trade.mfe.complete
        or not trade.mae.complete
        or trade.mfe.r_multiple is None
        or trade.mae.r_multiple is None
    ):
        return None
    return trade.mfe.r_multiple


def _cohort(trades: Sequence[TradeJournalEntry]) -> dict[str, object]:
    ordered = sorted(trades, key=lambda t: (t.closed_at_ms, t.trade_id))
    count = len(ordered)
    gross = sum((t.gross_realized_pnl for t in ordered), ZERO)
    fees = sum((t.entry_fees + t.exit_fees for t in ordered), ZERO)
    funding = sum((t.funding_cash_pnl for t in ordered), ZERO)
    net = sum((t.net_pnl for t in ordered), ZERO)
    winners = [t for t in ordered if t.net_pnl > ZERO]
    losers = [t for t in ordered if t.net_pnl < ZERO]
    stopped = [t for t in ordered if t.exit_reason == "MARK_STOP_TRIGGERED"]
    stopped_loss = [t for t in stopped if t.net_pnl < ZERO]
    known = [t for t in ordered if _complete_mfe_r(t) is not None]
    no_favorable_move = [
        t for t in losers
        if (mfe := _complete_mfe_r(t)) is not None and mfe < EARLY_MOVE_R
    ]
    gave_back = [
        t for t in losers
        if (mfe := _complete_mfe_r(t)) is not None and mfe >= GIVEBACK_R
    ]
    ambiguous_losers = [
        t for t in losers
        if (mfe := _complete_mfe_r(t)) is not None
        and EARLY_MOVE_R <= mfe < GIVEBACK_R
    ]
    unknown_losers = [t for t in losers if _complete_mfe_r(t) is None]
    best_winner = max((t.net_pnl for t in winners), default=ZERO)
    midpoint = count // 2
    early = sum((t.net_pnl for t in ordered[:midpoint]), ZERO)
    late = sum((t.net_pnl for t in ordered[midpoint:]), ZERO)
    return {
        "trades": count,
        "distinct_markets": len({t.market.canonical for t in ordered}),
        "wins_after_costs": len(winners),
        "losses_after_costs": len(losers),
        "gross_realized_pnl": str(gross),
        "fees_paid": str(fees),
        "funding_cash_pnl": str(funding),
        "net_pnl": str(net),
        "net_reconciliation_residual": str(net - (gross - fees + funding)),
        "mark_stop_exits": len(stopped),
        "mark_stop_losing_exits": len(stopped_loss),
        "mark_stop_loser_net_pnl": str(sum(
            (t.net_pnl for t in stopped_loss), ZERO
        )),
        "full_excursion_trades": len(known),
        "unknown_excursion_trades": count - len(known),
        "losses_no_0_25r_favorable_move": len(no_favorable_move),
        "losses_no_0_25r_favorable_move_net_pnl": str(sum(
            (t.net_pnl for t in no_favorable_move), ZERO
        )),
        "losses_after_0_5r_favorable_move": len(gave_back),
        "losses_after_0_5r_favorable_move_net_pnl": str(sum(
            (t.net_pnl for t in gave_back), ZERO
        )),
        "losses_between_0_25_and_0_5r_favorable": len(ambiguous_losers),
        "losing_trades_missing_excursion": len(unknown_losers),
        "gross_winners_flipped_negative_by_costs": sum(
            t.gross_realized_pnl > ZERO and t.net_pnl <= ZERO
            for t in ordered
        ),
        "chronological_first_half_net_pnl": str(early),
        "chronological_second_half_net_pnl": str(late),
        "net_without_largest_winner": str(net - best_winner),
        "retrospective_only_no_execution_authority": True,
    }


def closed_trade_entry_exit_context(
    trades: Sequence[TradeJournalEntry],
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
) -> dict[str, object]:
    """Attribute the entire closed journal to verified, pre-entry market conditions.

    Excursion/exit fields diagnose completed trades ONLY. None are
    features permitted in the entry strategy or future-conditioned signals.
    """
    ordered = tuple(sorted(
        trades, key=lambda t: (t.closed_at_ms, t.trade_id)
    ))
    if len({t.trade_id for t in ordered}) != len(ordered):
        raise ClosedTradeEntryExitContextError("duplicate closed trade ID")

    dimensions: dict[str, dict[str, list[TradeJournalEntry]]] = {
        "by_side_and_entry_rank": defaultdict(list),
        "by_side_strategy_and_rank": defaultdict(list),
        "by_side_and_15m_return": defaultdict(list),
        "by_side_and_1h_return": defaultdict(list),
        "by_side_and_entry_regime": defaultdict(list),
        "by_side_and_exit_reason": defaultdict(list),
    }
    unresolved: Counter[str] = Counter()
    context_by_trade: dict[str, dict[str, object] | None] = {}
    for trade in ordered:
        context, reason = try_resolve_entry_context_row(
            trade, facts, features, ranks
        )
        context_by_trade[trade.trade_id] = context
        if context is None:
            unresolved[reason or "unknown attribution error"] += 1
            lead = rank = return15 = return1h = regime = UNKNOWN_CONTEXT
        else:
            lead = str(context["lead_strategy"])
            rank = str(context["rank_band"])
            return15 = str(context["return_15m_sign"])
            return1h = str(context["return_1h_sign"])
            regime = (
                str(context["trend_regime"])
                + " | "
                + str(context["volatility_regime"])
            )

        side = trade.direction.value
        dimensions["by_side_and_entry_rank"][f"{side} | {rank}"].append(trade)
        dimensions["by_side_strategy_and_rank"][
            f"{side} | {lead} | {rank}"
        ].append(trade)
        dimensions["by_side_and_15m_return"][
            f"{side} | {return15}"
        ].append(trade)
        dimensions["by_side_and_1h_return"][
            f"{side} | {return1h}"
        ].append(trade)
        dimensions["by_side_and_entry_regime"][
            f"{side} | {regime}"
        ].append(trade)
        dimensions["by_side_and_exit_reason"][
            f"{side} | {trade.exit_reason}"
        ].append(trade)

    overall = _cohort(ordered)
    by_dimension = {
        dimension: {
            label: _cohort(members)
            for label, members in sorted(groups.items())
        }
        for dimension, groups in dimensions.items()
    }
    for dimension, groups in by_dimension.items():
        count = sum(int(group["trades"]) for group in groups.values())
        net = sum((Decimal(str(group["net_pnl"])) for group in groups.values()), ZERO)
        if count != len(ordered) or net != Decimal(str(overall["net_pnl"])):
            raise ClosedTradeEntryExitContextError(
                f"entry context cohort reconciliation failure: {dimension}"
            )
    if sum(unresolved.values()) != sum(
        context is None for context in context_by_trade.values()
    ):
        raise ClosedTradeEntryExitContextError("unresolved context count mismatch")
    return {
        "definition": "verified_at_entry_features_plus_realized_close_and_excursion_v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_positions": False,
        "changes_risk_limits": False,
        "trade_count": len(ordered),
        "entry_context_verified_trades": (
            len(ordered) - sum(unresolved.values())
        ),
        "entry_context_unresolved_trades": sum(unresolved.values()),
        "entry_context_unresolved_reasons": dict(sorted(unresolved.items())),
        "overall": overall,
        "dimensions": by_dimension,
        "entry_context_by_trade_id": context_by_trade,
        "caution": (
            "Only contemporaneously verified decision/feature/rank context is "
            "valid at entry. Missing historical features are not imputed; every "
            "trade remains in each economic cohort. MFE/MAE and holding duration "
            "are post-entry only. Mark favorable excursion is NOT an executable "
            "exit fill. Selection from this audit is hindsight and requires "
            "an independently frozen forward fill-aware paired portfolio trial."
        ),
    }
