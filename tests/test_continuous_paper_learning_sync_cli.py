from __future__ import annotations

import json

import pytest

from cocomelon.continuous_paper_learning_sync_cli import (
    continuous_paper_learning_sync_payload,
)
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    CONTINUOUS_PAPER_REPLAY_RUN_ID,
    ContinuousPaperOpeningLineage,
    ContinuousPaperOpeningLineageStore,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import LearningEvidenceLedger
from tests.test_execution_learning_sync import _snapshot, _trade


def _source_state(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    snapshot = _snapshot()
    trade = _trade(snapshot, run_id=CONTINUOUS_PAPER_REPLAY_RUN_ID)

    journal = JournalStore(root / "journal.sqlite3")
    try:
        journal.record_trade(trade)
    finally:
        journal.close()

    features = LearningFeatureSnapshotStore(root / "learning-features")
    features.record(snapshot)

    lineage = ContinuousPaperOpeningLineageStore(root / "opening-lineage")
    identity = ContinuousPaperRuntimeIdentity(
        worker_run_id=123,
        worker_run_attempt=1,
        worker_head_sha="a" * 40,
    )
    lineage.record(
        ContinuousPaperOpeningLineage(
            opening_plan_id=trade.opening_plan_id,
            feature_snapshot_id=trade.feature_snapshot_id,
            market=trade.market.canonical,
            opened_at_ms=trade.opened_at_ms,
            runtime=identity,
        )
    )

    (root / "session-summary.json").write_text(
        json.dumps(
            {
                "feature_snapshot_count": len(features.iter_verified()),
                "feature_snapshot_state_digest": features.state_digest,
                "opening_lineage_count": lineage.record_count,
                "opening_lineage_state_digest": lineage.state_digest,
                "live_orders": False,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root, trade


def test_continuous_paper_learning_sync_cli_is_idempotent(tmp_path) -> None:
    source, trade = _source_state(tmp_path)
    state = tmp_path / "learning-state"

    first = continuous_paper_learning_sync_payload(
        source_state_root=source,
        learning_state_root=state,
    )
    second = continuous_paper_learning_sync_payload(
        source_state_root=source,
        learning_state_root=state,
    )

    assert first["created_records"] == 1
    assert first["existing_records"] == 0
    assert first["skipped_unattributed_trades"] == 0
    assert second["created_records"] == 0
    assert second["existing_records"] == 1
    assert first["research_only"] is True
    assert first["promotion_eligible"] is False
    assert first["execution_ready"] is False

    records = LearningEvidenceLedger(state / "ledger").iter_records()
    assert len(records) == 1
    assert records[0].source_record_id == trade.trade_id


def test_continuous_paper_learning_sync_cli_rejects_summary_tampering(tmp_path) -> None:
    source, _trade_entry = _source_state(tmp_path)
    summary_path = source / "session-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["opening_lineage_state_digest"] = "0" * 64
    summary_path.write_text(
        json.dumps(summary, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="opening lineage digest mismatch"):
        continuous_paper_learning_sync_payload(
            source_state_root=source,
            learning_state_root=tmp_path / "learning-state",
        )
