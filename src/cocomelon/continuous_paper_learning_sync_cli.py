from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineageStore,
    sync_continuous_paper_learning_evidence,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import LearningEvidenceLedger


def _emit(payload: dict[str, object], *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=target,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-continuous-paper-learning-sync",
        description=(
            "Sync attributed continuous-paper execution outcomes into a "
            "research-only learning state"
        ),
    )
    parser.add_argument("--source-state-root", required=True, type=Path)
    parser.add_argument("--learning-state-root", required=True, type=Path)
    return parser


def _summary_payload(source_state_root: Path) -> dict[str, object]:
    path = source_state_root / "session-summary.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError("continuous paper session summary must be an object")
    if raw.get("live_orders") is not False:
        raise ValueError("continuous paper source must have live_orders=false")
    return raw


def continuous_paper_learning_sync_payload(
    *,
    source_state_root: Path,
    learning_state_root: Path,
) -> dict[str, object]:
    summary = _summary_payload(source_state_root)
    source_features = LearningFeatureSnapshotStore(
        source_state_root / "learning-features"
    )
    lineage = ContinuousPaperOpeningLineageStore(
        source_state_root / "opening-lineage"
    )

    expected_feature_count = summary.get("feature_snapshot_count")
    expected_feature_digest = summary.get("feature_snapshot_state_digest")
    expected_lineage_count = summary.get("opening_lineage_count")
    expected_lineage_digest = summary.get("opening_lineage_state_digest")
    if (
        isinstance(expected_feature_count, bool)
        or not isinstance(expected_feature_count, int)
        or expected_feature_count < 0
    ):
        raise ValueError("continuous paper feature snapshot count is invalid")
    if not isinstance(expected_feature_digest, str):
        raise ValueError("continuous paper feature snapshot digest is invalid")
    if (
        isinstance(expected_lineage_count, bool)
        or not isinstance(expected_lineage_count, int)
        or expected_lineage_count < 0
    ):
        raise ValueError("continuous paper opening lineage count is invalid")
    if not isinstance(expected_lineage_digest, str):
        raise ValueError("continuous paper opening lineage digest is invalid")

    actual_features = source_features.iter_verified()
    if len(actual_features) != expected_feature_count:
        raise ValueError("continuous paper feature snapshot count mismatch")
    if source_features.state_digest != expected_feature_digest:
        raise ValueError("continuous paper feature snapshot digest mismatch")
    if lineage.record_count != expected_lineage_count:
        raise ValueError("continuous paper opening lineage count mismatch")
    if lineage.state_digest != expected_lineage_digest:
        raise ValueError("continuous paper opening lineage digest mismatch")

    journal = JournalStore(source_state_root / "journal.sqlite3")
    destination_features = LearningFeatureSnapshotStore(
        learning_state_root / "features"
    )
    ledger = LearningEvidenceLedger(learning_state_root / "ledger")
    try:
        result = sync_continuous_paper_learning_evidence(
            journal,
            source_features,
            lineage,
            ledger,
            destination_feature_store=destination_features,
        )
    finally:
        journal.close()

    records = ledger.iter_records()
    verified_features = destination_features.iter_verified()
    return {
        "command": "continuous-paper-learning-sync",
        "source_state_root": str(source_state_root),
        "learning_state_root": str(learning_state_root),
        "scanned_trades": result.scanned_trades,
        "attributed_trades": result.attributed_trades,
        "skipped_unattributed_trades": result.skipped_unattributed_trades,
        "created_records": result.created_records,
        "existing_records": result.existing_records,
        "created_feature_snapshots": result.created_feature_snapshots,
        "existing_feature_snapshots": result.existing_feature_snapshots,
        "learning_record_count": len(records),
        "learning_state_digest": ledger.state_digest,
        "feature_snapshot_count": len(verified_features),
        "feature_state_digest": destination_features.state_digest,
        "source_feature_snapshot_count": expected_feature_count,
        "source_feature_snapshot_state_digest": expected_feature_digest,
        "source_opening_lineage_count": expected_lineage_count,
        "source_opening_lineage_state_digest": expected_lineage_digest,
        "research_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = continuous_paper_learning_sync_payload(
            source_state_root=args.source_state_root,
            learning_state_root=args.learning_state_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
