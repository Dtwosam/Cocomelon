from __future__ import annotations

from collections.abc import Sequence

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.prospective_profit_target_one_r_comparison import (
    EARLY_RESERVED_TRAILING_RULE_ID,
    _prospective_profit_target_comparison,
)


def prospective_early_reserved_trailing_comparison(
    trades: Sequence[TradeJournalEntry],
    early_trailing_state: object,
    breakeven_state: object,
) -> dict[str, object]:
    """Frozen forward-only IOC exit study, not an account-level backtest.

    Both controls and candidate run in parallel on each future original paper
    position. Only full visible-book IOC closes may claim alternative PnL;
    failed/partial exits block readiness. Both LONG and SHORT need profits,
    multiple markets and robust chronological blocks. Original account is
    never altered or granted execution/promotion authority.
    """
    result = _prospective_profit_target_comparison(
        trades,
        early_trailing_state,
        breakeven_state,
        target_rule_id=EARLY_RESERVED_TRAILING_RULE_ID,
    )
    output = dict(result)
    output["candidate_definition"] = (
        "activate_at_0.5R; trail_highwater_by_0.4R; "
        "minimum_0.1R_gross_lock; reserve_costs_for_0.05R_net_floor"
    )
    output["research_hypothesis"] = (
        "Protect trades whose favorable in-position mark reaches +0.5R "
        "without forcing an immediate take-profit or assuming fills."
    )
    output["not_an_independent_portfolio_trial"] = True
    output["ready_for_review"] = False
    output["execution_authority"] = False
    output["promotion_authority"] = False
    return output
