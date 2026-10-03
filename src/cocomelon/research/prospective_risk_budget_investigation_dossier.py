from __future__ import annotations

import hashlib
import json
from typing import Final, cast

from cocomelon.research.prospective_risk_rejected_forward_markout_ledger import (
    validate_risk_rejected_forward_markout_ledger,
)
from cocomelon.research.prospective_risk_rejected_stop_path_ledger import (
    validate_risk_rejected_stop_path_ledger,
)

DOSSIER_SCHEMA_VERSION: Final = 1
DOSSIER_KIND: Final = "prospective-risk-budget-investigation-dossier-v1"


class RiskBudgetInvestigationDossierError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_payload(payload: dict[str, object]) -> str:
    stripped = {
        key: value
        for key, value in payload.items()
        if key != "report_sha256"
    }
    return hashlib.sha256(
        _canonical_json(stripped).encode("utf-8")
    ).hexdigest()


def _latest_source_identity(
    ledger: dict[str, object],
    *,
    label: str,
) -> dict[str, object]:
    history = ledger.get("source_history")
    if not isinstance(history, list) or not history:
        raise RiskBudgetInvestigationDossierError(
            f"{label} source history is empty"
        )
    raw = history[-1]
    if not isinstance(raw, dict):
        raise RiskBudgetInvestigationDossierError(
            f"{label} latest source history entry is invalid"
        )
    run_id = raw.get("paper_run_id")
    attempt = raw.get("paper_run_attempt")
    artifact_name = raw.get("artifact_name")
    artifact_digest = raw.get("artifact_digest")
    if (
        isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id <= 0
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt <= 0
        or not isinstance(artifact_name, str)
        or not artifact_name.strip()
        or not isinstance(artifact_digest, str)
        or not artifact_digest.startswith("sha256:")
    ):
        raise RiskBudgetInvestigationDossierError(
            f"{label} latest source identity is invalid"
        )
    return {
        "paper_run_id": run_id,
        "paper_run_attempt": attempt,
        "artifact_name": artifact_name,
        "artifact_digest": artifact_digest,
    }


def _summary(ledger: dict[str, object], *, label: str) -> dict[str, object]:
    raw = ledger.get("summary")
    if not isinstance(raw, dict):
        raise RiskBudgetInvestigationDossierError(
            f"{label} summary is invalid"
        )
    return raw


