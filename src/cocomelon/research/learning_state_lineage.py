from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

LEARNING_STATE_LINEAGE_SCHEMA_VERSION = 1


class LearningStateLineageError(RuntimeError):
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


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_artifact_digest(value: str) -> bool:
    return value.startswith("sha256:") and _is_sha256(value.removeprefix("sha256:"))


def _is_commit_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def _require_non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _require_positive(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class LearningStateLineageEntry:
    sequence: int
    previous_entry_id: str | None
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
    before_learning_record_count: int
    before_learning_state_digest: str
    before_feature_snapshot_count: int
    before_feature_state_digest: str
    after_learning_record_count: int
    after_learning_state_digest: str
    after_feature_snapshot_count: int
    after_feature_state_digest: str
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_STATE_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.sequence, "sequence")
        _require_positive(self.upstream_run_id, "upstream_run_id")
        _require_positive(self.upstream_run_attempt, "upstream_run_attempt")
        _require_positive(self.upstream_artifact_id, "upstream_artifact_id")
        for field, count_value in (
            ("scanned_trades", self.scanned_trades),
            ("created_records", self.created_records),
            ("existing_records", self.existing_records),
            ("created_feature_snapshots", self.created_feature_snapshots),
            ("existing_feature_snapshots", self.existing_feature_snapshots),
            ("before_learning_record_count", self.before_learning_record_count),
            ("before_feature_snapshot_count", self.before_feature_snapshot_count),
            ("after_learning_record_count", self.after_learning_record_count),
            ("after_feature_snapshot_count", self.after_feature_snapshot_count),
        ):
            _require_non_negative(count_value, field)
        if self.previous_entry_id is not None and not _is_sha256(self.previous_entry_id):
            raise ValueError("previous_entry_id must be a lowercase sha256 hex digest")
        if not _is_commit_sha(self.upstream_head_sha):
            raise ValueError("upstream_head_sha must be a lowercase 40-character git SHA")
        if not _is_artifact_digest(self.upstream_artifact_digest):
            raise ValueError("upstream_artifact_digest must be sha256:<lowercase hex>")
        for field, digest_value in (
            ("before_learning_state_digest", self.before_learning_state_digest),
            ("before_feature_state_digest", self.before_feature_state_digest),
            ("after_learning_state_digest", self.after_learning_state_digest),
            ("after_feature_state_digest", self.after_feature_state_digest),
        ):
            if not _is_sha256(digest_value):
                raise ValueError(f"{field} must be a lowercase sha256 hex digest")
        if not self.required_candidate_ids:
            raise ValueError("required_candidate_ids must not be empty")
        if (
            tuple(sorted(self.required_candidate_ids)) != self.required_candidate_ids
            or len(set(self.required_candidate_ids)) != len(self.required_candidate_ids)
            or any(not item.strip() for item in self.required_candidate_ids)
        ):
            raise ValueError("required_candidate_ids must be unique sorted non-empty strings")
        if self.created_records + self.existing_records != self.scanned_trades:
            raise ValueError("learning lineage trade counts do not reconcile")
        if (
            self.created_feature_snapshots + self.existing_feature_snapshots
            != self.scanned_trades
        ):
            raise ValueError("learning lineage feature counts do not reconcile")
        if (
            self.before_learning_record_count + self.created_records
            != self.after_learning_record_count
        ):
            raise ValueError("learning lineage record transition does not reconcile")
        if (
            self.before_feature_snapshot_count + self.created_feature_snapshots
            != self.after_feature_snapshot_count
        ):
            raise ValueError("learning lineage feature transition does not reconcile")
        if self.research_only is not True:
            raise ValueError("learning lineage must remain research-only")
        if self.promotion_eligible is not False:
            raise ValueError("learning lineage cannot authorize promotion")
        if self.execution_ready is not False:
            raise ValueError("learning lineage cannot authorize execution")
        if self.schema_version != LEARNING_STATE_LINEAGE_SCHEMA_VERSION:
            raise ValueError("unsupported learning lineage schema version")

    def identity_payload(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "previous_entry_id": self.previous_entry_id,
            "upstream_run_id": self.upstream_run_id,
            "upstream_run_attempt": self.upstream_run_attempt,
            "upstream_head_sha": self.upstream_head_sha,
            "upstream_artifact_id": self.upstream_artifact_id,
            "upstream_artifact_digest": self.upstream_artifact_digest,
            "required_candidate_ids": self.required_candidate_ids,
            "scanned_trades": self.scanned_trades,
            "created_records": self.created_records,
            "existing_records": self.existing_records,
            "created_feature_snapshots": self.created_feature_snapshots,
            "existing_feature_snapshots": self.existing_feature_snapshots,
            "before_learning_record_count": self.before_learning_record_count,
            "before_learning_state_digest": self.before_learning_state_digest,
            "before_feature_snapshot_count": self.before_feature_snapshot_count,
            "before_feature_state_digest": self.before_feature_state_digest,
            "after_learning_record_count": self.after_learning_record_count,
            "after_learning_state_digest": self.after_learning_state_digest,
            "after_feature_snapshot_count": self.after_feature_snapshot_count,
            "after_feature_state_digest": self.after_feature_state_digest,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def entry_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "entry_id": self.entry_id}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> LearningStateLineageEntry:
        expected_keys = {
            "sequence",
            "previous_entry_id",
            "upstream_run_id",
            "upstream_run_attempt",
            "upstream_head_sha",
            "upstream_artifact_id",
            "upstream_artifact_digest",
            "required_candidate_ids",
            "scanned_trades",
            "created_records",
            "existing_records",
            "created_feature_snapshots",
            "existing_feature_snapshots",
            "before_learning_record_count",
            "before_learning_state_digest",
            "before_feature_snapshot_count",
            "before_feature_state_digest",
            "after_learning_record_count",
            "after_learning_state_digest",
            "after_feature_snapshot_count",
            "after_feature_state_digest",
            "research_only",
            "promotion_eligible",
            "execution_ready",
            "schema_version",
            "entry_id",
        }
        if set(raw) != expected_keys:
            raise LearningStateLineageError("LINEAGE_ENTRY_FIELDS_INVALID")
        candidate_ids = raw["required_candidate_ids"]
        if not isinstance(candidate_ids, list) or not all(
            isinstance(item, str) for item in candidate_ids
        ):
            raise LearningStateLineageError("LINEAGE_CANDIDATE_IDS_INVALID")
        previous_entry_id = raw["previous_entry_id"]
        if previous_entry_id is not None and not isinstance(previous_entry_id, str):
            raise LearningStateLineageError("LINEAGE_PREVIOUS_ENTRY_ID_INVALID")
        try:
            entry = cls(
                sequence=cast(int, raw["sequence"]),
                previous_entry_id=previous_entry_id,
                upstream_run_id=cast(int, raw["upstream_run_id"]),
                upstream_run_attempt=cast(int, raw["upstream_run_attempt"]),
                upstream_head_sha=cast(str, raw["upstream_head_sha"]),
                upstream_artifact_id=cast(int, raw["upstream_artifact_id"]),
                upstream_artifact_digest=cast(str, raw["upstream_artifact_digest"]),
                required_candidate_ids=tuple(candidate_ids),
                scanned_trades=cast(int, raw["scanned_trades"]),
                created_records=cast(int, raw["created_records"]),
                existing_records=cast(int, raw["existing_records"]),
                created_feature_snapshots=cast(int, raw["created_feature_snapshots"]),
                existing_feature_snapshots=cast(int, raw["existing_feature_snapshots"]),
                before_learning_record_count=cast(
                    int, raw["before_learning_record_count"]
                ),
                before_learning_state_digest=cast(
                    str, raw["before_learning_state_digest"]
                ),
                before_feature_snapshot_count=cast(
                    int, raw["before_feature_snapshot_count"]
                ),
                before_feature_state_digest=cast(
                    str, raw["before_feature_state_digest"]
                ),
                after_learning_record_count=cast(int, raw["after_learning_record_count"]),
                after_learning_state_digest=cast(
                    str, raw["after_learning_state_digest"]
                ),
                after_feature_snapshot_count=cast(
                    int, raw["after_feature_snapshot_count"]
                ),
                after_feature_state_digest=cast(str, raw["after_feature_state_digest"]),
                research_only=cast(bool, raw["research_only"]),
                promotion_eligible=cast(bool, raw["promotion_eligible"]),
                execution_ready=cast(bool, raw["execution_ready"]),
                schema_version=cast(int, raw["schema_version"]),
            )
        except (TypeError, ValueError) as exc:
            raise LearningStateLineageError("LINEAGE_ENTRY_INVALID") from exc
        entry_id = raw["entry_id"]
        if not isinstance(entry_id, str) or entry_id != entry.entry_id:
            raise LearningStateLineageError("LINEAGE_ENTRY_ID_MISMATCH")
        return entry


