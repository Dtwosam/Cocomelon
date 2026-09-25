from __future__ import annotations

from dataclasses import dataclass

from cocomelon.journal.store import JournalStore
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    execution_learning_record,
)


@dataclass(frozen=True, slots=True)
class ExecutionLearningSyncResult:
    scanned_trades: int
    created_records: int
    existing_records: int
    created_feature_snapshots: int
    existing_feature_snapshots: int

    def __post_init__(self) -> None:
        if min(
            self.scanned_trades,
            self.created_records,
            self.existing_records,
            self.created_feature_snapshots,
            self.existing_feature_snapshots,
        ) < 0:
            raise ValueError("execution learning sync counts must be non-negative")
        if self.created_records + self.existing_records != self.scanned_trades:
            raise ValueError("execution learning record counts must reconcile")
        feature_attempts = (
            self.created_feature_snapshots + self.existing_feature_snapshots
        )
        if feature_attempts not in {0, self.scanned_trades}:
            raise ValueError("execution learning feature counts must reconcile")


def sync_execution_learning_evidence(
    journal: JournalStore,
    feature_store: LearningFeatureSnapshotStore,
    ledger: LearningEvidenceLedger,
    *,
    candidate_id: str,
    kind: LearningEvidenceKind,
    research_eligible_at_ms: int,
    expected_replay_run_id: str | None = None,
    candidate_spec_id: str | None = None,
    campaign_id: str | None = None,
    destination_feature_store: LearningFeatureSnapshotStore | None = None,
) -> ExecutionLearningSyncResult:
    if not candidate_id.strip():
        raise ValueError("candidate_id must not be empty")
    if research_eligible_at_ms < 0:
        raise ValueError("research_eligible_at_ms must be non-negative")
    if expected_replay_run_id is not None and not expected_replay_run_id.strip():
        raise ValueError("expected_replay_run_id must not be empty when present")
    if kind not in {
        LearningEvidenceKind.PAPER_EXECUTION,
        LearningEvidenceKind.LIVE_EXECUTION,
    }:
        raise ValueError("execution learning sync requires paper or live execution kind")

    created = 0
    existing = 0
    created_features = 0
    existing_features = 0
    trades = tuple(journal.iter_trades())
    for trade in trades:
        if expected_replay_run_id is not None:
            if trade.replay_run_id != expected_replay_run_id:
                raise ValueError(
                    "journal trade replay_run_id does not match expected replay run"
                )
        if kind is LearningEvidenceKind.LIVE_EXECUTION and trade.replay_run_id is not None:
            raise ValueError("live execution sync cannot ingest replay-backed trade")

        verified = feature_store.load(trade.feature_snapshot_id)
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
            candidate_id=candidate_id,
            kind=kind,
            research_eligible_at_ms=research_eligible_at_ms,
            candidate_spec_id=candidate_spec_id,
            campaign_id=campaign_id,
        )
        if ledger.record(record):
            created += 1
        else:
            existing += 1

    return ExecutionLearningSyncResult(
        scanned_trades=len(trades),
        created_records=created,
        existing_records=existing,
        created_feature_snapshots=created_features,
        existing_feature_snapshots=existing_features,
    )
