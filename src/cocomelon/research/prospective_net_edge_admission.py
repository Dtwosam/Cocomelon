"""RESEARCH ONLY: pre-entry net expectancy from PRIOR baseline PAPER closes.

Strict chronology is part of the financial contract: a trade whose exit
is not strictly earlier than the proposed entry cannot vote on that entry.
All reference fills come from the unchanged baseline, including losers.
The shadow counterfactual below is NOT an independent capital-backed ledger.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction

ZERO: Final = Decimal("0")
NET_R_MARGIN: Final = Decimal("0.05")
MIN_CLOSED_BY_DIRECTION: Final = 40
MAX_RECENT_CLOSED: Final = 80
CHRONOLOGICAL_BLOCKS: Final = 4
MIN_DISTINCT_MARKETS: Final = 4
FROZEN_EMBARGO_MS: Final = 6 * 60 * 60 * 1_000


class ProspectiveNetEdgeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveNetEdgeState:
    frozen_at_ms: int

    def __post_init__(self) -> None:
        if type(self.frozen_at_ms) is not int or self.frozen_at_ms < 0:
            raise ValueError("frozen_at_ms must be nonnegative integer")

    @property
    def started_at_ms(self) -> int:
        return self.frozen_at_ms + FROZEN_EMBARGO_MS

    def contract(self) -> dict[str, object]:
        return {
            "candidate_id": "prospective-after-cost-direction-net-floor-v1",
            "frozen_at_ms": self.frozen_at_ms,
            "started_at_ms": self.started_at_ms,
            "reference": "all_actual_unfiltered_baseline_paper_closes",
            "training_only_closes_after_forward_start": True,
            "training_close_must_precede_target_open": True,
            "window": MAX_RECENT_CLOSED,
            "min_direction_closes": MIN_CLOSED_BY_DIRECTION,
            "min_markets": MIN_DISTINCT_MARKETS,
            "blocks": CHRONOLOGICAL_BLOCKS,
            "minimum_empirical_net_r_floor": str(NET_R_MARGIN),
            "scope": "research_only_counterfactual_abstention_not_separate_account",
            "execution_authority": False,
            "promotion_authority": False,
        }


def _chronology(trades: Sequence[TradeJournalEntry]) -> tuple[TradeJournalEntry, ...]:
    seen: set[str] = set()
    for trade in trades:
        identity = trade.trade_id
        if identity in seen:
            raise ProspectiveNetEdgeError("duplicate actual baseline trade id")
        seen.add(identity)
    return tuple(sorted(trades, key=lambda t: (
        t.opened_at_ms, t.closed_at_ms, t.trade_id,
    )))


def preentry_net_floor(
    baseline_closes: Sequence[TradeJournalEntry],
    *,
    proposed_open_ms: int,
    direction: Direction,
    state: ProspectiveNetEdgeState,
) -> dict[str, object]:
    """Read-only, frozen rule; never use an eventual target close for training."""
    if type(proposed_open_ms) is not int or proposed_open_ms < 0:
        raise ProspectiveNetEdgeError("proposed opening clock is invalid")
    if direction not in (Direction.LONG, Direction.SHORT):
        raise ProspectiveNetEdgeError("direction must be long or short")

    # Reject malformed/duplicated ORIGINAL baseline custody even during
    # embargo; never silently choose a favorable copy of a closed trade.
    unique = _chronology(baseline_closes)
    samples = tuple(sorted((
        trade for trade in unique
        if state.started_at_ms <= trade.closed_at_ms < proposed_open_ms
        and trade.direction is direction
    ), key=lambda t: (t.closed_at_ms, t.opened_at_ms, t.trade_id)))
    window = samples[-MAX_RECENT_CLOSED:]
    n = len(window)
    markets = {trade.market.canonical for trade in window}
    reply: dict[str, object] = {
        "proposed_open_ms": proposed_open_ms,
        "direction": direction.value,
        "reference_closed_trades": n,
        "reference_markets": len(markets),
        "strictly_past_reference_last_close_ms": (
            window[-1].closed_at_ms if window else None
        ),
        "candidate_decision": "BLOCK",
        "reason": "insufficient_new_original_reference",
        "empirical_stress_floor_net_r": None,
        "hypothetical_next_risk_dollars": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    if proposed_open_ms < state.started_at_ms:
        reply["reason"] = "precommitted_embargo"
        return reply
    if n < MIN_CLOSED_BY_DIRECTION:
        return reply
    if len(markets) < MIN_DISTINCT_MARKETS:
        reply["reason"] = "insufficient_cross_market_reference"
        return reply

    # All values are actual baseline AFTER-COST net R (paid fees,
    # financing and slippage). Four sequential blocks must EACH pay
    # their own costs. No directional/favorable-block selection occurs.
    r_values = [trade.net_r for trade in window]
    block_means: list[Decimal] = []
    for i in range(CHRONOLOGICAL_BLOCKS):
        part = r_values[
            i * n // CHRONOLOGICAL_BLOCKS:
            (i + 1) * n // CHRONOLOGICAL_BLOCKS
        ]
        if not part:
            raise ProspectiveNetEdgeError("empty chronology block")
        block_means.append(sum(part, ZERO) / Decimal(len(part)))

    by_market: dict[str, list[Decimal]] = defaultdict(list)
    for trade in window:
        by_market[trade.market.canonical].append(trade.net_r)
    loo_market = [
        (sum(r_values, ZERO) - sum(values, ZERO)) /
        Decimal(n - len(values))
        for values in by_market.values() if len(values) < n
    ]
    if len(loo_market) != len(markets):
        raise ProspectiveNetEdgeError("single-market baseline cannot qualify")
    # A single extraordinary closed winner cannot lift a weak account.
    loo_largest = (
        sum(r_values, ZERO) - max(r_values)
    ) / Decimal(n - 1)
    floor = min((*block_means, *loo_market, loo_largest))
    reply["empirical_stress_floor_net_r"] = str(floor)
    reply["reason"] = "empirical_net_floor_below_margin"
    if floor > NET_R_MARGIN:
        reply["candidate_decision"] = "ADMIT"
        reply["reason"] = "empirical_net_floor_above_margin"
    return reply


def replay_net_floor_on_original_closes(
    baseline_trades: Sequence[TradeJournalEntry],
    *,
    state: ProspectiveNetEdgeState,
) -> dict[str, object]:
    """Diagnostic zero-cash skip arithmetic, NEVER a matched PAPER account."""
    original = _chronology(baseline_trades)
    rows: list[dict[str, object]] = []
    gross_baseline_net = ZERO
    hypothetical_retained_net = ZERO
    admitted = 0
    skipped = 0
    for trade in original:
        gross_baseline_net += trade.net_pnl
        # A trade's eventual realized outcome is ALWAYS excluded at its
        # opening; even an earlier-opened overlapping position whose exit
        # is later is inaccessible. The whole baseline remains reference
        # material, regardless of earlier hypothetical skip decisions.
        prediction = preentry_net_floor(
            original,
            proposed_open_ms=trade.opened_at_ms,
            direction=trade.direction,
            state=state,
        )
        eligible = trade.opened_at_ms >= state.started_at_ms
        if not eligible:
            continue
        accept = prediction["candidate_decision"] == "ADMIT"
        admitted += int(accept)
        skipped += int(not accept)
        if accept:
            hypothetical_retained_net += trade.net_pnl
        rows.append({
            "trade_id": trade.trade_id,
            "opened_at_ms": trade.opened_at_ms,
            "closed_at_ms": trade.closed_at_ms,
            "market": trade.market.canonical,
            "direction": trade.direction.value,
            "actual_baseline_net_pnl": str(trade.net_pnl),
            "hypothetical_admitted": accept,
            "decision": prediction,
        })
    return {
        "rule": state.contract(),
        "forward_original_rows": len(rows),
        "forward_original_admitted": admitted,
        "forward_original_skipped": skipped,
        "whole_original_baseline_net_pnl_including_discovery": str(gross_baseline_net),
        "hypothetical_forward_retained_same_fills_net": str(
            hypothetical_retained_net
        ),
        "counterfactual_is_independent_account": False,
        "all_original_source_continuity_verified": False,
        "positive_whole_account_equity_verified": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "rows": rows,
    }
