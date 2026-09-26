from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.journal.store import JournalStore
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore


class ContinuousPaperLearningSourceError(RuntimeError):
    pass


def _mapping(path: Path, field: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContinuousPaperLearningSourceError(
            f"{field.upper()}_MISSING"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ContinuousPaperLearningSourceError(
            f"{field.upper()}_INVALID"
        ) from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ContinuousPaperLearningSourceError(f"{field.upper()}_INVALID")
    return cast(dict[str, object], raw)


def _integer(raw: dict[str, object], field: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContinuousPaperLearningSourceError(f"{field.upper()}_INVALID")
    return value


def _string(raw: dict[str, object], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContinuousPaperLearningSourceError(f"{field.upper()}_INVALID")
    return value


def _boolean(raw: dict[str, object], field: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ContinuousPaperLearningSourceError(f"{field.upper()}_INVALID")
    return value


def _require_state_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContinuousPaperLearningSourceError(f"{field.upper()}_INVALID")


@dataclass(frozen=True, slots=True)
class VerifiedContinuousPaperLearningSource:
    root: Path
    worker_started_at_ms: int
    worker_ended_at_ms: int
    feature_capture_started_at_ms: int
    closed_trade_count: int
    feature_snapshot_count: int
    feature_snapshot_state_digest: str

    @property
    def journal_path(self) -> Path:
        return self.root / "journal.sqlite3"

    @property
    def feature_store_root(self) -> Path:
        return self.root / "learning-features"


def verify_continuous_paper_learning_source(
    worker_root: str | Path,
) -> VerifiedContinuousPaperLearningSource:
    worker = Path(worker_root)
    summary = _mapping(worker / "session-summary.json", "session_summary")

    if _boolean(summary, "live_orders"):
        raise ContinuousPaperLearningSourceError("LIVE_ORDERS_FORBIDDEN")
    if not _boolean(summary, "network_access"):
        raise ContinuousPaperLearningSourceError("MAINNET_NETWORK_ACCESS_REQUIRED")

    started_at_ms = _integer(summary, "started_at_ms")
    ended_at_ms = _integer(summary, "ended_at_ms")
    activation_ms = _integer(
        summary,
        "learning_feature_capture_started_at_ms",
    )
    if ended_at_ms < started_at_ms:
        raise ContinuousPaperLearningSourceError("WORKER_TIME_RANGE_INVALID")
    if activation_ms > ended_at_ms:
        raise ContinuousPaperLearningSourceError(
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
        raise ContinuousPaperLearningSourceError("FEATURE_STORE_MISSING")
    source_features = LearningFeatureSnapshotStore(source_features_root)
    verified_source_features = source_features.iter_verified()
    if len(verified_source_features) != expected_feature_count:
        raise ContinuousPaperLearningSourceError("FEATURE_STORE_COUNT_MISMATCH")
    if source_features.state_digest != expected_feature_digest:
        raise ContinuousPaperLearningSourceError("FEATURE_STORE_DIGEST_MISMATCH")

    journal_path = worker / "journal.sqlite3"
    if not journal_path.is_file():
        raise ContinuousPaperLearningSourceError("JOURNAL_MISSING")
    journal = JournalStore(journal_path)
    try:
        source_trade_count = sum(1 for _ in journal.iter_trades())
    finally:
        journal.close()
    expected_trade_count = _integer(summary, "closed_trades")
    if source_trade_count != expected_trade_count:
        raise ContinuousPaperLearningSourceError("JOURNAL_TRADE_COUNT_MISMATCH")

    return VerifiedContinuousPaperLearningSource(
        root=worker,
        worker_started_at_ms=started_at_ms,
        worker_ended_at_ms=ended_at_ms,
        feature_capture_started_at_ms=activation_ms,
        closed_trade_count=expected_trade_count,
        feature_snapshot_count=expected_feature_count,
        feature_snapshot_state_digest=expected_feature_digest,
    )
