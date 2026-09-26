from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from cocomelon.continuous_paper import LEARNING_SOURCE_FILENAME, RUN_ID
from cocomelon.journal.store import JournalStore
from cocomelon.research.execution_learning_sync import sync_execution_learning_evidence
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_state_lineage import (
    append_learning_state_lineage,
    verify_learning_state_lineage,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
)
from cocomelon.research.research_learning_sync import ResearchLearningSyncReceipt

CONTINUOUS_PAPER_SUMMARY_FILENAME = "session-summary.json"


class ContinuousPaperLearningSyncError(RuntimeError):
    pass


def _mapping(path: Path, label: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuousPaperLearningSyncError(
            f"{label.upper()}_UNREADABLE"
        ) from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ContinuousPaperLearningSyncError(f"{label.upper()}_INVALID")
    return cast(dict[str, object], raw)


def _string(raw: dict[str, object], key: str, label: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContinuousPaperLearningSyncError(
            f"{label.upper()}_{key.upper()}_INVALID"
        )
    return value


def _integer(raw: dict[str, object], key: str, label: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContinuousPaperLearningSyncError(
            f"{label.upper()}_{key.upper()}_INVALID"
        )
    return value


def _require_commit_sha(value: str) -> None:
    if (
        len(value) != 40
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("upstream_head_sha must be a lowercase 40-character git SHA")


def _require_artifact_digest(value: str) -> None:
    digest = value.removeprefix("sha256:")
    if (
        not value.startswith("sha256:")
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("upstream_artifact_digest must be sha256:<lowercase hex>")


def _validate_source(
    paper_root: Path,
    *,
    upstream_head_sha: str,
) -> tuple[str, str]:
    source = _mapping(
        paper_root / LEARNING_SOURCE_FILENAME,
        "continuous_learning_source",
    )
    if source.get("schema_version") != 1:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_LEARNING_SOURCE_SCHEMA_INVALID"
        )
    if source.get("source_kind") != "continuous_paper":
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_LEARNING_SOURCE_KIND_INVALID"
        )
    if source.get("replay_run_id") != RUN_ID:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_LEARNING_SOURCE_REPLAY_INVALID"
        )
    if source.get("runtime_head_sha") != upstream_head_sha:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_LEARNING_SOURCE_HEAD_MISMATCH"
        )
    for field, expected in (
        ("research_only", True),
        ("promotion_eligible", False),
        ("execution_ready", False),
        ("live_orders", False),
    ):
        if source.get(field) is not expected:
            raise ContinuousPaperLearningSyncError(
                f"CONTINUOUS_LEARNING_SOURCE_{field.upper()}_INVALID"
            )
    candidate_id = _string(source, "candidate_id", "continuous_learning_source")
    candidate_spec_id = _string(
        source,
        "candidate_spec_id",
        "continuous_learning_source",
    )
    replay_config_digest = _string(
        source,
        "replay_config_digest",
        "continuous_learning_source",
    )
    if candidate_spec_id != replay_config_digest:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_LEARNING_SOURCE_SPEC_DIGEST_MISMATCH"
        )
    if (
        len(replay_config_digest) != 64
        or any(char not in "0123456789abcdef" for char in replay_config_digest)
    ):
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_LEARNING_SOURCE_CONFIG_DIGEST_INVALID"
        )
    expected_candidate_id = f"continuous-paper-{replay_config_digest[:24]}"
    if candidate_id != expected_candidate_id:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_LEARNING_SOURCE_CANDIDATE_INVALID"
        )
    return candidate_id, candidate_spec_id


