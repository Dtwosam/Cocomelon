from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry
from tests.research_artifact_support import write_research_artifact


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="atomic-checkpoint-candidate",
        family_id="atomic-checkpoint-family",
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


def test_checkpoint_report_rolls_back_when_state_update_fails(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=2_000,
            source_id="authoritative-v4-inventory",
        )
        artifact = write_research_artifact(
            tmp_path / "artifact",
            batch_id="atomic-checkpoint-batch",
            source_id="atomic-checkpoint-source",
            replay_run_id="atomic-checkpoint-replay",
            start_ms=1_000,
            end_ms=2_000,
        )
        registry.connection.executescript(
            """
            CREATE TRIGGER fail_checkpoint_state_update
            BEFORE UPDATE OF state ON research_candidates
            WHEN OLD.candidate_id = 'atomic-checkpoint-candidate'
            BEGIN
                SELECT RAISE(ABORT, 'forced checkpoint state failure');
            END;
            """
        )
        registry.connection.commit()

        with pytest.raises(sqlite3.IntegrityError, match="forced checkpoint state failure"):
            evaluate_research_checkpoint(
                registry=registry,
                candidate_id="atomic-checkpoint-candidate",
                artifact_batches=(artifact,),
            )

        report_count = registry.connection.execute(
            "SELECT COUNT(*) FROM research_performance_reports WHERE candidate_id = ?",
            ("atomic-checkpoint-candidate",),
        ).fetchone()
        assert report_count is not None
        assert int(report_count[0]) == 0
        assert (
            registry.load_candidate("atomic-checkpoint-candidate").state
            is ResearchCandidateState.DRAFT
        )
    finally:
        registry.close()
