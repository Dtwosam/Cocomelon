from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cocomelon.continuous_paper import RUN_ID
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning_sync import (
    CONTINUOUS_PAPER_LEARNING_CANDIDATE_ID,
    ContinuousPaperLearningSyncError,
    sync_continuous_paper_learning,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import LearningEvidenceLedger
from tests.test_execution_learning_sync import _snapshot, _trade


def _write_summary(
    root: Path,
    *,
    feature_store: LearningFeatureSnapshotStore,
    activation_ms: int | None,
    closed_trades: int,
) -> None:
    payload: dict[str, object] = {
        "started_at_ms": 5_000,
        "ended_at_ms": 40_000,
        "exit_reason": "duration_elapsed",
        "selected_markets": ["HYPE"],
        "processed_records": 100,
        "journal_observations": 20,
        "closed_trades": closed_trades,
        "session_closed_trades": 1,
        "feature_snapshot_count": len(feature_store.iter_verified()),
        "feature_snapshot_state_digest": feature_store.state_digest,
        "open_positions": 0,
        "equity": "10000",
        "execution_healthy": True,
        "execution_reason_codes": [],
        "network_access": True,
        "live_orders": False,
    }
    if activation_ms is not None:
        payload["learning_feature_capture_started_at_ms"] = activation_ms
    (root / "session-summary.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _worker(
    tmp_path: Path,
    *,
    include_post_feature: bool = True,
    activation_ms: int | None = 15_000,
) -> tuple[Path, str]:
    root = tmp_path / "worker"
    root.mkdir()
    features = LearningFeatureSnapshotStore(root / "learning-features")

    pre_snapshot = _snapshot(as_of_ms=9_000)
    post_snapshot = _snapshot(as_of_ms=19_000)
    if include_post_feature:
        features.record(post_snapshot)

    pre_trade = _trade(pre_snapshot, run_id=RUN_ID)
    post_trade = replace(
        _trade(post_snapshot, run_id=RUN_ID),
        opened_at_ms=20_000,
        closed_at_ms=30_000,
        strategy_decision_id="strategy-post",
        risk_decision_id="risk-post",
        opening_plan_id="plan-open-post",
        opening_attempt_id="attempt-open-post",
        exit_plan_ids=("plan-close-post",),
        exit_attempt_ids=("attempt-close-post",),
        fill_ids=("fill-open-post", "fill-close-post"),
        position_action_ids=("action-close-post",),
        holding_duration_ms=10_000,
    )

    journal = JournalStore(root / "journal.sqlite3")
    try:
        journal.record_trade(pre_trade)
        journal.record_trade(post_trade)
    finally:
        journal.close()

    _write_summary(
        root,
        feature_store=features,
        activation_ms=activation_ms,
        closed_trades=2,
    )
    return root, post_trade.trade_id


def _sync(worker: Path, state: Path):
    return sync_continuous_paper_learning(
        worker,
        state_root=state,
        upstream_run_id=123,
        upstream_run_attempt=1,
        upstream_head_sha="a" * 40,
        upstream_artifact_id=456,
        upstream_artifact_digest="sha256:" + "b" * 64,
    )


def test_continuous_paper_learning_skips_only_pre_activation_trades(
    tmp_path: Path,
) -> None:
    worker, post_trade_id = _worker(tmp_path)
    state = tmp_path / "state"

    first = _sync(worker, state)
    second = _sync(worker, state)

    assert first.scanned_trades == 2
    assert first.skipped_pre_activation_trades == 1
    assert first.created_records == 1
    assert first.existing_records == 0
    assert first.created_feature_snapshots == 1
    assert second.created_records == 0
    assert second.existing_records == 1
    assert second.lineage_sequence == 2

    records = LearningEvidenceLedger(state / "ledger").iter_records()
    assert len(records) == 1
    assert records[0].source_record_id == post_trade_id
    assert records[0].candidate_id == CONTINUOUS_PAPER_LEARNING_CANDIDATE_ID
    assert records[0].research_eligible_at_ms == records[0].closed_at_ms

    features = LearningFeatureSnapshotStore(state / "features")
    assert len(features.iter_verified()) == 1


def test_continuous_paper_learning_rejects_missing_post_activation_feature(
    tmp_path: Path,
) -> None:
    worker, _post_trade_id = _worker(tmp_path, include_post_feature=False)

    with pytest.raises(
        ValueError,
        match="missing authenticated feature snapshot",
    ):
        _sync(worker, tmp_path / "state")


def test_continuous_paper_learning_rejects_legacy_summary_without_activation(
    tmp_path: Path,
) -> None:
    worker, _post_trade_id = _worker(tmp_path, activation_ms=None)

    with pytest.raises(
        ContinuousPaperLearningSyncError,
        match="LEARNING_FEATURE_CAPTURE_STARTED_AT_MS_INVALID",
    ):
        _sync(worker, tmp_path / "state")


def test_continuous_paper_learning_rejects_feature_digest_mismatch(
    tmp_path: Path,
) -> None:
    worker, _post_trade_id = _worker(tmp_path)
    summary_path = worker / "session-summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["feature_snapshot_state_digest"] = "c" * 64
    summary_path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ContinuousPaperLearningSyncError,
        match="FEATURE_STORE_DIGEST_MISMATCH",
    ):
        _sync(worker, tmp_path / "state")
