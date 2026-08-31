from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.artifact import ResearchArtifactError, verify_research_batch_artifact
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import ResearchArtifactBatch, evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact


def _write_artifact(
    root: Path,
    *,
    hard_risk: bool = False,
    live_orders: bool = False,
) -> ResearchArtifactBatch:
    return write_research_artifact(
        root,
        batch_id="batch-a",
        source_id="source-a",
        replay_run_id="research-run-a",
        start_ms=0,
        end_ms=5_000,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=2_000,
                net_r=Decimal("0.36382"),
                equity_before=Decimal("10000"),
                planned_risk_fraction=Decimal("0.0025"),
                market="SOL",
                score=Decimal("72"),
                lead_strategy="trend",
                reason_codes=("TREND_UP",),
            ),
        ),
        order_execution=live_orders,
        hard_risk_reason="daily_loss_lockout" if hard_risk else None,
    )


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="candidate-a",
        family_id="family-a",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json='{"mode":"paper"}',
        risk_config_json='{"risk_per_trade":"0.0025","stops_required":true}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_verified_batch_derives_complete_seal_and_planned_risk_from_artifact(
    tmp_path: Path,
) -> None:
    artifact = _write_artifact(tmp_path / "artifact")

    verified = verify_research_batch_artifact(
        artifact.artifact_root,
        batch_id=artifact.batch_id,
        source_id=artifact.source_id,
    )

    assert verified.replay_run_id == "research-run-a"
    assert verified.interval.start_ms == 0
    assert verified.interval.end_ms == 5_000
    assert len(verified.trade_ids) == 1
    trade_id = verified.trade_ids[0]
    assert tuple(sample.trade_id for sample in verified.samples) == (trade_id,)
    assert verified.operational_failure is False
    assert verified.hard_risk_failure is False
    assert verified.planned_risk_fractions == ((trade_id, Decimal("0.0025")),)
    assert len(verified.source_digest) == 64
    assert len(verified.sample_digest) == 64


def test_verified_batch_derives_hard_risk_from_journal_not_caller_input(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "artifact", hard_risk=True)

    verified = verify_research_batch_artifact(
        artifact.artifact_root,
        batch_id=artifact.batch_id,
        source_id=artifact.source_id,
    )

    assert verified.hard_risk_failure is True
    assert "daily_loss_lockout" in verified.health_reason_codes


def test_verified_batch_rejects_live_order_replay_before_research_admission(
    tmp_path: Path,
) -> None:
    artifact = _write_artifact(tmp_path / "artifact", live_orders=True)

    with pytest.raises(ResearchArtifactError, match="genuine mainnet evidence cohort"):
        verify_research_batch_artifact(
            artifact.artifact_root,
            batch_id=artifact.batch_id,
            source_id=artifact.source_id,
        )


def test_checkpoint_evaluator_verifies_artifact_and_derives_planned_risk(
    tmp_path: Path,
) -> None:
    artifact = _write_artifact(tmp_path / "artifact")
    verified = verify_research_batch_artifact(
        artifact.artifact_root,
        batch_id=artifact.batch_id,
        source_id=artifact.source_id,
    )
    trade_id = verified.trade_ids[0]
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=5_000,
            source_id="authoritative-v4-inventory",
        )

        report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id="candidate-a",
            artifact_batches=(artifact,),
        )

        assert report.closed_trade_count == 1
        assert report.batch_ids == ("batch-a",)
        assert report.source_ids == ("source-a",)
        assert report.max_realized_planned_risk_utilization == Decimal("1")
        observations = registry.connection.execute(
            "SELECT payload_json FROM research_trade_observations"
        ).fetchall()
        assert len(observations) == 1
        persisted = json.loads(str(observations[0]["payload_json"]))
        assert persisted["trade_id"] == trade_id
        assert persisted["planned_risk_fraction"] == "0.0025"
    finally:
        registry.close()