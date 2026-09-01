from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.dashboard import build_research_status
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="transaction-candidate",
        family_id="transaction-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json='{"mode":"paper","slippage_model":"recorded"}',
        risk_config_json=(
            '{"max_position_r":"1","risk_per_trade":"0.0025","stops_required":true}'
        ),
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def test_status_rejects_active_transaction_before_contamination_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate())
        registry.mark_v4_registry_complete_through(
            through_ms=200_000,
            source_id="authoritative-v4-test-inventory",
        )
        artifact = write_research_artifact(
            tmp_path / "transaction-artifact",
            batch_id="transaction-batch",
            source_id="transaction-source",
            replay_run_id="transaction-replay",
            start_ms=1_000,
            end_ms=200_000,
            trades=(ArtifactTradeSpec(closed_at_ms=100_000, net_r=Decimal("0.25")),),
        )
        evaluate_research_checkpoint(
            registry=registry,
            candidate_id="transaction-candidate",
            artifact_batches=(artifact,),
        )
        registry.record_v4_interval(
            run_id="late-v4-overlap",
            interval=TimeInterval(start_ms=50_000, end_ms=150_000),
            disposition="accepted",
        )
        registry.connection.execute(
            """
            UPDATE research_candidates
            SET code_revision = code_revision
            WHERE candidate_id = ?
            """,
            ("transaction-candidate",),
        )
        assert registry.connection.in_transaction is True

        def backup_would_hang(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("contamination backup must not run inside active transaction")

        monkeypatch.setitem(
            build_research_status.__globals__,
            "_contamination_authentication_connection",
            backup_would_hang,
        )
        with pytest.raises(ResearchRegistryError, match="active transaction"):
            build_research_status(registry)
    finally:
        registry.connection.rollback()
        registry.close()
