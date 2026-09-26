from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.journal.store import JournalStore
from cocomelon.research.execution_learning_sync import (
    sync_execution_learning_evidence,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
)


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


def _execution_kind(value: str) -> LearningEvidenceKind:
    try:
        kind = LearningEvidenceKind(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "kind must be paper_execution or live_execution"
        ) from exc
    if kind not in {
        LearningEvidenceKind.PAPER_EXECUTION,
        LearningEvidenceKind.LIVE_EXECUTION,
    }:
        raise argparse.ArgumentTypeError(
            "kind must be paper_execution or live_execution"
        )
    return kind


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-execution-learning-sync",
        description=(
            "Sync settled execution trades into the append-only learning ledger "
            "after authenticating their decision-time feature snapshots"
        ),
    )
    parser.add_argument("--journal", required=True, type=Path)
    parser.add_argument("--feature-store-dir", required=True, type=Path)
    parser.add_argument("--learning-root", required=True, type=Path)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--kind",
        required=True,
        type=_execution_kind,
    )
    eligibility = parser.add_mutually_exclusive_group(required=True)
    eligibility.add_argument(
        "--research-eligible-at-ms",
        type=int,
    )
    eligibility.add_argument(
        "--research-eligible-at-trade-close",
        action="store_true",
    )
    parser.add_argument("--expected-replay-run-id")
    parser.add_argument("--candidate-spec-id")
    parser.add_argument("--campaign-id")
    parser.add_argument("--destination-feature-store-dir", type=Path)
    return parser


def execution_learning_sync_payload(
    *,
    journal_path: Path,
    feature_store_dir: Path,
    learning_root: Path,
    candidate_id: str,
    kind: LearningEvidenceKind,
    research_eligible_at_ms: int | None,
    research_eligible_at_trade_close: bool = False,
    expected_replay_run_id: str | None = None,
    candidate_spec_id: str | None = None,
    campaign_id: str | None = None,
    destination_feature_store_dir: Path | None = None,
) -> dict[str, object]:
    journal = JournalStore(journal_path)
    try:
        feature_store = LearningFeatureSnapshotStore(feature_store_dir)
        ledger = LearningEvidenceLedger(learning_root)
        destination_feature_store = (
            None
            if destination_feature_store_dir is None
            else LearningFeatureSnapshotStore(destination_feature_store_dir)
        )
        result = sync_execution_learning_evidence(
            journal,
            feature_store,
            ledger,
            candidate_id=candidate_id,
            kind=kind,
            research_eligible_at_ms=research_eligible_at_ms,
            research_eligible_at_trade_close=research_eligible_at_trade_close,
            expected_replay_run_id=expected_replay_run_id,
            candidate_spec_id=candidate_spec_id,
            campaign_id=campaign_id,
            destination_feature_store=destination_feature_store,
        )
        records = ledger.iter_records()
        destination_snapshots = (
            ()
            if destination_feature_store is None
            else destination_feature_store.iter_verified()
        )
        return {
            "command": "execution-learning-sync",
            "candidate_id": candidate_id,
            "candidate_spec_id": candidate_spec_id,
            "campaign_id": campaign_id,
            "kind": kind.value,
            "research_eligible_at_ms": research_eligible_at_ms,
            "research_eligibility_mode": (
                "trade_close"
                if research_eligible_at_trade_close
                else "fixed_timestamp"
            ),
            "expected_replay_run_id": expected_replay_run_id,
            "scanned_trades": result.scanned_trades,
            "created_records": result.created_records,
            "existing_records": result.existing_records,
            "created_feature_snapshots": result.created_feature_snapshots,
            "existing_feature_snapshots": result.existing_feature_snapshots,
            "learning_record_count": len(records),
            "learning_state_digest": ledger.state_digest,
            "source_feature_state_digest": feature_store.state_digest,
            "feature_snapshot_count": len(destination_snapshots),
            "feature_state_digest": (
                None
                if destination_feature_store is None
                else destination_feature_store.state_digest
            ),
            "journal": str(journal_path),
            "feature_store_dir": str(feature_store_dir),
            "destination_feature_store_dir": (
                None
                if destination_feature_store_dir is None
                else str(destination_feature_store_dir)
            ),
            "learning_root": str(learning_root),
        }
    finally:
        journal.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = execution_learning_sync_payload(
            journal_path=args.journal,
            feature_store_dir=args.feature_store_dir,
            learning_root=args.learning_root,
            candidate_id=args.candidate_id,
            kind=args.kind,
            research_eligible_at_ms=args.research_eligible_at_ms,
            research_eligible_at_trade_close=args.research_eligible_at_trade_close,
            expected_replay_run_id=args.expected_replay_run_id,
            candidate_spec_id=args.candidate_spec_id,
            campaign_id=args.campaign_id,
            destination_feature_store_dir=args.destination_feature_store_dir,
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
