from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from tests.research_artifact_support import write_research_artifact

research_cli = import_module("cocomelon.research_cli")

EXECUTION_CONFIG = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG = '{"risk_per_trade":"0.0025","stops_required":true}'
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


def _write_dataset(path: Path, artifact_root: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "artifact_batches": [
                    {
                        "artifact_root": str(artifact_root),
                        "batch_id": "batch-health",
                        "source_id": "source-health",
                    }
                ]
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _run_checkpoint(
    capsys: object,
    *,
    registry_path: Path,
    dataset_path: Path,
) -> tuple[int, str, str]:
    return _run_cli(
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


def test_checkpoint_dataset_rejects_caller_authored_health_state(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    dataset_path = tmp_path / "checkpoint.json"
    _prepare_registry(capsys, registry_path)
    dataset_path.write_text(
        json.dumps(
            {
                "artifact_batches": [],
                "health": {"operational_failure": False, "hard_risk_failure": False},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    code, out, err = _run_checkpoint(
        capsys,
        registry_path=registry_path,
        dataset_path=dataset_path,
    )

    assert code != 0
    assert out == ""
    error = json.loads(err)
    assert error["error_type"] == "ValueError"
    assert "authoritative artifact_batches" in error["error"]


def test_checkpoint_derives_operational_health_failure_from_replay_artifact(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    dataset_path = tmp_path / "checkpoint.json"
    _prepare_registry(capsys, registry_path)
    artifact = write_research_artifact(
        tmp_path / "artifact-operational",
        batch_id="batch-health",
        source_id="source-health",
        replay_run_id="replay-health-operational",
        start_ms=1_000,
        end_ms=2_000,
        data_complete=False,
    )
    _write_dataset(dataset_path, artifact.artifact_root)

    code, out, err = _run_checkpoint(
        capsys,
        registry_path=registry_path,
        dataset_path=dataset_path,
    )

    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert report["candidate_state"] == "rejected_operational"
    assert report["reason_codes"] == ["operational_failure"]


def test_checkpoint_derives_hard_risk_failure_from_journal_artifact(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    dataset_path = tmp_path / "checkpoint.json"
    _prepare_registry(capsys, registry_path)
    artifact = write_research_artifact(
        tmp_path / "artifact-hard-risk",
        batch_id="batch-health",
        source_id="source-health",
        replay_run_id="replay-health-risk",
        start_ms=1_000,
        end_ms=2_000,
        hard_risk_reason="daily_loss_lockout",
    )
    _write_dataset(dataset_path, artifact.artifact_root)

    code, out, err = _run_checkpoint(
        capsys,
        registry_path=registry_path,
        dataset_path=dataset_path,
    )

    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert report["candidate_state"] == "rejected_operational"
    assert report["reason_codes"] == ["hard_risk_failure"]
