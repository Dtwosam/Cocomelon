from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
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
CANDIDATE_ID: Final = "prospective-short-breakout-only-top3-v1"
SCHEMA_VERSION: Final = 1
FREEZE_EMBARGO_MS: Final = 6 * 3_600_000
RANK_CUTOFF: Final = 3
MIN_FUTURE: Final = 40
MIN_SKIPPED: Final = 8
MIN_MARKETS: Final = 4
MIN_SIDE: Final = 10
BLOCKS: Final = 4
MIN_PER_BLOCK: Final = 10


class ProspectiveShortBreakoutRankError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveShortBreakoutRankState:
    frozen_at_ms: int
    candidate_id: str = CANDIDATE_ID
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.frozen_at_ms) is not int or self.frozen_at_ms < 0:
            raise ValueError("short breakout freeze time invalid")
        if (
            self.candidate_id != CANDIDATE_ID
            or self.schema_version != SCHEMA_VERSION
        ):
            raise ValueError("short breakout frozen rule identity changed")

    @property
    def started_at_ms(self) -> int:
        return self.frozen_at_ms + FREEZE_EMBARGO_MS

    def payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "schema_version": self.schema_version,
            "frozen_at_ms": self.frozen_at_ms,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "only_direction": "short",
                "only_lead_strategy": "breakout",
                "skip_if_fresh_opening_rank_above": RANK_CUTOFF,
                "max_rank_age_ms": 300_000,
                "unknown_or_stale": "retain_and_disqualify_incomplete_review",
                "all_other_openings": "retain",
                "skip_execution_assumption": "zero_cash_no_replacement_trade",
            },
            "historical_hypothesis_only": {
                "source": "authenticated_153_closed_paper_trades_2026_10_09",
                "short_breakout_top3_trades": 4,
                "short_breakout_top3_net_pnl_approx_usd": "86.31",
                "short_breakout_rank4plus_trades": 8,
                "short_breakout_rank4plus_net_pnl_approx_usd": "-54.73",
                "post_selection_forward_validation_required": True,
            },
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "changes_strategy": False,
            "changes_positions": False,
            "changes_risk_limits": False,
        }

    @classmethod
    def from_payload(
        cls, raw: object,
    ) -> ProspectiveShortBreakoutRankState:
        if not isinstance(raw, dict):
            raise ProspectiveShortBreakoutRankError(
                "short breakout freeze must be an object"
            )
        frozen = raw.get("frozen_at_ms")
        if type(frozen) is not int:
            raise ProspectiveShortBreakoutRankError(
                "short breakout frozen timestamp is invalid"
            )
        state = cls(frozen_at_ms=frozen)
        if raw != state.payload():
            raise ProspectiveShortBreakoutRankError(
                "short breakout candidate freeze has drifted"
            )
        return state


def _economics(
    rows: Sequence[tuple[TradeJournalEntry, bool]],
) -> dict[str, object]:
    """Score ALL booked original cashflows, never invent skipped fills."""
    with localcontext(prec=96):
        actual = sum((t.net_pnl for t, _ in rows), ZERO)
        actual_r = sum((t.net_r for t, _ in rows), ZERO)
        candidate = sum((ZERO if skip else t.net_pnl for t, skip in rows), ZERO)
        candidate_r = sum((ZERO if skip else t.net_r for t, skip in rows), ZERO)
        blocked = tuple(t for t, skip in rows if skip)
        return {
            "trades": len(rows),
            "original_net_pnl": str(actual),
            "candidate_skip_only_net_pnl": str(candidate),
            "candidate_minus_original_net_pnl": str(candidate - actual),
            "original_net_r": str(actual_r),
            "candidate_skip_only_net_r": str(candidate_r),
            "candidate_minus_original_net_r": str(candidate_r - actual_r),
            "skipped": len(blocked),
            "skipped_original_winners": sum(t.net_pnl > ZERO for t in blocked),
            "skipped_original_losers": sum(t.net_pnl < ZERO for t in blocked),
            "skipped_original_net_pnl": str(
                sum((t.net_pnl for t in blocked), ZERO)
            ),
            "candidate_absolute_positive": (
                bool(rows) and candidate > ZERO and candidate_r > ZERO
            ),
            "candidate_beats_original": (
                bool(rows) and candidate > actual and candidate_r > actual_r
            ),
        }


