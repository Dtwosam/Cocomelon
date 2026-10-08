from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.prospective_filter_economic_readiness import (
    prospective_filter_economic_readiness,
)

ZERO: Final = Decimal("0")
STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-trend-outside-top10-both-sides-v1"
RANK_CUTOFF: Final = 10
MAX_RANK_AGE_MS: Final = 300_000
EMBARGO_MS: Final = 6 * 3_600_000
MIN_CLOSED: Final = 40
MIN_TARGETED_BLOCKS: Final = 10
MIN_RETAINED_PER_SIDE: Final = 10
MIN_MATCHED_MARKETS: Final = 4
CHRONOLOGICAL_BLOCKS: Final = 4
MIN_PERIOD_TRADES: Final = 10


class ProspectiveTrendOutsideTop10Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveTrendOutsideTop10State:
    frozen_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if isinstance(self.frozen_at_ms, bool) or (
            not isinstance(self.frozen_at_ms, int)
            or self.frozen_at_ms < 0
        ):
            raise ValueError("trend/rank freeze timestamp invalid")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("trend/rank schema drift")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("trend/rank candidate identity drift")

    @property
    def started_at_ms(self) -> int:
        return self.frozen_at_ms + EMBARGO_MS

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "candidate_id": CANDIDATE_ID,
            "frozen_at_ms": self.frozen_at_ms,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "action": "skip_original_entry",
                "lead_strategy": "trend",
                "min_rejected_rank_ordinal": RANK_CUTOFF + 1,
                "max_rank_age_ms": MAX_RANK_AGE_MS,
                "direction_policy": "both_long_and_short",
                "other_strategies": "admit",
                "rank_top10": "admit",
                "missing_or_stale_evidence": "no_credit_fail_closed",
            },
            "historical_hypothesis_only": {
                "source": "loss-streak-context-audit-134-closed-trades",
                "retrospective_validation_matched": 21,
                "retrospective_skip_only_delta_usd": (
                    "86.95636725174999999999999956"
                ),
                "explored_candidates": 18,
                "post_selection_forward_validation_required": True,
            },
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    @classmethod
    def from_payload(
        cls, raw: object
    ) -> ProspectiveTrendOutsideTop10State:
        if not isinstance(raw, dict):
            raise ProspectiveTrendOutsideTop10Error(
                "frozen trend/rank state must be an object"
            )
        frozen_at_ms = raw.get("frozen_at_ms")
        if isinstance(frozen_at_ms, bool) or not isinstance(frozen_at_ms, int):
            raise ProspectiveTrendOutsideTop10Error(
                "frozen trend/rank timestamp type drift"
            )
        state = cls(frozen_at_ms=frozen_at_ms)
        if raw != state.payload():
            raise ProspectiveTrendOutsideTop10Error(
                "frozen trend/rank rule or retrospective provenance drift"
            )
        return state


def _totals(
    rows: Sequence[tuple[TradeJournalEntry, bool, bool]],
) -> dict[str, object]:
    actual = sum((trade.net_pnl for trade, _, _ in rows), ZERO)
    actual_r = sum((trade.net_r for trade, _, _ in rows), ZERO)
    targeted = sum(
        (ZERO if block else trade.net_pnl for trade, block, _ in rows), ZERO
    )
    targeted_r = sum(
        (ZERO if block else trade.net_r for trade, block, _ in rows), ZERO
    )
    broad = sum(
        (ZERO if block else trade.net_pnl for trade, _, block in rows), ZERO
    )
    broad_r = sum(
        (ZERO if block else trade.net_r for trade, _, block in rows), ZERO
    )
    return {
        "trades": len(rows),
        "actual_net_pnl": str(actual),
        "targeted_net_pnl": str(targeted),
        "broad_top10_net_pnl": str(broad),
        "targeted_minus_actual_net_pnl": str(targeted - actual),
        "targeted_minus_broad_net_pnl": str(targeted - broad),
        "actual_net_r": str(actual_r),
        "targeted_net_r": str(targeted_r),
        "broad_top10_net_r": str(broad_r),
        "targeted_minus_actual_net_r": str(targeted_r - actual_r),
        "targeted_minus_broad_net_r": str(targeted_r - broad_r),
        "targeted_absolutely_profitable": (
            bool(rows) and targeted > ZERO and targeted_r > ZERO
        ),
        "targeted_beats_actual": (
            bool(rows) and targeted > actual and targeted_r > actual_r
        ),
        "targeted_beats_broad": (
            bool(rows) and targeted > broad and targeted_r > broad_r
        ),
    }


