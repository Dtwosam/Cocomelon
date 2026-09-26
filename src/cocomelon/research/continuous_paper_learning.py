from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cocomelon.journal.store import JournalStore
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    execution_learning_record,
)

CONTINUOUS_PAPER_LINEAGE_SCHEMA_VERSION = 1
CONTINUOUS_PAPER_CANDIDATE_ID = "continuous-paper-ensemble-v1"
CONTINUOUS_PAPER_REPLAY_RUN_ID = "continuous-paper-mainnet-v1"


class ContinuousPaperLearningError(RuntimeError):
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


def _is_commit_sha(value: str) -> bool:
    return (
        len(value) == 40
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


@dataclass(frozen=True, slots=True)
class ContinuousPaperRuntimeIdentity:
    worker_run_id: int
    worker_run_attempt: int
    worker_head_sha: str

    def __post_init__(self) -> None:
        if self.worker_run_id <= 0:
            raise ValueError("worker_run_id must be positive")
        if self.worker_run_attempt <= 0:
            raise ValueError("worker_run_attempt must be positive")
        if not _is_commit_sha(self.worker_head_sha):
            raise ValueError(
                "worker_head_sha must be a lowercase 40-character git SHA"
            )

    @property
    def campaign_id(self) -> str:
        return (
            f"continuous-paper-worker-"
            f"{self.worker_run_id}-{self.worker_run_attempt}"
        )


@dataclass(frozen=True, slots=True)
class ContinuousPaperOpeningLineage:
    opening_plan_id: str
    feature_snapshot_id: str
    market: str
    opened_at_ms: int
    runtime: ContinuousPaperRuntimeIdentity
    candidate_id: str = CONTINUOUS_PAPER_CANDIDATE_ID
    replay_run_id: str = CONTINUOUS_PAPER_REPLAY_RUN_ID
    schema_version: int = CONTINUOUS_PAPER_LINEAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "opening_plan_id",
            "feature_snapshot_id",
            "market",
            "candidate_id",
            "replay_run_id",
        ):
            _require_nonempty(str(getattr(self, field)), field)
        if self.opened_at_ms < 0:
            raise ValueError("opened_at_ms must be non-negative")
        if self.schema_version != CONTINUOUS_PAPER_LINEAGE_SCHEMA_VERSION:
            raise ValueError("unsupported continuous paper lineage schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "opening_plan_id": self.opening_plan_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "market": self.market,
            "opened_at_ms": self.opened_at_ms,
            "worker_run_id": self.runtime.worker_run_id,
            "worker_run_attempt": self.runtime.worker_run_attempt,
            "worker_head_sha": self.runtime.worker_head_sha,
            "candidate_id": self.candidate_id,
            "replay_run_id": self.replay_run_id,
            "schema_version": self.schema_version,
        }

    @property
    def lineage_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "lineage_id": self.lineage_id}

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, object],
    ) -> ContinuousPaperOpeningLineage:
        expected = {
            "opening_plan_id",
            "feature_snapshot_id",
            "market",
            "opened_at_ms",
            "worker_run_id",
            "worker_run_attempt",
            "worker_head_sha",
            "candidate_id",
            "replay_run_id",
            "schema_version",
            "lineage_id",
        }
        if set(raw) != expected:
            raise ContinuousPaperLearningError(
                "CONTINUOUS_PAPER_LINEAGE_FIELDS_INVALID"
            )
        try:
            lineage = cls(
                opening_plan_id=str(raw["opening_plan_id"]),
                feature_snapshot_id=str(raw["feature_snapshot_id"]),
                market=str(raw["market"]),
                opened_at_ms=int(raw["opened_at_ms"]),
                runtime=ContinuousPaperRuntimeIdentity(
                    worker_run_id=int(raw["worker_run_id"]),
                    worker_run_attempt=int(raw["worker_run_attempt"]),
                    worker_head_sha=str(raw["worker_head_sha"]),
                ),
                candidate_id=str(raw["candidate_id"]),
                replay_run_id=str(raw["replay_run_id"]),
                schema_version=int(raw["schema_version"]),
            )
        except (TypeError, ValueError) as exc:
            raise ContinuousPaperLearningError(
                "CONTINUOUS_PAPER_LINEAGE_INVALID"
            ) from exc
        if raw["lineage_id"] != lineage.lineage_id:
            raise ContinuousPaperLearningError(
                "CONTINUOUS_PAPER_LINEAGE_ID_MISMATCH"
            )
        return lineage


class ContinuousPaperOpeningLineageStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _record_name(opening_plan_id: str) -> str:
        _require_nonempty(opening_plan_id, "opening_plan_id")
        return hashlib.sha256(opening_plan_id.encode("utf-8")).hexdigest() + ".json"

    def _path(self, opening_plan_id: str) -> Path:
        return self.records_root / self._record_name(opening_plan_id)

    def record(self, lineage: ContinuousPaperOpeningLineage) -> bool:
        path = self._path(lineage.opening_plan_id)
        encoded = (_canonical_json(lineage.to_dict()) + "\n").encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise ContinuousPaperLearningError(
                    "CONTINUOUS_PAPER_LINEAGE_CONFLICT"
                )
            return False
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise ContinuousPaperLearningError(
                        "CONTINUOUS_PAPER_LINEAGE_CONFLICT"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def load(
        self,
        opening_plan_id: str,
    ) -> ContinuousPaperOpeningLineage | None:
        path = self._path(opening_plan_id)
        if not path.exists():
            return None
        try:
            encoded = path.read_bytes()
            raw = json.loads(encoded)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuousPaperLearningError(
                "CONTINUOUS_PAPER_LINEAGE_UNREADABLE"
            ) from exc
        if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
            raise ContinuousPaperLearningError(
                "CONTINUOUS_PAPER_LINEAGE_RECORD_INVALID"
            )
        lineage = ContinuousPaperOpeningLineage.from_dict(raw)
        if lineage.opening_plan_id != opening_plan_id:
            raise ContinuousPaperLearningError(
                "CONTINUOUS_PAPER_LINEAGE_PLAN_MISMATCH"
            )
        canonical = (_canonical_json(lineage.to_dict()) + "\n").encode("utf-8")
        if encoded != canonical:
            raise ContinuousPaperLearningError(
                "CONTINUOUS_PAPER_LINEAGE_NON_CANONICAL"
            )
        return lineage

    def iter_records(self) -> tuple[ContinuousPaperOpeningLineage, ...]:
        records: list[ContinuousPaperOpeningLineage] = []
        for path in sorted(self.records_root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContinuousPaperLearningError(
                    "CONTINUOUS_PAPER_LINEAGE_UNREADABLE"
                ) from exc
            if not isinstance(raw, dict) or not all(
                isinstance(key, str) for key in raw
            ):
                raise ContinuousPaperLearningError(
                    "CONTINUOUS_PAPER_LINEAGE_RECORD_INVALID"
                )
            lineage = ContinuousPaperOpeningLineage.from_dict(raw)
            if path.name != self._record_name(lineage.opening_plan_id):
                raise ContinuousPaperLearningError(
                    "CONTINUOUS_PAPER_LINEAGE_FILENAME_MISMATCH"
                )
            records.append(lineage)
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.opened_at_ms,
                    item.market,
                    item.opening_plan_id,
                ),
            )
        )

    @property
    def record_count(self) -> int:
        return len(self.iter_records())

    @property
    def state_digest(self) -> str:
        return _sha256_json(
            tuple(record.to_dict() for record in self.iter_records())
        )


