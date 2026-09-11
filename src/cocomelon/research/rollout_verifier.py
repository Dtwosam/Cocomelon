from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cocomelon.research.contracts import TimeInterval
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError

ROOT_CANDIDATE_ID = "scheduled-research-root"
CHALLENGER_CANDIDATE_ID = "research-r1-exit-15m-v1"
ROOT_MAX_POSITION_AGE_MS = 1_200_000
CHALLENGER_MAX_POSITION_AGE_MS = 900_000
_TERMINAL_CHALLENGER_STATUSES = {"succeeded", "failed", "contaminated"}


@dataclass(frozen=True, slots=True)
class ResearchFanoutRolloutVerification:
    root_candidate_id: str
    challenger_candidate_id: str
    source_id: str
    source_interval: tuple[int, int]
    root_max_position_age_ms: int
    challenger_max_position_age_ms: int
    challenger_status: str


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid rollout artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"rollout artifact must be an object: {path}")
    return value


def _execution_horizon(candidate: dict[str, object], *, label: str) -> int:
    raw = candidate.get("execution_config_json")
    if not isinstance(raw, str):
        raise ValueError(f"{label} execution config is missing")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} execution config is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} execution config must be an object")
    value = payload.get("max_position_age_ms")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} max_position_age_ms is invalid")
    return value


def _candidate_audit_root(root: Path, candidate: dict[str, object]) -> Path:
    artifact_key = candidate.get("artifact_key")
    if not isinstance(artifact_key, str) or not artifact_key:
        raise ValueError("rollout candidate artifact key is invalid")
    matches = tuple(
        (root / "audit" / "decisions").glob(f"research-decision-stage-{artifact_key}-*")
    )
    if len(matches) != 1 or not matches[0].is_dir():
        raise ValueError("rollout candidate artifact is missing or ambiguous")
    return matches[0]


def _verify_candidate_decision_artifact(
    artifact_root: Path,
    *,
    candidate: dict[str, object],
    recording_session_digest: str,
    source_set_digest: str,
) -> None:
    output = artifact_root / "output"
    if not (output / "bundle.json").is_file():
        raise ValueError("rollout candidate artifact bundle is missing")
    payload = _load_json(output / "strategy-decisions.json")
    expected = {
        "candidate_code_revision": candidate.get("code_revision"),
        "candidate_config_digest": candidate.get("config_digest"),
        "recording_session_digest": recording_session_digest,
        "source_set_digest": source_set_digest,
    }
    if payload.get("schema_version") != 1:
        raise ValueError("rollout candidate artifact schema is invalid")
    for field, value in expected.items():
        if not isinstance(value, str) or not value or payload.get(field) != value:
            raise ValueError(f"rollout candidate artifact {field} does not match fanout")


