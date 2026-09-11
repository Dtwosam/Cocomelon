from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.contracts import ResearchCandidateManifest
from cocomelon.research.registry import ResearchRegistry


@dataclass(frozen=True, slots=True)
class ResearchFanoutCandidate:
    candidate_id: str
    code_revision: str
    config_digest: str
    execution_config_json: str
    risk_config_json: str
    required: bool
    attempt_id: str
    batch_id: str
    source_id: str
    artifact_key: str

    @property
    def manifest(self) -> ResearchCandidateManifest:
        payload = json.loads(self.execution_config_json)
        if not isinstance(payload, dict):
            raise ValueError("research fanout execution config must be an object")
        return ResearchCandidateManifest(
            candidate_id=self.candidate_id,
            family_id="fanout-runtime",
            parent_candidate_id=None,
            ancestor_candidate_ids=(),
            config_digest=self.config_digest,
            code_revision=self.code_revision,
            execution_config_json=self.execution_config_json,
            risk_config_json=self.risk_config_json,
            state=_draft_state(),
            first_observation_ms=None,
            last_observation_ms=None,
            source_provenance_ids=(),
            local_touched_intervals=(),
            effective_touched_intervals=(),
            performance_report_ids=(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_key": self.artifact_key,
            "attempt_id": self.attempt_id,
            "batch_id": self.batch_id,
            "candidate_id": self.candidate_id,
            "code_revision": self.code_revision,
            "config_digest": self.config_digest,
            "execution_config_json": self.execution_config_json,
            "required": self.required,
            "risk_config_json": self.risk_config_json,
            "source_id": self.source_id,
        }

    def to_matrix_dict(self) -> dict[str, object]:
        return {
            "artifact_key": self.artifact_key,
            "attempt_id": self.attempt_id,
            "batch_id": self.batch_id,
            "candidate_id": self.candidate_id,
            "code_revision": self.code_revision,
            "required": self.required,
            "source_id": self.source_id,
        }


def _draft_state():
    from cocomelon.research.contracts import ResearchCandidateState

    return ResearchCandidateState.DRAFT


def _require_id(value: str, field: str) -> str:
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{field} must not be empty")
    return resolved


def _require_revision(value: str) -> str:
    revision = value.strip().lower()
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise ValueError("research fanout code_revision must be a 40-character commit SHA")
    return revision


def _artifact_key(candidate_id: str) -> str:
    return hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]


def _fanout_candidate(
    manifest: ResearchCandidateManifest,
    *,
    required: bool,
    run_id: str,
    run_attempt: int,
    source_id: str,
) -> ResearchFanoutCandidate:
    candidate_id = _require_id(manifest.candidate_id, "candidate_id")
    return ResearchFanoutCandidate(
        candidate_id=candidate_id,
        code_revision=_require_revision(manifest.code_revision),
        config_digest=manifest.config_digest,
        execution_config_json=manifest.execution_config_json,
        risk_config_json=manifest.risk_config_json,
        required=required,
        attempt_id=f"research-{run_id}-{run_attempt}-{candidate_id}",
        batch_id=f"research-batch-{run_id}-{run_attempt}-{candidate_id}",
        source_id=source_id,
        artifact_key=_artifact_key(candidate_id),
    )


def resolve_research_fanout(
    registry: ResearchRegistry,
    *,
    root_candidate_id: str,
    challenger_candidate_id: str | None,
    run_id: str,
    run_attempt: int,
) -> tuple[ResearchFanoutCandidate, ...]:
    root_id = _require_id(root_candidate_id, "root_candidate_id")
    resolved_run_id = _require_id(run_id, "run_id")
    if run_attempt <= 0:
        raise ValueError("run_attempt must be positive")
    challenger_id = None
    if challenger_candidate_id is not None and challenger_candidate_id.strip():
        challenger_id = challenger_candidate_id.strip()
        if challenger_id == root_id:
            raise ValueError("research challenger must be distinct from root candidate")

    source_id = f"research-mainnet-{resolved_run_id}-{run_attempt}"
    root = _fanout_candidate(
        registry.load_candidate(root_id),
        required=True,
        run_id=resolved_run_id,
        run_attempt=run_attempt,
        source_id=source_id,
    )
    if challenger_id is None:
        return (root,)
    challenger = _fanout_candidate(
        registry.load_candidate(challenger_id),
        required=False,
        run_id=resolved_run_id,
        run_attempt=run_attempt,
        source_id=source_id,
    )
    if challenger.artifact_key == root.artifact_key:
        raise ValueError("research fanout artifact keys must be distinct")
    return (root, challenger)


def write_research_fanout_plan(
    path: str | Path,
    candidates: tuple[ResearchFanoutCandidate, ...],
) -> None:
    if not candidates or len(candidates) > 2:
        raise ValueError("research fanout must contain one or two candidates")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "candidates": [candidate.to_dict() for candidate in candidates],
        "schema_version": 1,
    }
    target.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
