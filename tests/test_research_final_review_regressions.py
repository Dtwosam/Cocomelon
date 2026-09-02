from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

SYNC_WORKFLOW = Path(".github/workflows/research-v4-registry-sync.yml")


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="final-review-candidate",
        family_id="final-review-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest="a" * 64,
        code_revision="1" * 40,
        execution_config_json='{"mode":"paper","slippage_model":"recorded"}',
        risk_config_json='{"risk_per_trade":"0.0025"}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def _batch_row_count(registry: ResearchRegistry, table_name: str, batch_id: str) -> int:
    table = registry.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    if table is None:
        return 0
    row = registry.connection.execute(
        f"SELECT COUNT(*) FROM {table_name} WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_failed_final_checkpoint_rolls_back_new_batch_economics(
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
            tmp_path / "artifact",
            batch_id="failed-final-batch",
            source_id="failed-final-source",
            replay_run_id="failed-final-replay",
            start_ms=1_000,
            end_ms=200_000,
            trades=(ArtifactTradeSpec(closed_at_ms=100_000, net_r=Decimal("0.25")),),
        )

        def reject_final_checkpoint(*_args: object, **_kwargs: object) -> None:
            raise ResearchRegistryError("forced final checkpoint validation failure")

        monkeypatch.setattr(
            registry,
            "_validate_checkpoint_report_for_state",
            reject_final_checkpoint,
        )
        with pytest.raises(
            ResearchRegistryError,
            match="forced final checkpoint validation failure",
        ):
            evaluate_research_checkpoint(
                registry=registry,
                candidate_id="final-review-candidate",
                artifact_batches=(artifact,),
            )

        batch_count = _batch_row_count(registry, "research_batches", "failed-final-batch")
        observation_count = _batch_row_count(
            registry,
            "research_trade_observations",
            "failed-final-batch",
        )
        seal_count = _batch_row_count(
            registry,
            "research_batch_seals",
            "failed-final-batch",
        )
        attestation_count = _batch_row_count(
            registry,
            "research_batch_attestations",
            "failed-final-batch",
        )
    finally:
        registry.close()

    assert batch_count == 0
    assert observation_count == 0
    assert seal_count == 0
    assert attestation_count == 0


def test_v4_sync_restores_and_publishes_durable_authority_seed() -> None:
    source = SYNC_WORKFLOW.read_text(encoding="utf-8")

    restore_name = "Restore durable V4 authority seed when registry snapshot is unavailable"
    snapshot_name = "Snapshot already-recorded V4 acquisition identities"
    build_name = "Build durable V4 authority seed"
    publish_name = "Publish durable V4 authority seed"

    assert restore_name in source
    assert source.index(restore_name) < source.index(snapshot_name)
    restore = source.split(f"- name: {restore_name}", 1)[1].split("\n      - name:", 1)[0]
    assert "research-v4-authority-seed" in restore
    assert '.path == ".github/workflows/research-v4-registry-sync.yml"' in restore
    assert "merge_v4_authority_snapshot" in restore
    assert "restored-artifact-id.txt" in restore

    assert build_name in source
    assert publish_name in source
    assert source.index(build_name) < source.index(publish_name)
    build = source.split(f"- name: {build_name}", 1)[1].split("\n      - name:", 1)[0]
    assert "merge_v4_authority_snapshot" in build
    publish = source.split(f"- name: {publish_name}", 1)[1].split("\n      - name:", 1)[0]
    assert "name: research-v4-authority-seed" in publish
    assert "retention-days: 90" in publish
