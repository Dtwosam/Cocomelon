from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.cohort import (
    RESEARCH_CAPTURE_SECONDS,
    RESEARCH_ENTRY_WINDOW_MS,
    RESEARCH_EXECUTION_CONFIG_VERSION,
    RESEARCH_MAX_POSITION_AGE_MS,
    RESEARCH_REPLAY_CONFIG_VERSION,
    RESEARCH_REPLAY_ENGINE_VERSION,
)
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

_BOOTSTRAP_FAMILY_ID = "scheduled-research-bootstrap-v1"
_BOOTSTRAP_STARTING_CASH = Decimal("10000")


def _canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def research_bootstrap_config_digest() -> str:
    config = BaselineReplayConfig(
        starting_cash=_BOOTSTRAP_STARTING_CASH,
        execution=PaperExecutionConfig(
            config_version=RESEARCH_EXECUTION_CONFIG_VERSION,
            max_position_age_ms=RESEARCH_MAX_POSITION_AGE_MS,
        ),
        replay_engine_version=RESEARCH_REPLAY_ENGINE_VERSION,
        config_version=RESEARCH_REPLAY_CONFIG_VERSION,
    )
    return config.config_digest


def _require_code_revision(value: str) -> str:
    revision = value.strip().lower()
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ResearchRegistryError(
            "research bootstrap code_revision must be a 40-character commit SHA"
        )
    return revision


def ensure_bootstrap_candidate(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    code_revision: str,
) -> ResearchCandidateManifest:
    resolved_id = candidate_id.strip()
    if not resolved_id:
        raise ResearchRegistryError("research bootstrap candidate_id must not be empty")

    try:
        return registry.load_candidate(resolved_id)
    except ResearchRegistryError as exc:
        if str(exc) != f"candidate not found: {resolved_id}":
            raise

    manifest = ResearchCandidateManifest(
        candidate_id=resolved_id,
        family_id=_BOOTSTRAP_FAMILY_ID,
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest=research_bootstrap_config_digest(),
        code_revision=_require_code_revision(code_revision),
        execution_config_json=_canonical_json(
            {
                "config_version": RESEARCH_EXECUTION_CONFIG_VERSION,
                "max_position_age_ms": RESEARCH_MAX_POSITION_AGE_MS,
                "starting_cash": str(_BOOTSTRAP_STARTING_CASH),
            }
        ),
        risk_config_json=_canonical_json(
            {
                "capture_seconds": RESEARCH_CAPTURE_SECONDS,
                "economic_claim": "none",
                "entry_window_ms": RESEARCH_ENTRY_WINDOW_MS,
                "paper_only": True,
            }
        ),
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )
    registry.create_candidate(manifest)
    return registry.load_candidate(resolved_id)
