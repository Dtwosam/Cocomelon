from __future__ import annotations

from collections.abc import Sequence

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.prospective_profit_target_one_r_comparison import (
    BREAKEVEN_RULE_ID,
    MIN_DIRECTION_TRADES,
    MIN_MARKETS,
    MIN_PAIRED_TRADES,
    MIN_PROFIT_TARGET_FULL_CLOSES,
    MIN_PROFIT_TARGET_TRIGGERS,
    NET_RESERVED_TRAILING_RULE_ID,
    TRAILING_PROFIT_RULE_ID,
    ProspectiveProfitTargetComparisonError,
    _prospective_profit_target_comparison,
    _verified_outcomes,
)
from cocomelon.research.prospective_profit_trailing_grid import _robust_pair


def prospective_net_reserved_trailing_comparison(
    trades: Sequence[TradeJournalEntry],
    net_reserved_state: object,
    original_trailing_state: object,
    breakeven_state: object,
) -> dict[str, object]:
    """Same future IOC-funded trades; no retrospective preferred exit."""
    later_start, later_outcomes, later_meta = _verified_outcomes(
        net_reserved_state, rule_id=NET_RESERVED_TRAILING_RULE_ID
    )
    original_start, original_outcomes, original_meta = _verified_outcomes(
        original_trailing_state, rule_id=TRAILING_PROFIT_RULE_ID
    )
    baseline_start, _, baseline_meta = _verified_outcomes(
        breakeven_state, rule_id=BREAKEVEN_RULE_ID
    )
    if not (
        later_meta["execution_config"]
        == original_meta["execution_config"]
        == baseline_meta["execution_config"]
    ):
        raise ProspectiveProfitTargetComparisonError(
            "net-reserved trailing rules use different execution cost models"
        )
    common_start = max(later_start, original_start, baseline_start)
    reserved_review = _prospective_profit_target_comparison(
        trades,
        net_reserved_state,
        breakeven_state,
        target_rule_id=NET_RESERVED_TRAILING_RULE_ID,
        scoring_started_at_ms=common_start,
    )
    original_review = _prospective_profit_target_comparison(
        trades,
        original_trailing_state,
        breakeven_state,
        target_rule_id=TRAILING_PROFIT_RULE_ID,
        scoring_started_at_ms=common_start,
    )
    future_ids = reserved_review["paired_trade_ids"]
    older_ids = original_review["paired_trade_ids"]
    if not isinstance(future_ids, list) or not isinstance(older_ids, list):
        raise ProspectiveProfitTargetComparisonError(
            "net-reserved comparison lacks matched trade IDs"
        )
    complete = (
        future_ids == older_ids
        and reserved_review["integrity_clean"] is True
        and original_review["integrity_clean"] is True
        and len(future_ids) == reserved_review["prospective_closed_trades"]
        and len(older_ids) == original_review["prospective_closed_trades"]
    )
    paired_review: dict[str, object] | None = None
    strict = False
    if complete:
        trade_map = {trade.trade_id: trade for trade in trades}
        if len(trade_map) != len(trades):
            raise ProspectiveProfitTargetComparisonError(
                "net-reserved comparison journal has duplicate trades"
            )
        rows = []
        for trade_id in future_ids:
            trade = trade_map[trade_id]
            costed = later_outcomes[trade_id]
            uncosted = original_outcomes[trade_id]
            if not (
                costed.opening_plan_id
                == uncosted.opening_plan_id
                == trade.opening_plan_id
            ):
                raise ProspectiveProfitTargetComparisonError(
                    "net-reserved comparison opening plan drift"
                )
            prev_net = uncosted.candidate_net_pnl_estimate
            prev_r = uncosted.candidate_net_r_estimate
            if prev_net is None or prev_r is None:
                raise ProspectiveProfitTargetComparisonError(
                    "incomplete original trailing cashflow"
                )
            rows.append((trade, costed, prev_net, prev_r))
        review = _robust_pair(tuple(rows))
        paired_review = review
        required = (
            len(rows) >= MIN_PAIRED_TRADES
            and len({
                row[0].market.canonical for row in rows
            }) >= MIN_MARKETS
            and all(
                sum(
                    row[0].direction.value == side for row in rows
                ) >= MIN_DIRECTION_TRADES
                for side in ("long", "short")
            )
            and sum(
                row[1].triggered for row in rows
            ) >= MIN_PROFIT_TARGET_TRIGGERS
            and sum(
                row[1].triggered
                and row[1].simulated_close_complete
                for row in rows
            ) >= MIN_PROFIT_TARGET_FULL_CLOSES
        )
        strict = (
            required
            and review["strict_paired_economic_screen_passes"] is True
            and reserved_review["economic_screen_passes"] is True
        )
    return {
        "schema_version": 1,
        "candidate_id": NET_RESERVED_TRAILING_RULE_ID,
        "reference_exit_id": TRAILING_PROFIT_RULE_ID,
        "common_frozen_start_ms": common_start,
        "comparison_scope": "same_fully_filled_future_trades",
        "common_matched_trade_count": len(set(future_ids) & set(older_ids)),
        "same_complete_cohort": complete,
        "cost_reserved_candidate": reserved_review,
        "original_trailing_control": original_review,
        "incremental_robustness": paired_review,
        "strict_incremental_screen_passes": strict,
        "selected_winner": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "account_level_profitability_proven": False,
        "warning": (
            "The net lock is a conservative ex ante IOC reserve, not "
            "a guaranteed executable stop or observed net PnL. "
            "Only subsequent full book fills count as closed returns. "
            "No exit policy is selected from this same-cohort review; "
            "portfolio capital reflow and future displaced entries "
            "require a separate frozen account-level paper trial."
        ),
    }
