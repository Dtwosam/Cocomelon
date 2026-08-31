from __future__ import annotations

from pathlib import Path

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.provenance import load_sealed_admitted_batch_provenance
from cocomelon.research.registry import ResearchRegistry
from cocomelon.research.seals import seal_research_batch


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="attested-provenance-candidate",
        family_id="attested-provenance-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json='{"mode":"paper"}',
        risk_config_json='{"risk_per_trade":"0.0025"}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_sealed_unattested_batch_is_not_checkpoint_provenance(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=2_000,
            source_id="authoritative-v4-inventory",
        )
        registry.record_batch(
            candidate_id="attested-provenance-candidate",
            batch_id="sealed-only-batch",
            source_id="sealed-only-source",
            replay_run_id="sealed-only-replay",
            interval=TimeInterval(1_000, 2_000),
        )
        seal_research_batch(
            registry.connection,
            candidate_id="attested-provenance-candidate",
            batch_id="sealed-only-batch",
            trade_ids=(),
            sample_digest=(
                "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
            ),
        )

        assert load_sealed_admitted_batch_provenance(
            registry.connection,
            candidate_id="attested-provenance-candidate",
        ) == ((), ())
    finally:
        registry.close()
