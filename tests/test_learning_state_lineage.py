from __future__ import annotations

import json

import pytest

from cocomelon.research.learning_state_lineage import (
    LearningStateLineageError,
    append_learning_state_lineage,
    verify_learning_state_lineage,
)


def _append(
    root,
    *,
    run_id: int,
    attempt: int,
    before_records: int,
    before_learning_digest: str,
    before_features: int,
    before_feature_digest: str,
    created_records: int = 1,
    existing_records: int = 0,
    created_features: int = 1,
    existing_features: int = 0,
    after_learning_digest: str = "c" * 64,
    after_feature_digest: str = "d" * 64,
    artifact_id: int | None = None,
):
    scanned = created_records + existing_records
    assert scanned == created_features + existing_features
    return append_learning_state_lineage(
        root,
        upstream_run_id=run_id,
        upstream_run_attempt=attempt,
        upstream_head_sha="a" * 40,
        upstream_artifact_id=456 + run_id if artifact_id is None else artifact_id,
        upstream_artifact_digest="sha256:" + "b" * 64,
        required_candidate_ids=("scheduled-research-root",),
        scanned_trades=scanned,
        created_records=created_records,
        existing_records=existing_records,
        created_feature_snapshots=created_features,
        existing_feature_snapshots=existing_features,
        before_learning_record_count=before_records,
        before_learning_state_digest=before_learning_digest,
        before_feature_snapshot_count=before_features,
        before_feature_state_digest=before_feature_digest,
        after_learning_record_count=before_records + created_records,
        after_learning_state_digest=after_learning_digest,
        after_feature_snapshot_count=before_features + created_features,
        after_feature_state_digest=after_feature_digest,
    )


def test_learning_state_lineage_chains_verified_transitions(tmp_path) -> None:
    first = _append(
        tmp_path,
        run_id=100,
        attempt=1,
        before_records=0,
        before_learning_digest="1" * 64,
        before_features=0,
        before_feature_digest="2" * 64,
    )
    second = _append(
        tmp_path,
        run_id=101,
        attempt=1,
        before_records=1,
        before_learning_digest=first.after_learning_state_digest,
        before_features=1,
        before_feature_digest=first.after_feature_state_digest,
        after_learning_digest="e" * 64,
        after_feature_digest="f" * 64,
    )

    assert first.sequence == 1
    assert first.previous_entry_id is None
    assert second.sequence == 2
    assert second.previous_entry_id == first.entry_id

    tail = verify_learning_state_lineage(
        tmp_path,
        learning_record_count=2,
        learning_state_digest=second.after_learning_state_digest,
        feature_snapshot_count=2,
        feature_state_digest=second.after_feature_state_digest,
        require_entry=True,
    )
    assert tail == second


def test_learning_state_lineage_accepts_noop_idempotent_transition(tmp_path) -> None:
    first = _append(
        tmp_path,
        run_id=100,
        attempt=1,
        before_records=0,
        before_learning_digest="1" * 64,
        before_features=0,
        before_feature_digest="2" * 64,
    )
    second = _append(
        tmp_path,
        run_id=100,
        attempt=1,
        before_records=1,
        before_learning_digest=first.after_learning_state_digest,
        before_features=1,
        before_feature_digest=first.after_feature_state_digest,
        created_records=0,
        existing_records=1,
        created_features=0,
        existing_features=1,
        after_learning_digest=first.after_learning_state_digest,
        after_feature_digest=first.after_feature_state_digest,
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert second.previous_entry_id == first.entry_id


def test_learning_state_lineage_rejects_changed_identity_for_same_upstream(
    tmp_path,
) -> None:
    first = _append(
        tmp_path,
        run_id=100,
        attempt=1,
        before_records=0,
        before_learning_digest="1" * 64,
        before_features=0,
        before_feature_digest="2" * 64,
    )

    with pytest.raises(
        LearningStateLineageError,
        match="LINEAGE_UPSTREAM_IDENTITY_CHANGED",
    ):
        _append(
            tmp_path,
            run_id=100,
            attempt=1,
            before_records=1,
            before_learning_digest=first.after_learning_state_digest,
            before_features=1,
            before_feature_digest=first.after_feature_state_digest,
            created_records=0,
            existing_records=1,
            created_features=0,
            existing_features=1,
            after_learning_digest=first.after_learning_state_digest,
            after_feature_digest=first.after_feature_state_digest,
            artifact_id=999,
        )

    assert len(list((tmp_path / "lineage" / "entries").glob("*.json"))) == 1


def test_learning_state_lineage_rejects_regressed_upstream_order(tmp_path) -> None:
    first = _append(
        tmp_path,
        run_id=101,
        attempt=1,
        before_records=0,
        before_learning_digest="1" * 64,
        before_features=0,
        before_feature_digest="2" * 64,
    )

    with pytest.raises(
        LearningStateLineageError,
        match="LINEAGE_UPSTREAM_ORDER_INVALID",
    ):
        _append(
            tmp_path,
            run_id=100,
            attempt=1,
            before_records=1,
            before_learning_digest=first.after_learning_state_digest,
            before_features=1,
            before_feature_digest=first.after_feature_state_digest,
            after_learning_digest="e" * 64,
            after_feature_digest="f" * 64,
        )


def test_learning_state_lineage_rejects_tampered_entry(tmp_path) -> None:
    entry = _append(
        tmp_path,
        run_id=100,
        attempt=1,
        before_records=0,
        before_learning_digest="1" * 64,
        before_features=0,
        before_feature_digest="2" * 64,
    )
    path = next((tmp_path / "lineage" / "entries").glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["after_learning_state_digest"] = "9" * 64
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(
        LearningStateLineageError,
        match="LINEAGE_ENTRY_ID_MISMATCH",
    ):
        verify_learning_state_lineage(
            tmp_path,
            learning_record_count=entry.after_learning_record_count,
            learning_state_digest=entry.after_learning_state_digest,
            feature_snapshot_count=entry.after_feature_snapshot_count,
            feature_state_digest=entry.after_feature_state_digest,
            require_entry=True,
        )


def test_learning_state_lineage_requires_history_for_nonempty_state(tmp_path) -> None:
    with pytest.raises(LearningStateLineageError, match="LINEAGE_MISSING"):
        verify_learning_state_lineage(
            tmp_path,
            learning_record_count=1,
            learning_state_digest="1" * 64,
            feature_snapshot_count=1,
            feature_state_digest="2" * 64,
        )
