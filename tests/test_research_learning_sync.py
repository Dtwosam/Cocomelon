from __future__ import annotations

import json
import shutil
from types import SimpleNamespace

import pytest

from cocomelon.journal.store import JournalStore
from cocomelon.research import research_learning_sync
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import LearningEvidenceLedger
from tests.test_execution_learning_sync import _snapshot, _trade


def _write_json(path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _campaign(tmp_path):
    campaign = tmp_path / "campaign"
    output = campaign / "audit" / "evaluated" / "root-key" / "output"
    output.mkdir(parents=True)

    snapshot = _snapshot()
    journal = JournalStore(output / "journal.sqlite3")
    try:
        trade = _trade(snapshot, run_id="run-1")
        journal.record_trade(trade)
    finally:
        journal.close()

    source_features = LearningFeatureSnapshotStore(output / "learning-features")
    source_features.record(snapshot)
    _write_json(
        output / "replay.json",
        {
            "run_id": "run-1",
            "feature_snapshot_count": 1,
            "feature_snapshot_state_digest": source_features.state_digest,
        },
    )
    _write_json(
        output / "runner.json",
        {
            "status": "succeeded",
            "label": "TOUCHED / NON-PROMOTIONAL",
            "end_ms": 30_000,
        },
    )
    _write_json(
        campaign / "state" / "research-fanout.json",
        {
            "schema_version": 1,
            "candidates": [
                {
                    "artifact_key": "root-key",
                    "batch_id": "batch-1",
                    "candidate_id": "scheduled-research-root",
                    "required": True,
                    "source_id": "source-1",
                },
                {
                    "artifact_key": "ignored-key",
                    "batch_id": "batch-ignored",
                    "candidate_id": "optional-challenger",
                    "required": False,
                    "source_id": "source-ignored",
                },
            ],
        },
    )
    return campaign, snapshot, trade


def _verified(trade):
    return SimpleNamespace(
        replay_run_id="run-1",
        trade_ids=(trade.trade_id,),
    )


def test_research_learning_sync_ingests_required_candidate_and_copies_features(
    tmp_path,
    monkeypatch,
) -> None:
    campaign, snapshot, trade = _campaign(tmp_path)
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: _verified(trade),
    )

    receipt = research_learning_sync.sync_research_campaign_learning(
        campaign,
        state_root=tmp_path / "state",
        upstream_run_id=123,
        upstream_run_attempt=1,
        upstream_head_sha="a" * 40,
        upstream_artifact_id=456,
        upstream_artifact_digest="sha256:" + "b" * 64,
    )

    assert receipt.required_candidate_ids == ("scheduled-research-root",)
    assert receipt.scanned_trades == 1
    assert receipt.created_records == 1
    assert receipt.existing_records == 0
    assert receipt.created_feature_snapshots == 1
    assert receipt.existing_feature_snapshots == 0
    assert receipt.research_only is True
    assert receipt.promotion_eligible is False
    assert receipt.execution_ready is False

    ledger = LearningEvidenceLedger(tmp_path / "state" / "ledger")
    records = ledger.iter_records()
    assert len(records) == 1
    assert records[0].source_record_id == trade.trade_id

    features = LearningFeatureSnapshotStore(tmp_path / "state" / "features")
    assert features.load(snapshot.snapshot_id) is not None


def test_research_learning_sync_is_idempotent_for_same_campaign(
    tmp_path,
    monkeypatch,
) -> None:
    campaign, _snapshot_value, trade = _campaign(tmp_path)
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: _verified(trade),
    )
    kwargs = {
        "state_root": tmp_path / "state",
        "upstream_run_id": 123,
        "upstream_run_attempt": 1,
        "upstream_head_sha": "a" * 40,
        "upstream_artifact_id": 456,
        "upstream_artifact_digest": "sha256:" + "b" * 64,
    }

    first = research_learning_sync.sync_research_campaign_learning(campaign, **kwargs)
    second = research_learning_sync.sync_research_campaign_learning(campaign, **kwargs)

    assert first.created_records == 1
    assert first.created_feature_snapshots == 1
    assert second.created_records == 0
    assert second.existing_records == 1
    assert second.created_feature_snapshots == 0
    assert second.existing_feature_snapshots == 1
    assert first.learning_state_digest == second.learning_state_digest
    assert first.feature_state_digest == second.feature_state_digest


def test_research_learning_sync_rejects_pre_feature-store_campaign(
    tmp_path,
    monkeypatch,
) -> None:
    campaign, _snapshot_value, trade = _campaign(tmp_path)
    output = campaign / "audit" / "evaluated" / "root-key" / "output"
    shutil.rmtree(output / "learning-features")
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: _verified(trade),
    )

    with pytest.raises(
        research_learning_sync.ResearchLearningSyncError,
        match="FEATURE_STORE_MISSING",
    ):
        research_learning_sync.sync_research_campaign_learning(
            campaign,
            state_root=tmp_path / "state",
            upstream_run_id=123,
            upstream_run_attempt=1,
            upstream_head_sha="a" * 40,
            upstream_artifact_id=456,
            upstream_artifact_digest="sha256:" + "b" * 64,
        )


def test_research_learning_sync_rejects_feature_store_digest_mismatch(
    tmp_path,
    monkeypatch,
) -> None:
    campaign, _snapshot_value, trade = _campaign(tmp_path)
    replay = campaign / "audit" / "evaluated" / "root-key" / "output" / "replay.json"
    payload = json.loads(replay.read_text(encoding="utf-8"))
    payload["feature_snapshot_state_digest"] = "c" * 64
    _write_json(replay, payload)
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: _verified(trade),
    )

    with pytest.raises(
        research_learning_sync.ResearchLearningSyncError,
        match="FEATURE_STORE_DIGEST_MISMATCH",
    ):
        research_learning_sync.sync_research_campaign_learning(
            campaign,
            state_root=tmp_path / "state",
            upstream_run_id=123,
            upstream_run_attempt=1,
            upstream_head_sha="a" * 40,
            upstream_artifact_id=456,
            upstream_artifact_digest="sha256:" + "b" * 64,
        )
