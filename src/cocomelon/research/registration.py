from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.cohort import (
    RESEARCH_REPLAY_CONFIG_VERSION,
    RESEARCH_REPLAY_ENGINE_VERSION,
    research_replay_config_from_candidate,
)
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def register_candidate_spec(
    registry: ResearchRegistry,
    spec_path: str | Path,
) -> ResearchCandidateManifest:
    payload = _mapping(
        json.loads(Path(spec_path).read_text(encoding="utf-8")),
        "candidate spec",
    )
    if set(payload) != {"candidate_id", "parent_candidate_id", "execution_config"}:
        raise ValueError("candidate spec fields are not supported")

    candidate_id = _string(payload.get("candidate_id"), "candidate_id")
    parent_candidate_id = _string(payload.get("parent_candidate_id"), "parent_candidate_id")
    parent = registry.load_candidate(parent_candidate_id)
    parent_replay_config = research_replay_config_from_candidate(parent)

    execution = _mapping(payload.get("execution_config"), "execution_config")
    if set(execution) != {"config_version", "max_position_age_ms", "starting_cash"}:
        raise ValueError("candidate execution config fields are not supported")
    config_version = _string(execution.get("config_version"), "execution config_version")
    max_position_age_ms = execution.get("max_position_age_ms")
    if isinstance(max_position_age_ms, bool) or not isinstance(max_position_age_ms, int):
        raise ValueError("execution max_position_age_ms must be an integer")
    starting_cash_raw = _string(execution.get("starting_cash"), "execution starting_cash")
    try:
        starting_cash = Decimal(starting_cash_raw)
    except InvalidOperation as exc:
        raise ValueError("execution starting_cash must be decimal") from exc
    if not starting_cash.is_finite() or starting_cash <= 0:
        raise ValueError("execution starting_cash must be positive and finite")
    if starting_cash != parent_replay_config.starting_cash:
        raise ValueError("candidate starting_cash must match parent")

    replay_config = BaselineReplayConfig(
        starting_cash=starting_cash,
        execution=PaperExecutionConfig(
            config_version=config_version,
            max_position_age_ms=max_position_age_ms,
        ),
        replay_engine_version=RESEARCH_REPLAY_ENGINE_VERSION,
        config_version=RESEARCH_REPLAY_CONFIG_VERSION,
    )
    execution_config_json = json.dumps(
        execution,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    manifest = ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id=parent.family_id,
        parent_candidate_id=parent.candidate_id,
        ancestor_candidate_ids=parent.ancestor_candidate_ids + (parent.candidate_id,),
        config_digest=replay_config.config_digest,
        code_revision=parent.code_revision,
        execution_config_json=execution_config_json,
        risk_config_json=parent.risk_config_json,
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )
    research_replay_config_from_candidate(manifest)
    try:
        existing = registry.load_candidate(candidate_id)
    except ResearchRegistryError as exc:
        if str(exc) != f"candidate not found: {candidate_id}":
            raise
    else:
        immutable_fields_match = (
            existing.family_id == manifest.family_id
            and existing.parent_candidate_id == manifest.parent_candidate_id
            and existing.ancestor_candidate_ids == manifest.ancestor_candidate_ids
            and existing.config_digest == manifest.config_digest
            and existing.code_revision == manifest.code_revision
            and existing.execution_config_json == manifest.execution_config_json
            and existing.risk_config_json == manifest.risk_config_json
        )
        if not immutable_fields_match:
            raise ResearchRegistryError(
                f"candidate already exists with different immutable identity: {candidate_id}"
            )
        return existing
    registry.create_candidate(manifest)
    return registry.load_candidate(candidate_id)