def _entries_root(state_root: str | Path) -> Path:
    return Path(state_root) / "lineage" / "entries"


def _load_entries(state_root: str | Path) -> tuple[LearningStateLineageEntry, ...]:
    entries_root = _entries_root(state_root)
    if not entries_root.exists():
        return ()
    if not entries_root.is_dir():
        raise LearningStateLineageError("LINEAGE_ROOT_INVALID")

    entries: list[LearningStateLineageEntry] = []
    for path in sorted(entries_root.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LearningStateLineageError("LINEAGE_ENTRY_UNREADABLE") from exc
        if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
            raise LearningStateLineageError("LINEAGE_ENTRY_INVALID")
        entry = LearningStateLineageEntry.from_dict(cast(dict[str, object], raw))
        expected_name = f"{entry.sequence:08d}-{entry.entry_id}.json"
        if path.name != expected_name:
            raise LearningStateLineageError("LINEAGE_ENTRY_FILENAME_MISMATCH")
        entries.append(entry)
    return tuple(entries)


def verify_learning_state_lineage(
    state_root: str | Path,
    *,
    learning_record_count: int,
    learning_state_digest: str,
    feature_snapshot_count: int,
    feature_state_digest: str,
    require_entry: bool = False,
) -> LearningStateLineageEntry | None:
    for field, count_value in (
        ("learning_record_count", learning_record_count),
        ("feature_snapshot_count", feature_snapshot_count),
    ):
        _require_non_negative(count_value, field)
    for field, digest_value in (
        ("learning_state_digest", learning_state_digest),
        ("feature_state_digest", feature_state_digest),
    ):
        if not _is_sha256(digest_value):
            raise ValueError(f"{field} must be a lowercase sha256 hex digest")

    entries = _load_entries(state_root)
    if not entries:
        if require_entry or learning_record_count != 0 or feature_snapshot_count != 0:
            raise LearningStateLineageError("LINEAGE_MISSING")
        return None

    previous: LearningStateLineageEntry | None = None
    for expected_sequence, entry in enumerate(entries, start=1):
        if entry.sequence != expected_sequence:
            raise LearningStateLineageError("LINEAGE_SEQUENCE_INVALID")
        if previous is None:
            if entry.previous_entry_id is not None:
                raise LearningStateLineageError("LINEAGE_GENESIS_PARENT_INVALID")
        else:
            if entry.previous_entry_id != previous.entry_id:
                raise LearningStateLineageError("LINEAGE_PARENT_MISMATCH")
            if (
                entry.before_learning_record_count
                != previous.after_learning_record_count
                or entry.before_learning_state_digest
                != previous.after_learning_state_digest
                or entry.before_feature_snapshot_count
                != previous.after_feature_snapshot_count
                or entry.before_feature_state_digest
                != previous.after_feature_state_digest
            ):
                raise LearningStateLineageError("LINEAGE_STATE_TRANSITION_MISMATCH")
            if (
                entry.upstream_run_id,
                entry.upstream_run_attempt,
            ) < (
                previous.upstream_run_id,
                previous.upstream_run_attempt,
            ):
                raise LearningStateLineageError("LINEAGE_UPSTREAM_ORDER_INVALID")
        previous = entry

    tail = entries[-1]
    if (
        tail.after_learning_record_count != learning_record_count
        or tail.after_learning_state_digest != learning_state_digest
        or tail.after_feature_snapshot_count != feature_snapshot_count
        or tail.after_feature_state_digest != feature_state_digest
    ):
        raise LearningStateLineageError("LINEAGE_TAIL_STATE_MISMATCH")
    return tail


def append_learning_state_lineage(
    state_root: str | Path,
    *,
    upstream_run_id: int,
    upstream_run_attempt: int,
    upstream_head_sha: str,
    upstream_artifact_id: int,
    upstream_artifact_digest: str,
    required_candidate_ids: tuple[str, ...],
    scanned_trades: int,
    created_records: int,
    existing_records: int,
    created_feature_snapshots: int,
    existing_feature_snapshots: int,
    before_learning_record_count: int,
    before_learning_state_digest: str,
    before_feature_snapshot_count: int,
    before_feature_state_digest: str,
    after_learning_record_count: int,
    after_learning_state_digest: str,
    after_feature_snapshot_count: int,
    after_feature_state_digest: str,
) -> LearningStateLineageEntry:
    previous = verify_learning_state_lineage(
        state_root,
        learning_record_count=before_learning_record_count,
        learning_state_digest=before_learning_state_digest,
        feature_snapshot_count=before_feature_snapshot_count,
        feature_state_digest=before_feature_state_digest,
    )
    entry = LearningStateLineageEntry(
        sequence=1 if previous is None else previous.sequence + 1,
        previous_entry_id=None if previous is None else previous.entry_id,
        upstream_run_id=upstream_run_id,
        upstream_run_attempt=upstream_run_attempt,
        upstream_head_sha=upstream_head_sha,
        upstream_artifact_id=upstream_artifact_id,
        upstream_artifact_digest=upstream_artifact_digest,
        required_candidate_ids=required_candidate_ids,
        scanned_trades=scanned_trades,
        created_records=created_records,
        existing_records=existing_records,
        created_feature_snapshots=created_feature_snapshots,
        existing_feature_snapshots=existing_feature_snapshots,
        before_learning_record_count=before_learning_record_count,
        before_learning_state_digest=before_learning_state_digest,
        before_feature_snapshot_count=before_feature_snapshot_count,
        before_feature_state_digest=before_feature_state_digest,
        after_learning_record_count=after_learning_record_count,
        after_learning_state_digest=after_learning_state_digest,
        after_feature_snapshot_count=after_feature_snapshot_count,
        after_feature_state_digest=after_feature_state_digest,
    )
    if previous is not None and (
        entry.upstream_run_id,
        entry.upstream_run_attempt,
    ) < (
        previous.upstream_run_id,
        previous.upstream_run_attempt,
    ):
        raise LearningStateLineageError("LINEAGE_UPSTREAM_ORDER_INVALID")

    entries_root = _entries_root(state_root)
    entries_root.mkdir(parents=True, exist_ok=True)
    path = entries_root / f"{entry.sequence:08d}-{entry.entry_id}.json"
    if path.exists():
        raise LearningStateLineageError("LINEAGE_ENTRY_ALREADY_EXISTS")
    temp = path.with_suffix(".tmp")
    temp.write_text(
        _canonical_json(entry.to_dict()) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)

    verify_learning_state_lineage(
        state_root,
        learning_record_count=after_learning_record_count,
        learning_state_digest=after_learning_state_digest,
        feature_snapshot_count=after_feature_snapshot_count,
        feature_state_digest=after_feature_state_digest,
        require_entry=True,
    )
    return entry