def _verified_source_features(
    paper_root: Path,
) -> LearningFeatureSnapshotStore:
    summary = _mapping(
        paper_root / CONTINUOUS_PAPER_SUMMARY_FILENAME,
        "continuous_paper_summary",
    )
    if summary.get("live_orders") is not False:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_PAPER_SUMMARY_LIVE_AUTHORITY_INVALID"
        )
    expected_count = _integer(
        summary,
        "feature_snapshot_count",
        "continuous_paper_summary",
    )
    expected_digest = _string(
        summary,
        "feature_snapshot_state_digest",
        "continuous_paper_summary",
    )
    if (
        len(expected_digest) != 64
        or any(char not in "0123456789abcdef" for char in expected_digest)
    ):
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_PAPER_FEATURE_DIGEST_INVALID"
        )
    feature_store = LearningFeatureSnapshotStore(
        paper_root / "learning-features"
    )
    verified = feature_store.iter_verified()
    if len(verified) != expected_count:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_PAPER_FEATURE_COUNT_MISMATCH"
        )
    if feature_store.state_digest != expected_digest:
        raise ContinuousPaperLearningSyncError(
            "CONTINUOUS_PAPER_FEATURE_DIGEST_MISMATCH"
        )
    return feature_store


def sync_continuous_paper_learning(
    paper_root: str | Path,
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
    _require_artifact_digest(upstream_artifact_digest)

    paper = Path(paper_root)
    state = Path(state_root)
    candidate_id, candidate_spec_id = _validate_source(
        paper,
        upstream_head_sha=upstream_head_sha,
    )
    source_features = _verified_source_features(paper)

    ledger = LearningEvidenceLedger(state / "ledger")
    destination_features = LearningFeatureSnapshotStore(state / "features")
    before_records = ledger.iter_records()
    before_snapshots = destination_features.iter_verified()
    before_learning_record_count = len(before_records)
    before_learning_state_digest = ledger.state_digest
    before_feature_snapshot_count = len(before_snapshots)
    before_feature_state_digest = destination_features.state_digest
    verify_learning_state_lineage(
        state,
        learning_record_count=before_learning_record_count,
        learning_state_digest=before_learning_state_digest,
        feature_snapshot_count=before_feature_snapshot_count,
        feature_state_digest=before_feature_state_digest,
    )

    journal = JournalStore(paper / "journal.sqlite3")
    try:
        result = sync_execution_learning_evidence(
            journal,
            source_features,
            ledger,
            candidate_id=candidate_id,
            kind=LearningEvidenceKind.PAPER_EXECUTION,
            research_eligible_at_ms=None,
            research_eligible_at_trade_close=True,
            expected_replay_run_id=RUN_ID,
            candidate_spec_id=candidate_spec_id,
            campaign_id=(
                f"continuous-paper-run-{upstream_run_id}-"
                f"{upstream_run_attempt}"
            ),
            destination_feature_store=destination_features,
        )
    finally:
        journal.close()

    records = ledger.iter_records()
    snapshots = destination_features.iter_verified()
    learning_state_digest = ledger.state_digest
    feature_state_digest = destination_features.state_digest
    lineage = append_learning_state_lineage(
        state,
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        required_candidate_ids=(candidate_id,),
        scanned_trades=result.scanned_trades,
        created_records=result.created_records,
        existing_records=result.existing_records,
        created_feature_snapshots=result.created_feature_snapshots,
        existing_feature_snapshots=result.existing_feature_snapshots,
        before_learning_record_count=before_learning_record_count,
        before_learning_state_digest=before_learning_state_digest,
        before_feature_snapshot_count=before_feature_snapshot_count,
        before_feature_state_digest=before_feature_state_digest,
        after_learning_record_count=len(records),
        after_learning_state_digest=learning_state_digest,
        after_feature_snapshot_count=len(snapshots),
        after_feature_state_digest=feature_state_digest,
    )
    return ResearchLearningSyncReceipt(
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        required_candidate_ids=(candidate_id,),
        scanned_trades=result.scanned_trades,
        created_records=result.created_records,
        existing_records=result.existing_records,
        created_feature_snapshots=result.created_feature_snapshots,
        existing_feature_snapshots=result.existing_feature_snapshots,
        learning_record_count=len(records),
        learning_state_digest=learning_state_digest,
        feature_snapshot_count=len(snapshots),
        feature_state_digest=feature_state_digest,
        lineage_sequence=lineage.sequence,
        lineage_entry_id=lineage.entry_id,
    )