def verify_research_fanout_rollout(
    campaign_root: str | Path,
    *,
    root_candidate_id: str = ROOT_CANDIDATE_ID,
    challenger_candidate_id: str = CHALLENGER_CANDIDATE_ID,
) -> ResearchFanoutRolloutVerification:
    root = Path(campaign_root)
    fanout = _load_json(root / "state" / "research-fanout.json")
    candidates = fanout.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 2:
        raise ValueError("rollout verification requires exactly root plus one challenger")
    by_id = {
        str(candidate.get("candidate_id")): candidate
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    if set(by_id) != {root_candidate_id, challenger_candidate_id}:
        raise ValueError("rollout candidate identities do not match expected root and challenger")
    root_candidate = by_id[root_candidate_id]
    challenger = by_id[challenger_candidate_id]
    if root_candidate.get("required") is not True or challenger.get("required") is not False:
        raise ValueError("rollout required/optional candidate roles are invalid")
    source_ids = {root_candidate.get("source_id"), challenger.get("source_id")}
    if len(source_ids) != 1 or not all(isinstance(value, str) and value for value in source_ids):
        raise ValueError("rollout candidates do not share one source_id")
    source_id = str(next(iter(source_ids)))

    capture = _load_json(root / "audit" / "capture" / "output" / "capture-source.json")
    start_ms = capture.get("start_ms")
    end_ms = capture.get("end_ms")
    if isinstance(start_ms, bool) or not isinstance(start_ms, int):
        raise ValueError("capture start_ms is invalid")
    if isinstance(end_ms, bool) or not isinstance(end_ms, int) or end_ms <= start_ms:
        raise ValueError("capture end_ms is invalid")
    recording_session_digest = capture.get("recording_session_digest")
    source_set_digest = capture.get("source_set_digest")
    if not isinstance(recording_session_digest, str) or not recording_session_digest:
        raise ValueError("capture recording_session_digest is invalid")
    if not isinstance(source_set_digest, str) or not source_set_digest:
        raise ValueError("capture source_set_digest is invalid")

    root_horizon = _execution_horizon(root_candidate, label="root")
    challenger_horizon = _execution_horizon(challenger, label="challenger")
    if root_horizon != ROOT_MAX_POSITION_AGE_MS:
        raise ValueError("root rollout is not using the immutable 20-minute horizon")
    if challenger_horizon != CHALLENGER_MAX_POSITION_AGE_MS:
        raise ValueError("challenger rollout is not using the immutable 15-minute horizon")

    connection = sqlite3.connect(root / "state" / "research.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT attempt_id, candidate_id, batch_id, source_id, status, start_ms, end_ms
               FROM research_runner_attempts
               WHERE attempt_id IN (?, ?)""",
            (str(root_candidate.get("attempt_id")), str(challenger.get("attempt_id"))),
        ).fetchall()
    finally:
        connection.close()
    latest = {str(row["candidate_id"]): row for row in rows}
    if set(latest) != {root_candidate_id, challenger_candidate_id}:
        raise ValueError("rollout registry is missing an exact fanout attempt")
    for candidate_id, candidate in (
        (root_candidate_id, root_candidate),
        (challenger_candidate_id, challenger),
    ):
        row = latest[candidate_id]
        if str(row["attempt_id"]) != candidate.get("attempt_id") or str(
            row["batch_id"]
        ) != candidate.get("batch_id"):
            raise ValueError("rollout registry attempt identity does not match fanout plan")
        if str(row["source_id"]) != source_id:
            raise ValueError("rollout registry source_id does not match shared capture")
        if (int(row["start_ms"]), int(row["end_ms"])) != (start_ms, end_ms):
            raise ValueError(
                "rollout candidates do not share the authenticated shared capture interval"
            )
    if str(latest[root_candidate_id]["status"]) != "succeeded":
        raise ValueError("required root rollout attempt did not succeed")
    challenger_status = str(latest[challenger_candidate_id]["status"])
    if challenger_status not in _TERMINAL_CHALLENGER_STATUSES:
        raise ValueError("optional challenger rollout attempt is not terminal")

    root_artifact = _candidate_audit_root(root, root_candidate)
    _verify_candidate_decision_artifact(
        root_artifact,
        candidate=root_candidate,
        recording_session_digest=recording_session_digest,
        source_set_digest=source_set_digest,
    )
    if challenger_status == "succeeded":
        challenger_artifact = _candidate_audit_root(root, challenger)
        _verify_candidate_decision_artifact(
            challenger_artifact,
            candidate=challenger,
            recording_session_digest=recording_session_digest,
            source_set_digest=source_set_digest,
        )

    registry = ResearchRegistry(root / "state" / "research.sqlite3")
    try:
        registry.assert_batch_disjoint_from_v4(TimeInterval(start_ms, end_ms))
    except ResearchRegistryError as exc:
        raise ValueError("rollout V4 authority does not cover a disjoint shared capture") from exc
    finally:
        registry.close()

    return ResearchFanoutRolloutVerification(
        root_candidate_id=root_candidate_id,
        challenger_candidate_id=challenger_candidate_id,
        source_id=source_id,
        source_interval=(start_ms, end_ms),
        root_max_position_age_ms=root_horizon,
        challenger_max_position_age_ms=challenger_horizon,
        challenger_status=challenger_status,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the first root+challenger research fan-out rollout artifact."
    )
    parser.add_argument("campaign_root")
    args = parser.parse_args(argv)
    result = verify_research_fanout_rollout(args.campaign_root)
    print(
        json.dumps(
            {
                "verified": True,
                "root_candidate_id": result.root_candidate_id,
                "challenger_candidate_id": result.challenger_candidate_id,
                "source_id": result.source_id,
                "source_interval": list(result.source_interval),
                "root_max_position_age_ms": result.root_max_position_age_ms,
                "challenger_max_position_age_ms": result.challenger_max_position_age_ms,
                "challenger_status": result.challenger_status,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
