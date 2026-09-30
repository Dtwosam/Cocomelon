from __future__ import annotations

import json
from pathlib import Path

from cocomelon.research.cadence_shadow import (
    CADENCE_SHADOW_STATE_SCHEMA_VERSION,
    ShadowCadenceOutcome,
    _outcome_from_payload,
)


class CadenceOpportunityAuditError(RuntimeError):
    pass


def load_cadence_outcomes(
    state_path: str | Path,
) -> tuple[ShadowCadenceOutcome, ...]:
    path = Path(state_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CadenceOpportunityAuditError(
            "CADENCE_OPPORTUNITY_AUDIT_STATE_INVALID"
        ) from exc
    if not isinstance(raw, dict):
        raise CadenceOpportunityAuditError(
            "CADENCE_OPPORTUNITY_AUDIT_STATE_INVALID"
        )
    if raw.get("schema_version") != CADENCE_SHADOW_STATE_SCHEMA_VERSION:
        raise CadenceOpportunityAuditError(
            "CADENCE_OPPORTUNITY_AUDIT_SCHEMA_UNSUPPORTED"
        )
    values = raw.get("outcomes")
    if not isinstance(values, list):
        raise CadenceOpportunityAuditError(
            "CADENCE_OPPORTUNITY_AUDIT_OUTCOMES_INVALID"
        )
    try:
        outcomes = tuple(
            _outcome_from_payload(value)
            for value in values
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CadenceOpportunityAuditError(
            "CADENCE_OPPORTUNITY_AUDIT_OUTCOMES_INVALID"
        ) from exc

    identities = tuple(
        (
            outcome.sample.cadence_ms,
            outcome.sample.decision_id,
            outcome.sample.horizon_ms,
        )
        for outcome in outcomes
    )
    if len(identities) != len(set(identities)):
        raise CadenceOpportunityAuditError(
            "CADENCE_OPPORTUNITY_AUDIT_DUPLICATE_OUTCOME"
        )
    return tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.sample.target_end_ms,
                item.sample.market.canonical,
                item.sample.cadence_ms,
                item.sample.decision_id,
                item.sample.horizon_ms,
            ),
        )
    )
