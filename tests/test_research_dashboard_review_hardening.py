from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

import cocomelon.research_dashboard_cli as research_dashboard_cli
from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.dashboard import build_research_status
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","risk_per_trade":"0.0025","stops_required":true}'


def _candidate(candidate_id: str) -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id=candidate_id,
        family_id=f"{candidate_id}-family",
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


def test_status_reconstructs_authenticated_legacy_checkpoint_history(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        registry.create_candidate(_candidate("legacy-candidate"))
        registry.mark_v4_registry_complete_through(
            through_ms=400_000,
            source_id="authoritative-v4-test-inventory",
        )
        first = write_research_artifact(
            tmp_path / "legacy-first",
            batch_id="legacy-batch-first",
            source_id="legacy-source-first",
            replay_run_id="legacy-replay-first",
            start_ms=1_000,
            end_ms=200_000,
            trades=(ArtifactTradeSpec(closed_at_ms=100_000, net_r=Decimal("0.25")),),
        )
        first_report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id="legacy-candidate",
            artifact_batches=(first,),
        )
        second = write_research_artifact(
            tmp_path / "legacy-second",
            batch_id="legacy-batch-second",
            source_id="legacy-source-second",
            replay_run_id="legacy-replay-second",
            start_ms=200_000,
            end_ms=400_000,
            trades=(ArtifactTradeSpec(closed_at_ms=300_000, net_r=Decimal("-0.10")),),
        )
        second_report = evaluate_research_checkpoint(
            registry=registry,
            candidate_id="legacy-candidate",
            artifact_batches=(second,),
        )
        registry.connection.execute("DROP TABLE research_checkpoint_commits")
        registry.connection.commit()

        status = build_research_status(registry)
    finally:
        registry.close()

    checkpoints = status["candidates"][0]["checkpoints"]
    assert [item["report_id"] for item in checkpoints] == [
        first_report.report_id,
        second_report.report_id,
    ]
    assert [item["source_end_ms"] for item in checkpoints] == [200_000, 400_000]


def test_status_cli_does_not_initialize_existing_unrelated_sqlite_file(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "unrelated.sqlite3"
    connection = sqlite3.connect(registry_path)
    connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    connection.execute("INSERT INTO sentinel (value) VALUES ('unchanged')")
    connection.commit()
    connection.close()
    before = registry_path.read_bytes()

    exit_code = research_dashboard_cli.main(
        ["--registry", str(registry_path), "--format", "json"]
    )
    captured = capsys.readouterr()
    after = registry_path.read_bytes()

    verify = sqlite3.connect(registry_path)
    try:
        tables = {
            str(row[0])
            for row in verify.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        }
    finally:
        verify.close()

    assert exit_code != 0
    assert captured.out == ""
    assert "schema" in json.loads(captured.err)["error"].lower()
    assert before == after
    assert tables == {"sentinel"}


def test_status_build_uses_one_sqlite_read_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    writer: ResearchRegistry | None = None
    try:
        registry.connection.execute("PRAGMA journal_mode = WAL")
        registry.create_candidate(_candidate("snapshot-candidate"))
        registry.mark_v4_registry_complete_through(
            through_ms=200_000,
            source_id="authoritative-v4-test-inventory",
        )
        artifact = write_research_artifact(
            tmp_path / "snapshot-artifact",
            batch_id="snapshot-batch",
            source_id="snapshot-source",
            replay_run_id="snapshot-replay",
            start_ms=1_000,
            end_ms=200_000,
            trades=(ArtifactTradeSpec(closed_at_ms=100_000, net_r=Decimal("0.25")),),
        )
        writer = ResearchRegistry(registry_path)
        original_load = registry.load_candidate
        checkpoint_written = False

        def load_then_checkpoint(candidate_id: str) -> ResearchCandidateManifest:
            nonlocal checkpoint_written
            candidate = original_load(candidate_id)
            if not checkpoint_written:
                checkpoint_written = True
                assert writer is not None
                evaluate_research_checkpoint(
                    registry=writer,
                    candidate_id="snapshot-candidate",
                    artifact_batches=(artifact,),
                )
            return candidate

        monkeypatch.setattr(registry, "load_candidate", load_then_checkpoint)
        status = build_research_status(registry)
    finally:
        if writer is not None:
            writer.close()
        registry.close()

    assert checkpoint_written is True
    candidate = status["candidates"][0]
    assert candidate["state"] == ResearchCandidateState.DRAFT.value
    assert candidate["checkpoint_count"] == 0
    assert candidate["checkpoints"] == []
