from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_learning import (
    CONTINUOUS_PAPER_CANDIDATE_ID,
    CONTINUOUS_PAPER_REPLAY_RUN_ID,
    ContinuousPaperOpeningLineage,
    ContinuousPaperOpeningLineageStore,
    ContinuousPaperRuntimeIdentity,
    sync_continuous_paper_learning_evidence,
)
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import LearningEvidenceLedger
from tests.test_execution_learning_sync import _snapshot, _trade


def _identity(
    *,
    run_id: int = 123,
    run_attempt: int = 1,
    head_sha: str = "a" * 40,
) -> ContinuousPaperRuntimeIdentity:
    return ContinuousPaperRuntimeIdentity(
        worker_run_id=run_id,
        worker_run_attempt=run_attempt,
        worker_head_sha=head_sha,
    )


def test_opening_lineage_store_is_append_only_and_idempotent(tmp_path) -> None:
    identity = _identity()
    lineage = ContinuousPaperOpeningLineage(
        opening_plan_id="plan-open-1",
        feature_snapshot_id="f" * 24,
        market="HYPE",
        opened_at_ms=10_000,
        runtime=identity,
    )
    store = ContinuousPaperOpeningLineageStore(tmp_path / "lineage")

    assert store.record(lineage) is True
    assert store.record(lineage) is False
    assert store.load("plan-open-1") == lineage
    assert store.record_count == 1
    assert len(store.state_digest) == 64


def test_continuous_sync_skips_unattributed_legacy_trade_and_preserves_opening_runtime(
    tmp_path,
) -> None:
    attributed_snapshot = _snapshot(as_of_ms=9_000)
    legacy_snapshot = _snapshot(as_of_ms=8_000)

    attributed = _trade(
        attributed_snapshot,
        run_id=CONTINUOUS_PAPER_REPLAY_RUN_ID,
    )
    legacy = replace(
        _trade(
            legacy_snapshot,
            run_id=CONTINUOUS_PAPER_REPLAY_RUN_ID,
        ),
        opening_plan_id="legacy-plan",
        strategy_decision_id="legacy-strategy",
        risk_decision_id="legacy-risk",
        opening_attempt_id="legacy-opening-attempt",
        exit_plan_ids=("legacy-exit-plan",),
        exit_attempt_ids=("legacy-exit-attempt",),
        fill_ids=("legacy-open-fill", "legacy-close-fill"),
        position_action_ids=("legacy-close-action",),
        opened_at_ms=30_000,
        closed_at_ms=40_000,
    )

    journal = JournalStore(tmp_path / "journal.sqlite3")
    journal.record_trade(attributed)
    journal.record_trade(legacy)

    source_features = LearningFeatureSnapshotStore(tmp_path / "source-features")
    source_features.record(attributed_snapshot)
    source_features.record(legacy_snapshot)

    lineage_store = ContinuousPaperOpeningLineageStore(tmp_path / "opening-lineage")
    identity = _identity(run_id=456, run_attempt=2, head_sha="b" * 40)
    lineage_store.record(
        ContinuousPaperOpeningLineage(
            opening_plan_id=attributed.opening_plan_id,
            feature_snapshot_id=attributed.feature_snapshot_id,
            market=attributed.market.canonical,
            opened_at_ms=attributed.opened_at_ms,
            runtime=identity,
        )
    )

    ledger = LearningEvidenceLedger(tmp_path / "learning")
    destination_features = LearningFeatureSnapshotStore(tmp_path / "learning-features")
    try:
        first = sync_continuous_paper_learning_evidence(
            journal,
            source_features,
            lineage_store,
            ledger,
            destination_feature_store=destination_features,
        )
        second = sync_continuous_paper_learning_evidence(
            journal,
            source_features,
            lineage_store,
            ledger,
            destination_feature_store=destination_features,
        )
    finally:
        journal.close()

    assert first.scanned_trades == 2
    assert first.attributed_trades == 1
    assert first.skipped_unattributed_trades == 1
    assert first.created_records == 1
    assert first.existing_records == 0
    assert first.created_feature_snapshots == 1
    assert second.created_records == 0
    assert second.existing_records == 1

    records = ledger.iter_records()
    assert len(records) == 1
    record = records[0]
    assert record.source_record_id == attributed.trade_id
    assert record.candidate_id == CONTINUOUS_PAPER_CANDIDATE_ID
    assert record.candidate_spec_id == identity.worker_head_sha
    assert record.campaign_id == identity.campaign_id
    assert record.research_eligible_at_ms == attributed.closed_at_ms
    assert record.net_pnl == attributed.net_pnl
    assert record.net_r == attributed.net_r
    assert destination_features.load(attributed.feature_snapshot_id) is not None
    assert destination_features.load(legacy.feature_snapshot_id) is None
    assert attributed.replay_run_id == CONTINUOUS_PAPER_REPLAY_RUN_ID


def test_continuous_sync_rejects_mislabeled_opening_lineage(tmp_path) -> None:
    snapshot = _snapshot()
    trade = _trade(snapshot, run_id=CONTINUOUS_PAPER_REPLAY_RUN_ID)
    journal = JournalStore(tmp_path / "journal.sqlite3")
    journal.record_trade(trade)
    features = LearningFeatureSnapshotStore(tmp_path / "features")
    features.record(snapshot)
    lineage_store = ContinuousPaperOpeningLineageStore(tmp_path / "lineage")
    lineage_store.record(
        ContinuousPaperOpeningLineage(
            opening_plan_id=trade.opening_plan_id,
            feature_snapshot_id=trade.feature_snapshot_id,
            market=trade.market.canonical,
            opened_at_ms=trade.opened_at_ms + 1,
            runtime=_identity(),
        )
    )
    try:
        try:
            sync_continuous_paper_learning_evidence(
                journal,
                features,
                lineage_store,
                LearningEvidenceLedger(tmp_path / "learning"),
            )
        except ValueError as exc:
            assert "opened_at_ms" in str(exc)
        else:
            raise AssertionError("mislabeled opening lineage must fail closed")
    finally:
        journal.close()


def test_runtime_identity_requires_real_github_style_identity() -> None:
    try:
        ContinuousPaperRuntimeIdentity(
            worker_run_id=0,
            worker_run_attempt=1,
            worker_head_sha="a" * 40,
        )
    except ValueError as exc:
        assert "worker_run_id" in str(exc)
    else:
        raise AssertionError("zero worker run id must be rejected")

    try:
        ContinuousPaperRuntimeIdentity(
            worker_run_id=1,
            worker_run_attempt=1,
            worker_head_sha="not-a-sha",
        )
    except ValueError as exc:
        assert "worker_head_sha" in str(exc)
    else:
        raise AssertionError("invalid worker head sha must be rejected")
