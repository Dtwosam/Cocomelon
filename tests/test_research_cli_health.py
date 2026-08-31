from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

research_cli = import_module("cocomelon.research_cli")

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"max_position_r":"1","stops_required":true}'
V4_SOURCE = "authoritative-v4-inventory"


def _run_cli(capsys: object, argv: list[str]) -> tuple[int, str, str]:
    exit_code = research_cli.main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _prepare_registry(capsys: object, registry_path: Path) -> None:
    create_code, _, create_err = _run_cli(
        capsys,
        [
            "create-candidate",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-health",
            "--family-id",
            "family-health",
            "--config-digest",
            "a" * 64,
            "--code-revision",
            "1" * 40,
            "--execution-config-json",
            EXECUTION_CONFIG,
            "--risk-config-json",
            RISK_CONFIG,
        ],
    )
    assert create_code == 0
    assert create_err == ""
    completeness_code, _, completeness_err = _run_cli(
        capsys,
        [
            "mark-v4-registry-complete",
            "--registry",
            str(registry_path),
            "--through-ms",
            "10000",
            "--source-id",
            V4_SOURCE,
        ],
    )
    assert completeness_code == 0
    assert completeness_err == ""


def _write_dataset(path: Path, *, health: dict[str, bool] | None) -> None:
    payload: dict[str, object] = {
        "batches": [
            {
                "batch_id": "batch-health",
                "source_id": "source-health",
                "replay_run_id": "replay-health",
                "start_ms": 1000,
                "end_ms": 2000,
            }
        ],
        "samples": [],
    }
    if health is not None:
        payload["health"] = health
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def test_checkpoint_dataset_requires_explicit_health_state(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    dataset_path = tmp_path / "checkpoint.json"
    _prepare_registry(capsys, registry_path)
    _write_dataset(dataset_path, health=None)

    code, out, err = _run_cli(
        capsys,
        [
            "checkpoint",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-health",
            "--dataset",
            str(dataset_path),
        ],
    )

    assert code != 0
    assert out == ""
    error = json.loads(err)
    assert error["error_type"] == "ValueError"
    assert "health" in error["error"]


def test_checkpoint_carries_operational_health_failure_into_rejection(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    dataset_path = tmp_path / "checkpoint.json"
    _prepare_registry(capsys, registry_path)
    _write_dataset(
        dataset_path,
        health={"operational_failure": True, "hard_risk_failure": False},
    )

    code, out, err = _run_cli(
        capsys,
        [
            "checkpoint",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-health",
            "--dataset",
            str(dataset_path),
        ],
    )

    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert report["candidate_state"] == "rejected_operational"
    assert report["reason_codes"] == ["operational_failure"]


def test_checkpoint_carries_hard_risk_health_failure_into_rejection(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    dataset_path = tmp_path / "checkpoint.json"
    _prepare_registry(capsys, registry_path)
    _write_dataset(
        dataset_path,
        health={"operational_failure": False, "hard_risk_failure": True},
    )

    code, out, err = _run_cli(
        capsys,
        [
            "checkpoint",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-health",
            "--dataset",
            str(dataset_path),
        ],
    )

    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert report["candidate_state"] == "rejected_operational"
    assert report["reason_codes"] == ["hard_risk_failure"]
