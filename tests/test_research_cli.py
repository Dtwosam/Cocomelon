from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from cocomelon.research.contracts import ResearchCandidateState
from cocomelon.research.evaluator import evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry
from tests.research_artifact_support import ArtifactTradeSpec, write_research_artifact

research_cli = import_module("cocomelon.research_cli")

DAY_MS = 86_400_000
EXECUTION_CONFIG_INPUT = '{"slippage_model":"recorded","mode":"paper"}'
RISK_CONFIG_INPUT = (
    '{"stops_required":true,"risk_per_trade":"0.0025","max_position_r":"1"}'
)
EXECUTION_CONFIG_CANONICAL = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG_CANONICAL = (
    '{"max_position_r":"1","risk_per_trade":"0.0025","stops_required":true}'
)
V4_INVENTORY_SOURCE = "authoritative-v4-inventory"


def _run_cli(capsys: object, argv: list[str]) -> tuple[int, str, str]:
    exit_code = research_cli.main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _candidate_config_args() -> list[str]:
    return [
        "--execution-config-json",
        EXECUTION_CONFIG_INPUT,
        "--risk-config-json",
        RISK_CONFIG_INPUT,
    ]


def _create_root(capsys: object, registry_path: Path) -> None:
    exit_code, _, _ = _run_cli(
        capsys,
        [
            "create-candidate",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r1",
            "--family-id",
            "family-a",
            "--config-digest",
            "a" * 64,
            "--code-revision",
            "1" * 40,
            *_candidate_config_args(),
        ],
    )
    assert exit_code == 0


def _mark_v4_complete(capsys: object, registry_path: Path, *, through_ms: int) -> None:
    exit_code, _, error = _run_cli(
        capsys,
        [
            "mark-v4-registry-complete",
            "--registry",
            str(registry_path),
            "--through-ms",
            str(through_ms),
            "--source-id",
            V4_INVENTORY_SOURCE,
        ],
    )
    assert exit_code == 0
    assert error == ""


def _record_promising_report(registry: ResearchRegistry, candidate_id: str) -> str:
    registry.mark_v4_registry_complete_through(
        through_ms=8 * DAY_MS,
        source_id=V4_INVENTORY_SOURCE,
    )
    artifact = write_research_artifact(
        registry.path.parent / f"{candidate_id}-promising-artifact",
        batch_id=f"{candidate_id}-promising-batch",
        source_id=f"{candidate_id}-promising-source",
        replay_run_id=f"{candidate_id}-promising-replay",
        start_ms=1_000,
        end_ms=8 * DAY_MS,
        trades=tuple(
            ArtifactTradeSpec(
                closed_at_ms=(index % 7) * DAY_MS + 10_000 + index,
                net_r=Decimal("0.5"),
            )
            for index in range(40)
        ),
    )
    report = evaluate_research_checkpoint(
        registry=registry,
        candidate_id=candidate_id,
        artifact_batches=(artifact,),
    )
    assert report.candidate_state is ResearchCandidateState.RESEARCH_PROMISING
    return report.report_id