def build_risk_budget_investigation_dossier(
    return_ledger: object,
    stop_ledger: object,
) -> dict[str, object]:
    validated_returns = validate_risk_rejected_forward_markout_ledger(
        return_ledger
    )
    validated_stops = validate_risk_rejected_stop_path_ledger(
        stop_ledger
    )
    return_summary = _summary(validated_returns, label="return ledger")
    stop_summary = _summary(validated_stops, label="stop ledger")

    return_identity = _latest_source_identity(
        validated_returns,
        label="return ledger",
    )
    stop_identity = _latest_source_identity(
        validated_stops,
        label="stop ledger",
    )
    return_overlap = validated_returns.get("overlap_started_at_ms")
    stop_overlap = validated_stops.get("overlap_started_at_ms")
    source_aligned = (
        return_identity == stop_identity
        and return_overlap == stop_overlap
    )

    cumulative_economic_gate = return_summary.get(
        "risk_budget_investigation_readiness"
    )
    cumulative_stop_gate = stop_summary.get(
        "risk_budget_stop_investigation"
    )
    gates_current = isinstance(
        cumulative_economic_gate, dict
    ) and isinstance(cumulative_stop_gate, dict)
    return_integrity = return_summary.get("integrity_clean") is True
    stop_integrity = stop_summary.get("integrity_clean") is True
    integrity_clean = return_integrity and stop_integrity

    return_post = return_summary.get("post_integrity_miss")
    stop_post = stop_summary.get("post_integrity_miss")
    post_boundary_known = (
        isinstance(return_post, dict)
        and isinstance(stop_post, dict)
        and return_post.get("boundary_known") is True
        and stop_post.get("boundary_known") is True
    )
    post_started_at_ms = (
        return_post.get("started_at_ms")
        if isinstance(return_post, dict)
        else None
    )
    stop_post_started_at_ms = (
        stop_post.get("started_at_ms")
        if isinstance(stop_post, dict)
        else None
    )
    post_source_aligned = (
        source_aligned
        and post_boundary_known
        and isinstance(post_started_at_ms, int)
        and not isinstance(post_started_at_ms, bool)
        and post_started_at_ms == stop_post_started_at_ms
    )
    post_economic_gate = (
        return_post.get("risk_budget_investigation_readiness")
        if isinstance(return_post, dict)
        else None
    )
    post_stop_gate = (
        stop_post.get("risk_budget_stop_investigation")
        if isinstance(stop_post, dict)
        else None
    )
    post_gates_current = isinstance(
        post_economic_gate, dict
    ) and isinstance(post_stop_gate, dict)
    if integrity_clean:
        integrity_scope = "cumulative"
        effective_integrity_clean = True
        economic_gate = cumulative_economic_gate
        stop_gate = cumulative_stop_gate
    elif post_source_aligned and post_gates_current:
        integrity_scope = "post_integrity_miss"
        effective_integrity_clean = True
        economic_gate = post_economic_gate
        stop_gate = post_stop_gate
    else:
        integrity_scope = "blocked"
        effective_integrity_clean = False
        economic_gate = cumulative_economic_gate
        stop_gate = cumulative_stop_gate

    economic_by_reason: dict[str, object] = {}
    stop_by_reason: dict[str, object] = {}
    if isinstance(economic_gate, dict):
        raw = economic_gate.get("by_reason")
        if isinstance(raw, dict):
            economic_by_reason = raw
    if isinstance(stop_gate, dict):
        raw = stop_gate.get("by_reason")
        if isinstance(raw, dict):
            stop_by_reason = raw

    reasons = sorted(set(economic_by_reason) | set(stop_by_reason))
    by_reason: dict[str, dict[str, object]] = {}
    ready_reasons: list[str] = []
    for reason in reasons:
        economic = economic_by_reason.get(reason)
        stop = stop_by_reason.get(reason)
        economic_ready = (
            isinstance(economic, dict)
            and economic.get("ready_for_risk_budget_investigation") is True
        )
        stop_ready = (
            isinstance(stop, dict)
            and stop.get(
                "ready_for_risk_budget_stop_investigation"
            )
            is True
        )
        conjunctive_ready = (
            source_aligned
            and gates_current
            and effective_integrity_clean
            and economic_ready
            and stop_ready
        )
        if conjunctive_ready:
            ready_reasons.append(reason)
        by_reason[reason] = {
            "economic_ready": economic_ready,
            "stop_survival_ready": stop_ready,
            "conjunctive_ready_for_investigation": conjunctive_ready,
            "economic_horizons": (
                economic.get("horizons")
                if isinstance(economic, dict)
                else None
            ),
            "stop_survival_horizons": (
                stop.get("horizons")
                if isinstance(stop, dict)
                else None
            ),
        }

    if not gates_current:
        status = "waiting_for_current_gate_format"
    elif not source_aligned:
        status = "waiting_for_aligned_sources"
    elif integrity_clean:
        status = "aligned_evaluated"
    elif post_source_aligned and post_gates_current:
        status = "aligned_post_integrity_evaluated"
    else:
        status = "blocked_by_source_integrity"

    payload: dict[str, object] = {
        "schema_version": DOSSIER_SCHEMA_VERSION,
        "kind": DOSSIER_KIND,
        "status": status,
        "source_aligned": source_aligned,
        "gates_current": gates_current,
        "integrity_clean": integrity_clean,
        "effective_integrity_clean": effective_integrity_clean,
        "integrity_scope": integrity_scope,
        "post_integrity_source_aligned": post_source_aligned,
        "post_integrity_started_at_ms": (
            post_started_at_ms if post_source_aligned else None
        ),
        "return_integrity_clean": return_integrity,
        "stop_integrity_clean": stop_integrity,
        "return_source": return_identity,
        "stop_source": stop_identity,
        "return_overlap_started_at_ms": return_overlap,
        "stop_overlap_started_at_ms": stop_overlap,
        "return_ledger_sha256": validated_returns.get("ledger_sha256"),
        "stop_ledger_sha256": validated_stops.get("ledger_sha256"),
        "ready_reasons": ready_reasons,
        "by_reason": by_reason,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "changes_execution": False,
        "changes_candidate_readiness": False,
    }
    payload["report_sha256"] = _sha256_payload(payload)
    return payload


def validate_risk_budget_investigation_dossier(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier must be an object"
        )
    if raw.get("schema_version") != DOSSIER_SCHEMA_VERSION:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier schema is unsupported"
        )
    if raw.get("kind") != DOSSIER_KIND:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier kind is unsupported"
        )
    if raw.get("status") not in {
        "waiting_for_current_gate_format",
        "waiting_for_aligned_sources",
        "blocked_by_source_integrity",
        "aligned_evaluated",
        "aligned_post_integrity_evaluated",
    }:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier status is unsupported"
        )
    if (
        raw.get("research_only") is not True
        or raw.get("execution_authority") is not False
        or raw.get("promotion_authority") is not False
        or raw.get("changes_risk_limits") is not False
        or raw.get("changes_execution") is not False
        or raw.get("changes_candidate_readiness") is not False
    ):
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier authority drift"
        )
    ready_reasons = raw.get("ready_reasons")
    by_reason = raw.get("by_reason")
    if not isinstance(ready_reasons, list) or not isinstance(by_reason, dict):
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier reason summary is invalid"
        )
    expected = _sha256_payload(cast(dict[str, object], raw))
    if raw.get("report_sha256") != expected:
        raise RiskBudgetInvestigationDossierError(
            "risk-budget dossier digest mismatch"
        )
    return dict(raw)
