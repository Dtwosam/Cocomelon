from __future__ import annotations

import inspect
import sqlite3
from decimal import Decimal
from pathlib import Path

import cocomelon.research.dashboard as research_dashboard
import cocomelon.research_dashboard_cli as research_dashboard_cli
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
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


def _seed_checkpoint(registry: ResearchRegistry, tmp_path: Path) -> None:
    registry.create_candidate(_candidate("candidate-a"))
    registry.mark_v4_registry_complete_through(
        through_ms=200_000,
        source_id="authoritative-v4-test-inventory",
    )
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="batch-a",
        source_id="source-a",
        replay_run_id="replay-a",
        start_ms=1_000,
        end_ms=200_000,
        trades=(ArtifactTradeSpec(closed_at_ms=100_000, net_r=Decimal("0.25")),),
    )
    evaluate_research_checkpoint(
        registry=registry,
        candidate_id="candidate-a",
        artifact_batches=(artifact,),
    )


def _semantic_snapshot(path: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    connection = sqlite3.connect(path)
    try:
        tables = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'research_%'
                ORDER BY name
                """
            ).fetchall()
        )
        result: dict[str, tuple[tuple[object, ...], ...]] = {}
        for table in tables:
            columns = tuple(
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            )
            order = ", ".join(columns)
            rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            result[table] = tuple(tuple(row) for row in rows)
        return result
    finally:
        connection.close()


def test_dashboard_and_cli_are_semantically_read_only(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    _seed_checkpoint(registry, tmp_path)
    before = _semantic_snapshot(registry_path)

    status = research_dashboard.build_research_status(registry)
    rendered = research_dashboard.render_research_status_markdown(status)
    registry.close()

    exit_code = research_dashboard_cli.main(
        ["--registry", str(registry_path), "--format", "json"]
    )
    captured = capsys.readouterr()
    after = _semantic_snapshot(registry_path)

    assert rendered.startswith("# Research Status")
    assert exit_code == 0
    assert captured.err == ""
    assert before == after


def test_dashboard_source_has_no_v4_economic_or_live_execution_surface() -> None:
    source = "\n".join(
        (
            inspect.getsource(research_dashboard),
            inspect.getsource(research_dashboard_cli),
        )
    ).lower()

    for forbidden in (
        "v4-mainnet-corpus",
        "phase9-v4-one-shot",
        "candidate_edge",
        "live_order",
        "send_order",
        "private_key",
        "wallet",
        "withdraw",
    ):
        assert forbidden not in source


def test_retroactive_contamination_hides_research_economics(tmp_path: Path) -> None:
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        _seed_checkpoint(registry, tmp_path)
        before = research_dashboard.build_research_status(registry)
        assert before["candidates"][0]["economics_visible"] is True
        assert len(before["candidates"][0]["checkpoints"]) == 1

        registry.record_v4_interval(
            run_id="late-v4-overlap",
            interval=TimeInterval(150_000, 250_000),
            disposition="diagnostic_failure",
        )
        after = research_dashboard.build_research_status(registry)
    finally:
        registry.close()

    candidate = after["candidates"][0]
    assert candidate["state"] == ResearchCandidateState.REJECTED_CONTAMINATION.value
    assert candidate["economics_visible"] is False
    assert candidate["checkpoints"] == []
    rendered = research_dashboard.render_research_status_markdown(after)
    assert "Economics hidden because the candidate is contaminated." in rendered
    assert "6.250000" not in rendered
