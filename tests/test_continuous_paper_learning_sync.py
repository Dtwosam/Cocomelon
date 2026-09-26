from __future__ import annotations

import json

import pytest

from cocomelon.continuous_paper import (
    LEARNING_SOURCE_FILENAME,
    _learning_source_payload,
)
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning_sync import (
    ContinuousPaperLearningSyncError,
    sync_continuous_paper_learning,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_state_lineage import verify_learning_state_lineage
from cocomelon.research.outcome_learning import LearningEvidenceLedger


def _empty_paper_state(tmp_path, *, head_sha: str):
    paper = tmp_path / "paper"
    paper.mkdir()
    config = BaselineReplayConfig()
    source = _learning_source_payload(config, runtime_head_sha=head_sha)
    (paper / LEARNING_SOURCE_FILENAME).write_text(
        json.dumps(source, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    features = LearningFeatureSnapshotStore(paper / "learning-features")
    (paper / "session-summary.json").write_text(
        json.dumps(
            {
                "live_orders": False,
                "feature_snapshot_count": 0,
                "feature_snapshot_state_digest": features.state_digest,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    journal = JournalStore(paper / "journal.sqlite3")
    journal.close()
    return paper, config


def test_continuous_paper_learning_sync_accepts_authenticated_zero_trade_worker(
    tmp_path,
) -> None:
    head_sha = "a" * 40
    paper, config = _empty_paper_state(tmp_path, head_sha=head_sha)
    state = tmp_path / "learning-state"

    receipt = sync_continuous_paper_learning(
        paper,
        state_root=state,
        upstream_run_id=100,
        upstream_run_attempt=1,
        upstream_head_sha=head_sha,
        upstream_artifact_id=200,
        upstream_artifact_digest="sha256:" + "b" * 64,
    )

    assert receipt.required_candidate_ids == (
        "continuous-paper-" + config.config_digest[:24],
    )
    assert receipt.scanned_trades == 0
    assert receipt.created_records == 0
    assert receipt.created_feature_snapshots == 0
    assert receipt.research_only is True
    assert receipt.promotion_eligible is False
    assert receipt.execution_ready is False
    assert LearningEvidenceLedger(state / "ledger").iter_records() == ()
    tail = verify_learning_state_lineage(
        state,
        learning_record_count=0,
        learning_state_digest=receipt.learning_state_digest,
        feature_snapshot_count=0,
        feature_state_digest=receipt.feature_state_digest,
        require_entry=True,
    )
    assert tail is not None
    assert tail.entry_id == receipt.lineage_entry_id


def test_continuous_paper_learning_sync_rejects_worker_head_mismatch(tmp_path) -> None:
    paper, _config = _empty_paper_state(tmp_path, head_sha="a" * 40)
    with pytest.raises(
        ContinuousPaperLearningSyncError,
        match="CONTINUOUS_LEARNING_SOURCE_HEAD_MISMATCH",
    ):
        sync_continuous_paper_learning(
            paper,
            state_root=tmp_path / "learning-state",
            upstream_run_id=100,
            upstream_run_attempt=1,
            upstream_head_sha="c" * 40,
            upstream_artifact_id=200,
            upstream_artifact_digest="sha256:" + "b" * 64,
        )
