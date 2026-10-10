"""Fixed, time-bounded paper-only ENA entry quarantine.

This is an *intervention* selected from a retrospective losing cohort,
not evidence of a profitable trading rule. Existing positions and exits
remain untouched. Live execution does not import or activate this policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from cocomelon.domain.strategy import Direction
from cocomelon.evidence.epochs import EpochMarketEvaluation

# Frozen source: original paper run 38001096314, attempt 1, successful
# post-handoff all-paper-trade chart audit artifact 11649679278.
SOURCE_RUN_ID: Final = 38001096314
SOURCE_RUN_ATTEMPT: Final = 1
SOURCE_ARTIFACT_ID: Final = 11649679278
SOURCE_AUDIT_MEMBER_SHA256: Final = (
    "b828de7051c2df0030c063c314e8802edba882e7b4c996e31b42adf6097ccef2"
)
SOURCE_ORIGINAL_CLOSED_TRADES: Final = 154
SOURCE_ENA_CLOSED_TRADES: Final = 16
SOURCE_ENA_WINNERS: Final = 0
SOURCE_ENA_BOOKED_NET_PNL: Final = "-165.4427411543226200000000004"
SOURCE_LAST_CLOSED_AT_MS: Final = 1791570933991

# Start a separate forward observation AFTER source closure and a
# six-hour embargo from the 2026-10-10 00:00 UTC policy freeze.
# Expiry prevents accidentally persisting a selectively chosen historical
# symbol ban as a permanent or future live strategy.
FREEZE_AT_MS: Final = 1791590400000
ACTIVE_FROM_MS: Final = 1791612000000
ACTIVE_UNTIL_MS: Final = 1792216800000
MARKET_CANONICAL: Final = "ENA"
CANDIDATE_ID: Final = "paper-ena-fixed-quarantine-20261010-v1"
BLOCK_REASON: Final = "paper_ena_forward_loss_quarantine"


@dataclass(slots=True)
class PaperEnaQuarantine:
    """Admit all other markets while blocking *new* ENA paper exposure."""

    blocked_decisions: int = 0
    blocked_by_side: dict[str, int] = field(default_factory=dict)
    _seen_decision_ids: set[str] = field(default_factory=set)

    def block_reason(
        self,
        evaluation: EpochMarketEvaluation,
        *,
        attempt_timestamp_ms: int,
    ) -> str | None:
        if not (ACTIVE_FROM_MS <= attempt_timestamp_ms < ACTIVE_UNTIL_MS):
            return None
        decision = evaluation.decision
        # A pre-freeze decision is not re-labeled as forward merely because
        # a subsequent book/IOC attempt crossed the policy start boundary.
        if decision.timestamp_ms < ACTIVE_FROM_MS:
            return None
        if decision.market.canonical != MARKET_CANONICAL:
            return None
        if decision.direction not in (Direction.LONG, Direction.SHORT):
            return None
        if decision.decision_id not in self._seen_decision_ids:
            self._seen_decision_ids.add(decision.decision_id)
            self.blocked_decisions += 1
            side = decision.direction.value
            self.blocked_by_side[side] = self.blocked_by_side.get(side, 0) + 1
        return BLOCK_REASON

    def summary(self) -> dict[str, object]:
        return {
            "candidate_id": CANDIDATE_ID,
            "kind": "time_bounded_original_paper_ena_entry_quarantine",
            "source_run_id": SOURCE_RUN_ID,
            "source_run_attempt": SOURCE_RUN_ATTEMPT,
            "source_artifact_id": SOURCE_ARTIFACT_ID,
            "source_audit_member_sha256": SOURCE_AUDIT_MEMBER_SHA256,
            "source_original_closed_trades": SOURCE_ORIGINAL_CLOSED_TRADES,
            "source_ena_closed_trades": SOURCE_ENA_CLOSED_TRADES,
            "source_ena_winners": SOURCE_ENA_WINNERS,
            "source_ena_booked_net_pnl": SOURCE_ENA_BOOKED_NET_PNL,
            "source_last_closed_at_ms": SOURCE_LAST_CLOSED_AT_MS,
            "frozen_at_ms": FREEZE_AT_MS,
            "active_from_ms": ACTIVE_FROM_MS,
            "active_until_ms": ACTIVE_UNTIL_MS,
            "market": MARKET_CANONICAL,
            "entry_block_reason": BLOCK_REASON,
            "blocked_decisions_this_worker": self.blocked_decisions,
            "blocked_by_side_this_worker": dict(sorted(self.blocked_by_side.items())),
            "paper_only": True,
            "existing_positions_and_exits_untouched": True,
            "risk_limits_unchanged": True,
            "live_orders_enabled": False,
            "retrospectively_selected": True,
            "profitable_edge_verified": False,
            "matched_forward_baseline_available": False,
        }
