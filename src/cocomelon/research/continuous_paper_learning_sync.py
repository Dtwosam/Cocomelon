from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.continuous_paper import RUN_ID
from cocomelon.journal.store import JournalStore
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

CONTINUOUS_PAPER_LEARNING_SYNC_SCHEMA_VERSION = 1
CONTINUOUS_PAPER_LEARNING_CANDIDATE_ID = RUN_ID


class ContinuousPaperLearningSyncError(RuntimeError):
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
        raise ContinuousPaperLearningSyncError(
            f"{field.upper()}_MISSING"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuousPaperLearningSyncError(
            f"{field.upper()}_INVALID"
        ) from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ContinuousPaperLearningSyncError(f"{field.upper()}_INVALID")
    return cast(dict[str, object], raw)


def _integer(raw: dict[str, object], field: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContinuousPaperLearningSyncError(f"{field.upper()}_INVALID")
    return value


def _string(raw: dict[str, object], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContinuousPaperLearningSyncError(f"{field.upper()}_INVALID")
    return value


def _boolean(raw: dict[str, object], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ContinuousPaperLearningSyncError(f"{field.upper()}_INVALID")
    return value


def _require_commit_sha(value: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("upstream_head_sha must be lowercase 40-character git SHA")


def _require_artifact_digest(value: str) -> None:
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError(
            "upstream_artifact_digest must be sha256:<lowercase hex>"
        )


def _require_state_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContinuousPaperLearningSyncError(f"{field.upper()}_INVALID")


@dataclass(frozen=True, slots=True)
class ContinuousPaperLearningSyncReceipt:
    upstream_run_id: int
    upstream_run_attempt: int
    upstream_head_sha: str
    upstream_artifact_id: int
    upstream_artifact_digest: str
    worker_started_at_ms: int
    worker_ended_at_ms: int
    learning_feature_capture_started_at_ms: int
    scanned_trades: int
    skipped_pre_activation_trades: int
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
    schema_version: int = CONTINUOUS_PAPER_LEARNING_SYNC_SCHEMA_VERSION

    def identity_payload(self) -> dict[str, object]:
        return {
            "upstream_run_id": self.upstream_run_id,
            "upstream_run_attempt": self.upstream_run_attempt,
            "upstream_head_sha": self.upstream_head_sha,
            "upstream_artifact_id": self.upstream_artifact_id,
            "upstream_artifact_digest": self.upstream_artifact_digest,
            "worker_started_at_ms": self.worker_started_at_ms,
            "worker_ended_at_ms": self.worker_ended_at_ms,
            "learning_feature_capture_started_at_ms": (
                self.learning_feature_capture_started_at_ms
            ),
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
            "command": "continuous-paper-learning-sync",
            **self.identity_payload(),
            "candidate_id": CONTINUOUS_PAPER_LEARNING_CANDIDATE_ID,
            "scanned_trades": self.scanned_trades,
            "skipped_pre_activation_trades": self.skipped_pre_activation_trades,
            "created_records": self.created_records,
            "existing_records": self.existing_records,
            "created_feature_snapshots": self.created_feature_snapshots,
            "existing_feature_snapshots": self.existing_feature_snapshots,
            "receipt_id": self.receipt_id,
        }


def sync_continuous_paper_learning(
    worker_root: str | Path,
    *,
    state_root: str | Path,
    upstream_run_id: int,
    upstream_run_attempt: int,
    upstream_head_sha: str,
    upstream_artifact_id: int,
    upstream_artifact_digest: str,
) -> ContinuousPaperLearningSyncReceipt:
    if upstream_run_id <= 0:
        raise ValueError("upstream_run_id must be positive")
    if upstream_run_attempt <= 0:
        raise ValueError("upstream_run_attempt must be positive")
    if upstream_artifact_id <= 0:
        raise ValueError("upstream_artifact_id must be positive")
    _require_commit_sha(upstream_head_sha)
    _require_artifact_digest(upstream_artifact_digest)

    worker = Path(worker_root)
    state = Path(state_root)
    summary = _mapping(worker / "session-summary.json", "session_summary")

    if _boolean(summary, "live_orders"):
        raise ContinuousPaperLearningSyncError("LIVE_ORDERS_FORBIDDEN")
    if not _boolean(summary, "network_access"):
        raise ContinuousPaperLearningSyncError("MAINNET_NETWORK_ACCESS_REQUIRED")

    started_at_ms = _integer(summary, "started_at_ms")
    ended_at_ms = _integer(summary, "ended_at_ms")
    activation_ms = _integer(
        summary,
        "learning_feature_capture_started_at_ms",
    )
    if ended_at_ms < started_at_ms:
        raise ContinuousPaperLearningSyncError("WORKER_TIME_RANGE_INVALID")
    if activation_ms > ended_at_ms:
        raise ContinuousPaperLearningSyncError(
            "FEATURE_CAPTURE_ACTIVATION_AFTER_WORKER_END"
        )

    expected_feature_count = _integer(summary, "feature_snapshot_count")
    expected_feature_digest = _string(
        summary,
        "feature_snapshot_state_digest",
    )
    _require_state_digest(expected_feature_digest, "feature_snapshot_state_digest")

    source_features_root = worker / "learning-features"
    if not source_features_root.is_dir():
        raise ContinuousPaperLearningSyncError("FEATURE_STORE_MISSING")
    source_features = LearningFeatureSnapshotStore(source_features_root)
    verified_source_features = source_features.iter_verified()
    if len(verified_source_features) != expected_feature_count:
        raise ContinuousPaperLearningSyncError("FEATURE_STORE_COUNT_MISMATCH")
    if source_features.state_digest != expected_feature_digest:
        raise ContinuousPaperLearningSyncError("FEATURE_STORE_DIGEST_MISMATCH")

    journal_path = worker / "journal.sqlite3"
    if not journal_path.is_file():
        raise ContinuousPaperLearningSyncError("JOURNAL_MISSING")
    journal = JournalStore(journal_path)
    try:
        source_trades = tuple(journal.iter_trades())
        expected_trade_count = _integer(summary, "closed_trades")
        if len(source_trades) != expected_trade_count:
            raise ContinuousPaperLearningSyncError("JOURNAL_TRADE_COUNT_MISMATCH")

        ledger = LearningEvidenceLedger(state / "ledger")
        destination_features = LearningFeatureSnapshotStore(state / "features")
        before_records = ledger.iter_records()
        before_features = destination_features.iter_verified()

        verify_learning_state_lineage(
            state,
            learning_record_count=len(before_records),
            learning_state_digest=ledger.state_digest,
            feature_snapshot_count=len(before_features),
            feature_state_digest=destination_features.state_digest,
        )

        result = sync_execution_learning_evidence(
            journal,
            source_features,
            ledger,
            candidate_id=CONTINUOUS_PAPER_LEARNING_CANDIDATE_ID,
            kind=LearningEvidenceKind.PAPER_EXECUTION,
            research_eligible_at_ms=None,
            expected_replay_run_id=RUN_ID,
            destination_feature_store=destination_features,
            opened_at_or_after_ms=activation_ms,
        )
    finally:
        journal.close()

    if result.scanned_trades != expected_trade_count:
        raise ContinuousPaperLearningSyncError("SCANNED_TRADE_COUNT_MISMATCH")

    after_records = ledger.iter_records()
    after_features = destination_features.iter_verified()
    learning_state_digest = ledger.state_digest
    feature_state_digest = destination_features.state_digest

    lineage = append_learning_state_lineage(
        state,
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        required_candidate_ids=(CONTINUOUS_PAPER_LEARNING_CANDIDATE_ID,),
        scanned_trades=result.scanned_trades,
        created_records=result.created_records,
        existing_records=result.existing_records,
        created_feature_snapshots=result.created_feature_snapshots,
        existing_feature_snapshots=result.existing_feature_snapshots,
        before_learning_record_count=len(before_records),
        before_learning_state_digest=(
            LearningEvidenceLedger(state / "ledger").state_digest
            if False
            else ""
        ),
        before_feature_snapshot_count=len(before_features),
        before_feature_state_digest="",
        after_learning_record_count=len(after_records),
        after_learning_state_digest=learning_state_digest,
        after_feature_snapshot_count=len(after_features),
        after_feature_state_digest=feature_state_digest,
    )

    return ContinuousPaperLearningSyncReceipt(
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        worker_started_at_ms=started_at_ms,
        worker_ended_at_ms=ended_at_ms,
        learning_feature_capture_started_at_ms=activation_ms,
        scanned_trades=result.scanned_trades,
        skipped_pre_activation_trades=result.skipped_pre_activation_trades,
        created_records=result.created_records,
        existing_records=result.existing_records,
        created_feature_snapshots=result.created_feature_snapshots,
        existing_feature_snapshots=result.existing_feature_snapshots,
        learning_record_count=len(after_records),
        learning_state_digest=learning_state_digest,
        feature_snapshot_count=len(after_features),
        feature_state_digest=feature_state_digest,
        lineage_sequence=lineage.sequence,
        lineage_entry_id=lineage.entry_id,
    )
