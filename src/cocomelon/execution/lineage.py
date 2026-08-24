from __future__ import annotations

import json

from cocomelon.execution.store import PaperExecutionStore


def load_plan_lineage(
    store: PaperExecutionStore,
    plan_id: str,
) -> tuple[str, str] | None:
    if not plan_id.strip():
        raise ValueError("plan_id must not be empty")
    row = store.raw_connection().execute(
        "SELECT payload_json FROM paper_order_plans WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError as exc:
        raise ValueError("persisted plan lineage is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("persisted plan lineage is unreadable")
    risk_decision_id = payload.get("risk_decision_id")
    strategy_decision_id = payload.get("strategy_decision_id")
    if not isinstance(risk_decision_id, str) or not risk_decision_id.strip():
        raise ValueError("persisted risk decision lineage is unreadable")
    if not isinstance(strategy_decision_id, str) or not strategy_decision_id.strip():
        raise ValueError("persisted strategy decision lineage is unreadable")
    return risk_decision_id, strategy_decision_id