def prospective_trend_outside_top10_comparison(
    trades: Sequence[TradeJournalEntry],
    facts: EvaluationFactStore,
    ranks: ContinuousPaperOpeningRankStore,
    state: ProspectiveTrendOutsideTop10State,
) -> dict[str, object]:
    """Audit a precommitted targeted trend filter on *future* actual trades."""
    journal = tuple(trades)
    if len({t.trade_id for t in journal}) != len(journal):
        raise ProspectiveTrendOutsideTop10Error(
            "trend/rank comparison contains duplicate trade IDs"
        )
    prospective = tuple(sorted(
        (trade for trade in journal if trade.opened_at_ms >= state.started_at_ms),
        key=lambda trade: (
            trade.opened_at_ms, trade.closed_at_ms, trade.trade_id
        ),
    ))
    rows: list[tuple[TradeJournalEntry, bool, bool]] = []
    missing_fact = 0
    missing_rank = 0
    stale_rank = 0
    for trade in prospective:
        fact = (
            None
            if trade.replay_run_id is None
            else facts.load_decision_by_strategy_id(
                trade.strategy_decision_id, trade.replay_run_id
            )
        )
        if fact is None or not fact.lead_strategy:
            missing_fact += 1
            continue
        if (
            fact.market != trade.market
            or fact.direction is not trade.direction
            or fact.feature_snapshot_id != trade.feature_snapshot_id
            or fact.timestamp_ms > trade.opened_at_ms
        ):
            raise ProspectiveTrendOutsideTop10Error(
                "trend/rank decision lineage drift or future decision"
            )
        rank = ranks.load(trade.opening_plan_id)
        if rank is None:
            missing_rank += 1
            continue
        if (
            rank.market != trade.market.canonical
            or rank.opened_at_ms != trade.opened_at_ms
        ):
            raise ProspectiveTrendOutsideTop10Error(
                "trend/rank opening rank lineage drift"
            )
        if rank.rank_age_ms > MAX_RANK_AGE_MS:
            stale_rank += 1
            continue
        outside = rank.ordinal > RANK_CUTOFF
        target_skip = outside and fact.lead_strategy == "trend"
        rows.append((trade, target_skip, outside))
    result = _totals(rows)
    economic = prospective_filter_economic_readiness(tuple(
        (trade, block) for trade, block, _ in rows
    ))
    long_rows = tuple(row for row in rows if row[0].direction.value == "long")
    short_rows = tuple(row for row in rows if row[0].direction.value == "short")
    sides = {
        "long": _totals(long_rows),
        "short": _totals(short_rows),
    }
    blocks = []
    for index in range(CHRONOLOGICAL_BLOCKS):
        portion = rows[
            len(rows) * index // CHRONOLOGICAL_BLOCKS:
            len(rows) * (index + 1) // CHRONOLOGICAL_BLOCKS
        ]
        block_econ = _totals(portion)
        blocks.append({
            "block": index + 1,
            **block_econ,
            "passes": (
                len(portion) >= MIN_PERIOD_TRADES
                and block_econ["targeted_absolutely_profitable"] is True
                and block_econ["targeted_beats_actual"] is True
            ),
        })

    # A blanket top-10 screen removes ALL outside-rank opportunities,
    # including non-trend winners; quantify that sacrifice separately.
    broad_only_winners = sum(
        trade.net_pnl > ZERO
        for trade, targeted, broad in rows
        if broad and not targeted
    )
    largest_incremental_winner = (
        None
        if not rows else max(
            rows,
            key=lambda row: (
                (-row[0].net_pnl if row[1] else ZERO),
                row[0].trade_id,
            ),
        )[0].trade_id
    )
    leave_best = _totals(tuple(
        row for row in rows if row[0].trade_id != largest_incremental_winner
    ))
    by_market_removed = {
        market: _totals(tuple(
            row for row in rows if row[0].market.canonical != market
        ))
        for market in sorted({row[0].market.canonical for row in rows})
    }
    clean = (
        len(rows) == len(prospective)
        and missing_fact == missing_rank == stale_rank == 0
    )
    strict = (
        clean
        and len(rows) >= MIN_CLOSED
        and len(by_market_removed) >= MIN_MATCHED_MARKETS
        and sum(row[1] for row in rows) >= MIN_TARGETED_BLOCKS
        and all(
            len(side_rows) >= MIN_RETAINED_PER_SIDE
            and sum(not row[1] for row in side_rows) >= MIN_RETAINED_PER_SIDE
            and sides[name]["targeted_absolutely_profitable"] is True
            and sides[name]["targeted_beats_actual"] is True
            for name, side_rows in (
                ("long", long_rows), ("short", short_rows)
            )
        )
        and economic["economics_ready"] is True
        and result["targeted_absolutely_profitable"] is True
        and result["targeted_beats_actual"] is True
        and all(block["passes"] is True for block in blocks)
        and leave_best["targeted_absolutely_profitable"] is True
        and leave_best["targeted_beats_actual"] is True
        and all(
            row["targeted_absolutely_profitable"] is True
            and row["targeted_beats_actual"] is True
            for row in by_market_removed.values()
        )
    )
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "candidate_id": CANDIDATE_ID,
        "frozen_rule": state.payload(),
        "forward_started_at_ms": state.started_at_ms,
        "prospective_closed_trades": len(prospective),
        "fully_attributed_future_trades": len(rows),
        "missing_decisions": missing_fact,
        "missing_rank": missing_rank,
        "stale_rank": stale_rank,
        "integrity_clean": clean,
        "rank_cutoff": RANK_CUTOFF,
        "blocked_targeted_trades": sum(row[1] for row in rows),
        "blocked_targeted_winners": sum(
            trade.net_pnl > ZERO for trade, blocked, _ in rows if blocked
        ),
        "blocked_targeted_losers": sum(
            trade.net_pnl <= ZERO for trade, blocked, _ in rows if blocked
        ),
        "retained_outside_top10_nontrend_trades": sum(
            broad and not targeted for _, targeted, broad in rows
        ),
        "retained_outside_top10_nontrend_winners": broad_only_winners,
        "overall": result,
        "vs_actual_robustness": economic,
        "by_direction": sides,
        "chronological_blocks": blocks,
        "remove_largest_incremental_winner": leave_best,
        "leave_one_market_out": by_market_removed,
        "strict_descriptive_screen_passes": strict,
        "selected_winner": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready_for_review": False,
        "account_level_profitability_proven": False,
        "warning": (
            "Historical selection from 18 discovery patterns does not "
            "prove forward profitability. Skip-only zero PnL assumes no "
            "replacement positions; comparing actual vs filtered same "
            "trade closes cannot establish capital reflow or drawdown. "
            "Active LONG and SHORT paper decisions are unchanged."
        ),
    }
