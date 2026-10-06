from __future__ import annotations

from dataclasses import dataclass

from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)


@dataclass(frozen=True, slots=True)
class ContinuousPaperDecisionExportReport:
    replay_run_id: str
    scanned_facts: int
    selected_facts: int
    created_records: int
    long_decisions: int
    short_decisions: int
    no_trade_decisions: int
    state_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "replay_run_id": self.replay_run_id,
            "scanned_facts": self.scanned_facts,
            "selected_facts": self.selected_facts,
            "created_records": self.created_records,
            "long_decisions": self.long_decisions,
            "short_decisions": self.short_decisions,
            "no_trade_decisions": self.no_trade_decisions,
            "state_digest": self.state_digest,
            "research_only": True,
            "promotion_authority": False,
            "execution_authority": False,
        }


def export_continuous_paper_decision_facts(
    facts: EvaluationFactStore,
    output: ContinuousPaperDecisionFactStore,
    *,
    replay_run_id: str,
) -> ContinuousPaperDecisionExportReport:
    if not replay_run_id.strip():
        raise ValueError("replay_run_id must not be empty")

    scanned = 0
    selected = 0
    created = 0
    counts = {
        Direction.LONG: 0,
        Direction.SHORT: 0,
        Direction.NO_TRADE: 0,
    }
    for fact in facts.iter_decision_facts():
        scanned += 1
        if fact.replay_run_id != replay_run_id:
            continue
        selected += 1
        counts[fact.direction] += 1
        if output.record(fact):
            created += 1

    return ContinuousPaperDecisionExportReport(
        replay_run_id=replay_run_id,
        scanned_facts=scanned,
        selected_facts=selected,
        created_records=created,
        long_decisions=counts[Direction.LONG],
        short_decisions=counts[Direction.SHORT],
        no_trade_decisions=counts[Direction.NO_TRADE],
        state_digest=output.state_digest,
    )
