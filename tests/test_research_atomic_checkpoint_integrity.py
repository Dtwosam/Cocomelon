from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.provenance import load_sealed_admitted_batch_provenance
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.seals import seal_research_batch
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

DAY_MS = 86_400_000
EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


def _candidate(candidate_id: str) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id="atomic-integrity-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json=EXECUTION_CONFIG,
        risk_config_json=RISK_CONFIG,
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_report_provenance_excludes_sealed_batch_without_authoritative_attestation(
    tmp_path: Path,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=10_000,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate("unattested-candidate"))
    registry.record_batch(
        candidate_id="unattested-candidate",
        batch_id="sealed-only-batch",
        source_id="sealed-only-source",
        replay_run_id="sealed-only-replay",
        interval=TimeInterval(1_000, 2_000),
    )
    seal_research_batch(
        registry.connection,
        candidate_id="unattested-candidate",
        batch_id="sealed-only-batch",
        trade_ids=(),
        sample_digest="0" * 64,
    )

    assert load_sealed_admitted_batch_provenance(
        registry.connection,
        candidate_id="unattested-candidate",
    ) == ((), ())
    registry.close()


def test_late_v4_contamination_before_checkpoint_commit_persists_no_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    registry.mark_v4_registry_complete_through(
        through_ms=3 * DAY_MS,
        source_id="authoritative-v4-inventory",
    )
    registry.create_candidate(_candidate("atomic-candidate"))
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="atomic-batch",
        source_id="atomic-source",
        replay_run_id="atomic-replay",
        start_ms=DAY_MS,
        end_ms=2 * DAY_MS,
        trades=(
            ArtifactTradeSpec(
                closed_at_ms=DAY_MS + 20_000,
                net_r=Decimal("0.2"),
            ),
        ),
    )

    original_record = registry.record_performance_report
    injected = False

    def contaminate_then_record(
        *,
        candidate_id: str,
        report_id: str,
        payload: dict[str, object],
    ) -> None:
        nonlocal injected
        if not injected:
            injected = True
            late = ResearchRegistry(registry_path)
            try:
                late.record_v4_interval(
                    run_id="late-v4",
                    interval=TimeInterval(DAY_MS + 1_000, DAY_MS + 2_000),
                    disposition="diagnostic_failure",
                )
            finally:
                late.close()
        original_record(
            candidate_id=candidate_id,
            report_id=report_id,
            payload=payload,
        )

    monkeypatch.setattr(registry, "record_performance_report", contaminate_then_record)

    with pytest.raises(ResearchRegistryError):
        evaluate_research_checkpoint(
            registry=registry,
            candidate_id="atomic-candidate",
            artifact_batches=(artifact,),
        )

    assert (
        registry.load_candidate("atomic-candidate").state
        is ResearchCandidateState.REJECTED_CONTAMINATION
    )
    report_count = registry.connection.execute(
        "SELECT COUNT(*) AS count FROM research_performance_reports"
    ).fetchone()
    assert report_count is not None
    assert int(report_count["count"]) == 0
    registry.close()
