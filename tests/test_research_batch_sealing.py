from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="sealed-candidate",
        family_id="sealed-family",
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


def test_checkpoint_cannot_omit_any_canonical_closed_trade(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    registry.mark_v4_registry_complete_through(
        through_ms=10_000,
        source_id="authoritative-v4-inventory",
    )
    candidate = _candidate()
    registry.create_candidate(candidate)
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="sealed-batch",
        source_id="sealed-source",
        replay_run_id="sealed-replay",
        start_ms=1_000,
        end_ms=8_000,
        trades=(
            ArtifactTradeSpec(closed_at_ms=3_000, net_r=Decimal("0.5")),
            ArtifactTradeSpec(closed_at_ms=5_000, net_r=Decimal("-0.4")),
        ),
    )

    report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate.candidate_id,
        artifact_batches=(artifact,),
    )

    assert report.closed_trade_count == 2
    rows = registry.connection.execute(
        "SELECT trade_id FROM research_trade_observations ORDER BY trade_id"
    ).fetchall()
    assert len(rows) == 2
    seal = registry.connection.execute(
        "SELECT trade_ids_json FROM research_batch_seals WHERE batch_id = ?",
        ("sealed-batch",),
    ).fetchone()
    assert seal is not None
    registry.close()
