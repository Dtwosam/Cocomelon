from __future__ import annotations

from cocomelon.execution.store import PaperExecutionStore


def load_plan_lineage(
    store: PaperExecutionStore,
    plan_id: str,
) -> tuple[str, str] | None:
    plan = store.load_plan(plan_id)
    if plan is None:
        return None
    return plan.risk_decision_id, plan.strategy_decision_id