def test_cli_emits_deterministic_json_and_exposes_no_live_surface(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    argv = ["init-registry", "--registry", str(registry_path)]

    first_code, first_out, first_err = _run_cli(capsys, argv)
    second_code, second_out, second_err = _run_cli(capsys, argv)

    assert first_code == second_code == 0
    assert first_err == second_err == ""
    assert first_out == second_out
    assert json.loads(first_out) == {
        "command": "init-registry",
        "registry": str(registry_path),
    }

    help_text = research_cli.build_parser().format_help().lower()
    assert "live" not in help_text
    assert "order" not in help_text


def test_create_candidate_persists_canonical_execution_and_risk_identity(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    _create_root(capsys, registry_path)

    registry = ResearchRegistry(registry_path)
    try:
        candidate = registry.load_candidate("candidate-r1")
    finally:
        registry.close()

    assert candidate.execution_config_json == EXECUTION_CONFIG_CANONICAL
    assert candidate.risk_config_json == RISK_CONFIG_CANONICAL
    assert candidate.first_observation_ms is None
    assert candidate.last_observation_ms is None
    assert candidate.source_provenance_ids == ()
    assert candidate.local_touched_intervals == ()
    assert candidate.effective_touched_intervals == ()
    assert candidate.performance_report_ids == ()


def test_mark_v4_registry_complete_is_monotonic_and_source_bound(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"

    first_code, first_out, first_err = _run_cli(
        capsys,
        [
            "mark-v4-registry-complete",
            "--registry",
            str(registry_path),
            "--through-ms",
            "5000",
            "--source-id",
            V4_INVENTORY_SOURCE,
        ],
    )
    assert first_code == 0
    assert first_err == ""
    assert json.loads(first_out) == {
        "command": "mark-v4-registry-complete",
        "source_id": V4_INVENTORY_SOURCE,
        "through_ms": 5000,
    }

    backwards_code, backwards_out, backwards_err = _run_cli(
        capsys,
        [
            "mark-v4-registry-complete",
            "--registry",
            str(registry_path),
            "--through-ms",
            "4999",
            "--source-id",
            V4_INVENTORY_SOURCE,
        ],
    )
    assert backwards_code != 0
    assert backwards_out == ""
    assert "cannot move backwards" in json.loads(backwards_err)["error"]

    changed_source_code, changed_source_out, changed_source_err = _run_cli(
        capsys,
        [
            "mark-v4-registry-complete",
            "--registry",
            str(registry_path),
            "--through-ms",
            "6000",
            "--source-id",
            "different-inventory",
        ],
    )
    assert changed_source_code != 0
    assert changed_source_out == ""
    assert "source cannot change" in json.loads(changed_source_err)["error"]


def test_record_batch_persists_and_rejects_v4_overlap(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    _create_root(capsys, registry_path)
    _mark_v4_complete(capsys, registry_path, through_ms=10_000)

    ok_code, ok_out, ok_err = _run_cli(
        capsys,
        [
            "record-batch",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r1",
            "--batch-id",
            "batch-safe",
            "--source-id",
            "source-safe",
            "--replay-run-id",
            "replay-safe",
            "--start-ms",
            "1000",
            "--end-ms",
            "2000",
        ],
    )
    assert ok_code == 0
    assert ok_err == ""
    assert json.loads(ok_out)["batch_id"] == "batch-safe"

    connection = sqlite3.connect(registry_path)
    try:
        row = connection.execute(
            "SELECT candidate_id, source_id, replay_run_id, start_ms, end_ms "
            "FROM research_batches WHERE batch_id = ?",
            ("batch-safe",),
        ).fetchone()
    finally:
        connection.close()
    assert row == ("candidate-r1", "source-safe", "replay-safe", 1000, 2000)

    register_code, _, register_err = _run_cli(
        capsys,
        [
            "register-v4-interval",
            "--registry",
            str(registry_path),
            "--run-id",
            "v4-diagnostic",
            "--start-ms",
            "3000",
            "--end-ms",
            "4000",
            "--disposition",
            "diagnostic_failure",
        ],
    )
    assert register_code == 0
    assert register_err == ""

    blocked_code, blocked_out, blocked_err = _run_cli(
        capsys,
        [
            "record-batch",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r1",
            "--batch-id",
            "batch-overlap",
            "--source-id",
            "source-overlap",
            "--replay-run-id",
            "replay-overlap",
            "--start-ms",
            "3999",
            "--end-ms",
            "4500",
        ],
    )
    assert blocked_code != 0
    assert blocked_out == ""
    blocked_payload = json.loads(blocked_err)
    assert blocked_payload["error_type"] == "ResearchContaminationError"
    assert "v4-diagnostic" in blocked_payload["error"]


def test_invalid_lineage_and_invalid_cutover_exit_nonzero(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    _create_root(capsys, registry_path)

    lineage_code, lineage_out, lineage_err = _run_cli(
        capsys,
        [
            "create-candidate",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r2",
            "--family-id",
            "family-b",
            "--parent-candidate-id",
            "candidate-r1",
            "--config-digest",
            "b" * 64,
            "--code-revision",
            "2" * 40,
            *_candidate_config_args(),
        ],
    )
    assert lineage_code != 0
    assert lineage_out == ""
    assert json.loads(lineage_err)["error_type"] == "ResearchRegistryError"

    cutover_code, cutover_out, cutover_err = _run_cli(
        capsys,
        [
            "validate-cutover",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r1",
            "--validation-start-ms",
            "100000",
        ],
    )
    assert cutover_code != 0
    assert cutover_out == ""
    assert json.loads(cutover_err)["error_type"] == "ResearchRegistryError"


def test_freeze_candidate_persists_and_checkpoint_is_touched_non_promotional(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    _create_root(capsys, registry_path)

    registry = ResearchRegistry(registry_path)
    registry.transition_candidate(
        "candidate-r1",
        ResearchCandidateState.RESEARCHING,
        reason="test-start",
    )
    _record_promising_report(registry, "candidate-r1")
    registry.close()

    freeze_ms = 8 * DAY_MS + 1
    freeze_code, freeze_out, freeze_err = _run_cli(
        capsys,
        [
            "freeze-candidate",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r1",
            "--freeze-ms",
            str(freeze_ms),
        ],
    )
    assert freeze_code == 0
    assert freeze_err == ""
    assert json.loads(freeze_out)["state"] == "frozen_challenger"

    artifact = write_research_artifact(
        tmp_path / "post-freeze-artifact",
        batch_id="batch-checkpoint",
        source_id="source-checkpoint",
        replay_run_id="replay-checkpoint",
        start_ms=9 * DAY_MS,
        end_ms=9 * DAY_MS + 2_000,
    )
    dataset_path = tmp_path / "checkpoint.json"
    dataset_path.write_text(
        json.dumps(
            {
                "artifact_batches": [
                    {
                        "artifact_root": str(artifact.artifact_root),
                        "batch_id": artifact.batch_id,
                        "source_id": artifact.source_id,
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    checkpoint_code, checkpoint_out, checkpoint_err = _run_cli(
        capsys,
        [
            "checkpoint",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r1",
            "--dataset",
            str(dataset_path),
        ],
    )
    assert checkpoint_code != 0
    assert checkpoint_out == ""
    checkpoint_error = json.loads(checkpoint_err)
    assert checkpoint_error["error_type"] == "ResearchRegistryError"
    assert "terminal" in checkpoint_error["error"]