def prospective_short_breakout_rank_comparison(
    trades: Sequence[TradeJournalEntry],
    facts: EvaluationFactStore,
    features: LearningFeatureSnapshotStore,
    ranks: ContinuousPaperOpeningRankStore,
    state: ProspectiveShortBreakoutRankState,
) -> dict[str, object]:
    """Prospective skip-only hypothesis, without changing the paper account."""
    journal = tuple(trades)
    if len({t.trade_id for t in journal}) != len(journal):
        raise ProspectiveShortBreakoutRankError(
            "duplicate original trade identity"
        )
    forward = tuple(sorted(
        (t for t in journal if t.opened_at_ms >= state.started_at_ms),
        key=lambda t: (t.opened_at_ms, t.closed_at_ms, t.trade_id),
    ))
    rows: list[tuple[TradeJournalEntry, bool]] = []
    unresolved: Counter[str] = Counter()
    market_skips: Counter[str] = Counter()
    for trade in forward:
        # The resolver verifies saved decision, feature arrival, opening
        # identity and rank freshness against the ACTUAL entry timestamp.
        context, reason = try_resolve_entry_context_row(
            trade, facts, features, ranks
        )
        skip = False
        if context is None:
            unresolved[reason or "missing_verified_context"] += 1
        elif context.get("rank_evidence_status") != "fresh":
            unresolved[str(context.get("rank_evidence_status"))] += 1
        else:
            ordinal = context.get("rank_ordinal")
            if type(ordinal) is not int or ordinal <= 0:
                raise ProspectiveShortBreakoutRankError(
                    "verified opening rank has invalid ordinal"
                )
            skip = (
                trade.direction.value == "short"
                and context.get("lead_strategy") == "breakout"
                and ordinal > RANK_CUTOFF
            )
        # Unknown contexts remain in the original AND the candidate with
        # their original booked PnL. Missing data never removes a loser.
        rows.append((trade, skip))
        if skip:
            market_skips[trade.market.canonical] += 1
    overall = _economics(rows)
    by_direction = {
        name: _economics(tuple(
            row for row in rows if row[0].direction.value == name
        ))
        for name in ("long", "short")
    }
    markets = sorted({trade.market.canonical for trade, _ in rows})
    blocks = []
    for index in range(BLOCKS):
        part = rows[len(rows) * index // BLOCKS:
                    len(rows) * (index + 1) // BLOCKS]
        econ = _economics(part)
        blocks.append({
            "block": index + 1,
            **econ,
            "passes": (
                len(part) >= MIN_PER_BLOCK
                and econ["candidate_absolute_positive"] is True
                and econ["candidate_beats_original"] is True
            ),
        })
    largest_avoided_loss = max(
        (trade for trade, skip in rows if skip and trade.net_pnl < ZERO),
        key=lambda trade: (-trade.net_pnl, trade.trade_id),
        default=None,
    )
    leave_largest = _economics(tuple(
        row for row in rows if largest_avoided_loss is None
        or row[0].trade_id != largest_avoided_loss.trade_id
    ))
    by_market_leave_one_out = {
        market: _economics(tuple(
            row for row in rows if row[0].market.canonical != market
        ))
        for market in markets
    }
    complete = not unresolved
    side_econ = by_direction["short"]
    screen = (
        complete
        and len(rows) >= MIN_FUTURE
        and overall["skipped"] >= MIN_SKIPPED
        and len(markets) >= MIN_MARKETS
        and len(market_skips) >= MIN_MARKETS
        and all(
            by_direction[side]["trades"] >= MIN_SIDE
            and by_direction[side]["candidate_absolute_positive"] is True
            for side in ("long", "short")
        )
        and side_econ["candidate_beats_original"] is True
        and overall["candidate_absolute_positive"] is True
        and overall["candidate_beats_original"] is True
        and all(block["passes"] is True for block in blocks)
        and leave_largest["candidate_absolute_positive"] is True
        and leave_largest["candidate_beats_original"] is True
        and all(
            item["candidate_absolute_positive"] is True
            and item["candidate_beats_original"] is True
            for item in by_market_leave_one_out.values()
        )
    )
    return {
        "definition": "frozen_short_breakout_rank4plus_skip_only_v1",
        "candidate_id": CANDIDATE_ID,
        "frozen_rule": state.payload(),
        "prospective_not_before_ms": state.started_at_ms,
        "original_forward_closed_trades": len(forward),
        "scored_forward_closed_trades": len(rows),
        "unverified_original_entry_context_by_reason": dict(unresolved),
        "integrity_complete": complete,
        "skipped_markets": dict(sorted(market_skips.items())),
        "overall": overall,
        "by_direction": by_direction,
        "chronological_blocks": blocks,
        "leave_largest_avoided_loss_out": leave_largest,
        "leave_one_market_out": by_market_leave_one_out,
        "strict_descriptive_screen_passes": screen,
        "full_account_trial": False,
        "ready_for_review": False,
        "promotion_authority": False,
        "execution_authority": False,
        "research_only": True,
        "changes_strategy": False,
        "changes_positions": False,
        "changes_risk_limits": False,
        "warning": (
            "Retrospective 153-trade pattern selected before freeze cannot "
            "prove edge. Unknown entry evidence retains original cashflows "
            "without filter credit. Skipped trades are zero cash with no "
            "replacement, not an independent capital-constrained paper "
            "account. Promotion requires new independent matched full-account "
            "prospective simulation with fees, funding and actual fill limits."
        ),
    }
