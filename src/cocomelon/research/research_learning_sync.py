from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.journal.store import JournalStore
from cocomelon.research.artifact import verify_research_batch_artifact
from cocomelon.research.execution_learning_sync import (
    sync_execution_learning_evidence,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_state_lineage import (
    append_learning_state_lineage,
    verify_learning_state_lineage,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
)

RESEARCH_LEARNING_SYNC_SCHEMA_VERSION = 1


class ResearchLearningSyncError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(path: Path, field: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResearchLearningSyncError(f"{field.upper()}_MISSING") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchLearningSyncError(f"{field.upper()}_INVALID") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ResearchLearningSyncError(f"{field.upper()}_INVALID")
    return cast(dict[str, object], raw)


def _string(raw: dict[str, object], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchLearningSyncError(f"{field.upper()}_INVALID")
    return value


def _integer(raw: dict[str, object], field: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResearchLearningSyncError(f"{field.upper()}_INVALID")
    return value


def _boolean(raw: dict[str, object], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ResearchLearningSyncError(f"{field.upper()}_INVALID")
    return value


def _require_sha256_digest(value: str) -> None:
    prefix = "sha256:"
    digest = value.removeprefix(prefix)
    if (
        not value.startswith(prefix)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("upstream_artifact_digest must be sha256:<lowercase hex>")


def _require_commit_sha(value: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("upstream_head_sha must be lowercase 40-character git SHA")


@dataclass(frozen=True, slots=True)
class ResearchLearningSyncReceipt:
    upstream_run_id: int
    upstream_run_attempt: int
    upstream_head_sha: str
    upstream_artifact_id: int
    upstream_artifact_digest: str
    required_candidate_ids: tuple[str, ...]
    scanned_trades: int
    created_records: int
    existing_records: int
    created_feature_snapshots: int
    existing_feature_snapshots: int
    learning_record_count: int
    learning_state_digest: str
    feature_snapshot_count: int
    feature_state_digest: str
    lineage_sequence: int
    lineage_entry_id: str
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = RESEARCH_LEARNING_SYNC_SCHEMA_VERSION

    def identity_payload(self) -> dict[str, object]:
        return {
            "upstream_run_id": self.upstream_run_id,
            "upstream_run_attempt": self.upstream_run_attempt,
            "upstream_head_sha": self.upstream_head_sha,
            "upstream_artifact_id": self.upstream_artifact_id,
            "upstream_artifact_digest": self.upstream_artifact_digest,
            "required_candidate_ids": self.required_candidate_ids,
            "learning_record_count": self.learning_record_count,
            "learning_state_digest": self.learning_state_digest,
            "feature_snapshot_count": self.feature_snapshot_count,
            "feature_state_digest": self.feature_state_digest,
            "lineage_sequence": self.lineage_sequence,
            "lineage_entry_id": self.lineage_entry_id,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "scanned_trades": self.scanned_trades,
            "created_records": self.created_records,
            "existing_records": self.existing_records,
            "created_feature_snapshots": self.created_feature_snapshots,
            "existing_feature_snapshots": self.existing_feature_snapshots,
            "receipt_id": self.receipt_id,
        }


def _required_candidates(campaign_root: Path) -> tuple[dict[str, object], ...]:
    fanout = _mapping(
        campaign_root / "state" / "research-fanout.json",
        "research_fanout",
    )
    if fanout.get("schema_version") != 1:
        raise ResearchLearningSyncError("RESEARCH_FANOUT_SCHEMA_INVALID")
    raw_candidates = fanout.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ResearchLearningSyncError("RESEARCH_FANOUT_CANDIDATES_INVALID")

    candidates: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for item in raw_candidates:
        if not isinstance(item, dict) or not all(isinstance(key, str) for key in item):
            raise ResearchLearningSyncError("RESEARCH_FANOUT_CANDIDATE_INVALID")
        candidate = cast(dict[str, object], item)
        candidate_id = _string(candidate, "candidate_id")
        artifact_key = _string(candidate, "artifact_key")
        if candidate_id in seen_ids or artifact_key in seen_keys:
            raise ResearchLearningSyncError("RESEARCH_FANOUT_CANDIDATE_DUPLICATE")
        seen_ids.add(candidate_id)
        seen_keys.add(artifact_key)
        if _boolean(candidate, "required"):
            candidates.append(candidate)

    if not candidates:
        raise ResearchLearningSyncError("RESEARCH_REQUIRED_CANDIDATE_MISSING")
    return tuple(sorted(candidates, key=lambda item: _string(item, "candidate_id")))


def _verified_feature_store(
    output_root: Path,
    *,
    expected_replay_run_id: str,
) -> LearningFeatureSnapshotStore:
    feature_root = output_root / "learning-features"
    if not feature_root.is_dir():
        raise ResearchLearningSyncError("FEATURE_STORE_MISSING")

    replay = _mapping(output_root / "replay.json", "replay")
    if _string(replay, "run_id") != expected_replay_run_id:
        raise ResearchLearningSyncError("FEATURE_STORE_REPLAY_MISMATCH")
    expected_count = _integer(replay, "feature_snapshot_count")
    expected_digest = _string(replay, "feature_snapshot_state_digest")
    if len(expected_digest) != 64:
        raise ResearchLearningSyncError("FEATURE_STORE_DIGEST_INVALID")

    feature_store = LearningFeatureSnapshotStore(feature_root)
    verified = feature_store.iter_verified()
    if len(verified) != expected_count:
        raise ResearchLearningSyncError("FEATURE_STORE_COUNT_MISMATCH")
    if feature_store.state_digest != expected_digest:
        raise ResearchLearningSyncError("FEATURE_STORE_DIGEST_MISMATCH")
    return feature_store


def _runner_end_ms(output_root: Path) -> int:
    runner = _mapping(output_root / "runner.json", "runner")
    if runner.get("status") != "succeeded":
        raise ResearchLearningSyncError("RESEARCH_RUNNER_NOT_SUCCEEDED")
    if runner.get("label") != "TOUCHED / NON-PROMOTIONAL":
        raise ResearchLearningSyncError("RESEARCH_RUNNER_LABEL_INVALID")
    return _integer(runner, "end_ms")


def sync_research_campaign_learning(
    campaign_root: str | Path,
    *,
    state_root: str | Path,
    upstream_run_id: int,
    upstream_run_attempt: int,
    upstream_head_sha: str,
    upstream_artifact_id: int,
    upstream_artifact_digest: str,
) -> ResearchLearningSyncReceipt:
    if upstream_run_id <= 0:
        raise ValueError("upstream_run_id must be positive")
    if upstream_run_attempt <= 0:
        raise ValueError("upstream_run_attempt must be positive")
    if upstream_artifact_id <= 0:
        raise ValueError("upstream_artifact_id must be positive")
    _require_commit_sha(upstream_head_sha)
    _require_sha256_digest(upstream_artifact_digest)

    campaign = Path(campaign_root)
    state = Path(state_root)
    ledger = LearningEvidenceLedger(state / "ledger")
    destination_features = LearningFeatureSnapshotStore(state / "features")

    before_records = ledger.iter_records()
    before_feature_snapshots = destination_features.iter_verified()
    before_learning_record_count = len(before_records)
    before_learning_state_digest = ledger.state_digest
    before_feature_snapshot_count = len(before_feature_snapshots)
    before_feature_state_digest = destination_features.state_digest
    verify_learning_state_lineage(
        state,
        learning_record_count=before_learning_record_count,
        learning_state_digest=before_learning_state_digest,
        feature_snapshot_count=before_feature_snapshot_count,
        feature_state_digest=before_feature_state_digest,
    )

    scanned_trades = 0
    created_records = 0
    existing_records = 0
    created_features = 0
    existing_features = 0
    candidate_ids: list[str] = []

    for candidate in _required_candidates(campaign):
        candidate_id = _string(candidate, "candidate_id")
        artifact_key = _string(candidate, "artifact_key")
        batch_id = _string(candidate, "batch_id")
        source_id = _string(candidate, "source_id")
        output = campaign / "audit" / "evaluated" / artifact_key / "output"

        verified_batch = verify_research_batch_artifact(
            output,
            batch_id=batch_id,
            source_id=source_id,
        )
        trigger_head_path = output / "trigger-head.txt"
        try:
            trigger_head = trigger_head_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ResearchLearningSyncError("UPSTREAM_HEAD_BINDING_MISSING") from exc
        if trigger_head != upstream_head_sha:
            raise ResearchLearningSyncError("UPSTREAM_HEAD_MISMATCH")

        source_features = _verified_feature_store(
            output,
            expected_replay_run_id=verified_batch.replay_run_id,
        )
        eligible_at_ms = _runner_end_ms(output)
        if eligible_at_ms < verified_batch.interval.end_ms:
            raise ResearchLearningSyncError("RESEARCH_ELIGIBILITY_BOUNDARY_INVALID")

        journal = JournalStore(output / "journal.sqlite3")
        try:
            result = sync_execution_learning_evidence(
                journal,
                source_features,
                ledger,
                candidate_id=candidate_id,
                kind=LearningEvidenceKind.PAPER_EXECUTION,
                research_eligible_at_ms=eligible_at_ms,
                expected_replay_run_id=verified_batch.replay_run_id,
                destination_feature_store=destination_features,
            )
        finally:
            journal.close()

        if result.scanned_trades != len(verified_batch.trade_ids):
            raise ResearchLearningSyncError("RESEARCH_TRADE_COUNT_MISMATCH")

        candidate_ids.append(candidate_id)
        scanned_trades += result.scanned_trades
        created_records += result.created_records
        existing_records += result.existing_records
        created_features += result.created_feature_snapshots
        existing_features += result.existing_feature_snapshots

    records = ledger.iter_records()
    feature_snapshots = destination_features.iter_verified()
    learning_state_digest = ledger.state_digest
    feature_state_digest = destination_features.state_digest
    lineage = append_learning_state_lineage(
        state,
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        required_candidate_ids=tuple(candidate_ids),
        scanned_trades=scanned_trades,
        created_records=created_records,
        existing_records=existing_records,
        created_feature_snapshots=created_features,
        existing_feature_snapshots=existing_features,
        before_learning_record_count=before_learning_record_count,
        before_learning_state_digest=before_learning_state_digest,
        before_feature_snapshot_count=before_feature_snapshot_count,
        before_feature_state_digest=before_feature_state_digest,
        after_learning_record_count=len(records),
        after_learning_state_digest=learning_state_digest,
        after_feature_snapshot_count=len(feature_snapshots),
        after_feature_state_digest=feature_state_digest,
    )
    return ResearchLearningSyncReceipt(
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        required_candidate_ids=tuple(candidate_ids),
        scanned_trades=scanned_trades,
        created_records=created_records,
        existing_records=existing_records,
        created_feature_snapshots=created_features,
        existing_feature_snapshots=existing_features,
        learning_record_count=len(records),
        learning_state_digest=learning_state_digest,
        feature_snapshot_count=len(feature_snapshots),
        feature_state_digest=feature_state_digest,
        lineage_sequence=lineage.sequence,
        lineage_entry_id=lineage.entry_id,
    )
