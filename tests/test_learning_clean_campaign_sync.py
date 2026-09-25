from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

from cocomelon.domain.market import MarketId
from cocomelon.journal.store import JournalStore
from cocomelon.research import research_learning_sync
from cocomelon.research.learning_clean_campaign_sync import (
    sync_learning_clean_research_campaign,
)
from cocomelon.research.learning_clean_evidence import LearningCleanEvidenceStore
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from tests.test_execution_learning_sync import _snapshot, _trade
from tests.test_learning_clean_validation_score import _setup
from tests.test_research_learning_sync import _write_json


def _campaign(
    tmp_path,
    *,
    spec,
    market: MarketId = MarketId("", "HYPE"),
    snapshot_offset_ms: int = 1_000,
) -> tuple[object, object, object]:
    campaign = tmp_path / f"campaign-{market.canonical}-{snapshot_offset_ms}"
    output = campaign / "audit" / "evaluated" / "root-key" / "output"
    output.mkdir(parents=True)

    snapshot = _snapshot(
        as_of_ms=spec.validation_start_ms + snapshot_offset_ms,
        market=market,
    )
    opened_at_ms = snapshot.as_of_ms + 100
    closed_at_ms = opened_at_ms + 1_000
    trade = replace(
        _trade(snapshot, run_id="run-clean-1"),
        market=market,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        holding_duration_ms=closed_at_ms - opened_at_ms,
        net_r=Decimal("0.25"),
        replay_run_id="run-clean-1",
    )

    journal = JournalStore(output / "journal.sqlite3")
    try:
        journal.record_trade(trade)
    finally:
        journal.close()

    features = LearningFeatureSnapshotStore(output / "learning-features")
    features.record(snapshot)
    _write_json(
        output / "replay.json",
        {
            "run_id": "run-clean-1",
            "feature_snapshot_count": 1,
            "feature_snapshot_state_digest": features.state_digest,
        },
    )
    (output / "trigger-head.txt").write_text("a" * 40 + "\n", encoding="utf-8")
    _write_json(
        output / "runner.json",
        {
            "status": "succeeded",
            "label": "TOUCHED / NON-PROMOTIONAL",
            "end_ms": closed_at_ms + 1_000,
        },
    )
    _write_json(
        campaign / "state" / "research-fanout.json",
        {
            "schema_version": 1,
            "candidates": [
                {
                    "artifact_key": "root-key",
                    "batch_id": "batch-clean-1",
                    "candidate_id": "scheduled-research-root",
                    "required": True,
                    "source_id": "source-clean-1",
                }
            ],
        },
    )
    verified = SimpleNamespace(
        replay_run_id="run-clean-1",
        trade_ids=(trade.trade_id,),
        interval=SimpleNamespace(end_ms=closed_at_ms),
    )
    return campaign, snapshot, trade, verified


def _kwargs() -> dict[str, object]:
    return {
        "upstream_run_id": 123,
        "upstream_run_attempt": 1,
        "upstream_head_sha": "a" * 40,
        "upstream_artifact_id": 456,
        "upstream_artifact_digest": "sha256:" + "b" * 64,
    }


def test_clean_campaign_sync_appends_accepted_trade_and_is_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    campaign, _snapshot_value, trade, verified = _campaign(
        tmp_path,
        spec=spec,
    )
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: verified,
    )

    first = sync_learning_clean_research_campaign(
        campaign_root=campaign,
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        **_kwargs(),
    )
    second = sync_learning_clean_research_campaign(
        campaign_root=campaign,
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        **_kwargs(),
    )

    assert first.source_trade_count == 1
    assert first.pre_validation_source_trade_count == 0
    assert first.clean_trade_prediction_count == 1
    assert first.clean_no_trade_prediction_count == 0
    assert len(first.clean_prediction_ids) == 1
    assert len(first.clean_outcome_ids) == 1
    assert first.prediction_count_after == 1
    assert first.settled_outcome_count_after == 1
    assert first.unsettled_trade_prediction_count_after == 0
    assert second == first

    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    predictions = store.iter_predictions()
    outcomes = store.iter_outcomes()
    assert len(predictions) == 1
    assert len(outcomes) == 1
    assert outcomes[0].source_trade_id == trade.trade_id
    assert outcomes[0].net_r == Decimal("0.25")


def test_clean_campaign_sync_records_no_trade_without_outcome(
    tmp_path,
    monkeypatch,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    campaign, _snapshot_value, _trade_value, verified = _campaign(
        tmp_path,
        spec=spec,
        market=MarketId("", "BTC"),
    )
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: verified,
    )

    result = sync_learning_clean_research_campaign(
        campaign_root=campaign,
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        **_kwargs(),
    )

    assert result.source_trade_count == 1
    assert result.clean_trade_prediction_count == 0
    assert result.clean_no_trade_prediction_count == 1
    assert len(result.clean_prediction_ids) == 1
    assert result.clean_outcome_ids == ()
    assert result.prediction_count_after == 1
    assert result.settled_outcome_count_after == 0
    assert result.unsettled_trade_prediction_count_after == 0


def test_clean_campaign_sync_skips_pre_validation_trade(
    tmp_path,
    monkeypatch,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    campaign, _snapshot_value, _trade_value, verified = _campaign(
        tmp_path,
        spec=spec,
        snapshot_offset_ms=-2_000,
    )
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: verified,
    )

    result = sync_learning_clean_research_campaign(
        campaign_root=campaign,
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        **_kwargs(),
    )

    assert result.source_trade_count == 1
    assert result.pre_validation_source_trade_count == 1
    assert result.clean_prediction_ids == ()
    assert result.clean_outcome_ids == ()
    assert result.prediction_count_after == 0
    assert result.settled_outcome_count_after == 0


def test_clean_campaign_sync_rejects_upstream_head_mismatch(
    tmp_path,
    monkeypatch,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    campaign, _snapshot_value, _trade_value, verified = _campaign(
        tmp_path,
        spec=spec,
    )
    monkeypatch.setattr(
        research_learning_sync,
        "verify_research_batch_artifact",
        lambda *_args, **_kwargs: verified,
    )

    bad = _kwargs()
    bad["upstream_head_sha"] = "c" * 40

    try:
        sync_learning_clean_research_campaign(
            campaign_root=campaign,
            package_root=package_root,
            validation_spec_path=spec_path,
            evidence_root=evidence_root,
            **bad,
        )
    except RuntimeError as exc:
        assert "UPSTREAM_HEAD_MISMATCH" in str(exc)
    else:
        raise AssertionError("expected upstream head mismatch")