@dataclass(frozen=True, slots=True)
class ContinuousPaperLearningSyncResult:
    scanned_trades: int
    attributed_trades: int
    skipped_unattributed_trades: int
    created_records: int
    existing_records: int
    created_feature_snapshots: int
    existing_feature_snapshots: int

    def __post_init__(self) -> None:
        values = (
            self.scanned_trades,
            self.attributed_trades,
            self.skipped_unattributed_trades,
            self.created_records,
            self.existing_records,
            self.created_feature_snapshots,
            self.existing_feature_snapshots,
        )
        if min(values) < 0:
            raise ValueError("continuous paper learning sync counts must be non-negative")
        if (
            self.attributed_trades + self.skipped_unattributed_trades
            != self.scanned_trades
        ):
            raise ValueError("continuous paper attribution counts must reconcile")
        if self.created_records + self.existing_records != self.attributed_trades:
            raise ValueError("continuous paper learning record counts must reconcile")
        if (
            self.created_feature_snapshots + self.existing_feature_snapshots
            != self.attributed_trades
        ):
            raise ValueError("continuous paper feature counts must reconcile")


def sync_continuous_paper_learning_evidence(
    journal: JournalStore,
    source_feature_store: LearningFeatureSnapshotStore,
    lineage_store: ContinuousPaperOpeningLineageStore,
    ledger: LearningEvidenceLedger,
    *,
    destination_feature_store: LearningFeatureSnapshotStore | None = None,
) -> ContinuousPaperLearningSyncResult:
    created = 0
    existing = 0
    created_features = 0
    existing_features = 0
    attributed = 0
    skipped = 0
    trades = tuple(journal.iter_trades())

    for trade in trades:
        lineage = lineage_store.load(trade.opening_plan_id)
        if lineage is None:
            skipped += 1
            continue
        attributed += 1
        if trade.replay_run_id != lineage.replay_run_id:
            raise ValueError(
                f"trade replay_run_id does not match opening lineage: {trade.trade_id}"
            )
        if trade.market.canonical != lineage.market:
            raise ValueError(
                f"trade market does not match opening lineage: {trade.trade_id}"
            )
        if trade.feature_snapshot_id != lineage.feature_snapshot_id:
            raise ValueError(
                f"trade feature snapshot does not match opening lineage: {trade.trade_id}"
            )
        if trade.opened_at_ms != lineage.opened_at_ms:
            raise ValueError(
                f"trade opened_at_ms does not match opening lineage: {trade.trade_id}"
            )

        verified = source_feature_store.load(trade.feature_snapshot_id)
        if verified is None:
            raise ValueError(
                f"missing authenticated feature snapshot for trade {trade.trade_id}"
            )
        snapshot = verified.snapshot
        if snapshot.market != trade.market:
            raise ValueError(
                f"feature snapshot market does not match trade {trade.trade_id}"
            )
        if snapshot.as_of_ms > trade.opened_at_ms:
            raise ValueError(
                f"feature snapshot is after trade open for trade {trade.trade_id}"
            )
        if snapshot.source_received_at_ms > trade.opened_at_ms:
            raise ValueError(
                f"feature snapshot source is after trade open for trade {trade.trade_id}"
            )

        if destination_feature_store is not None:
            if destination_feature_store.record(snapshot):
                created_features += 1
            else:
                existing_features += 1

        record = execution_learning_record(
            trade,
            candidate_id=lineage.candidate_id,
            kind=LearningEvidenceKind.PAPER_EXECUTION,
            research_eligible_at_ms=trade.closed_at_ms,
            candidate_spec_id=lineage.runtime.worker_head_sha,
            campaign_id=lineage.runtime.campaign_id,
        )
        if ledger.record(record):
            created += 1
        else:
            existing += 1

    return ContinuousPaperLearningSyncResult(
        scanned_trades=len(trades),
        attributed_trades=attributed,
        skipped_unattributed_trades=skipped,
        created_records=created,
        existing_records=existing,
        created_feature_snapshots=created_features,
        existing_feature_snapshots=existing_features,
    )
