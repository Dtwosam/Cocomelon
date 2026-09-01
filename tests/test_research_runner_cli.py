from __future__ import annotations

import inspect
import json
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
)
from cocomelon.research.registry import ResearchRegistry
from cocomelon.research.runner_history import (
    ResearchRunnerAttemptStatus,
    finish_runner_attempt,
    record_runner_attempt_started,
)
from tests.research_artifact_support import (
    CODE_REVISION,
    CONFIG_DIGEST,
    ArtifactTradeSpec,
    write_research_artifact,
)

research_runner_cli = import_module("cocomelon.research_runner_cli")


def _candidate() -> ResearchCandidateManifest:
    return ResearchCandidateManifest(
        candidate_id="runner-cli-candidate",
        family_id="runner-cli-family",
        parent_candidate_id=None,
        ancestor_candidate_ids=(),
        config_digest=CONFIG_DIGEST,
        code_revision=CODE_REVISION,
        execution_config_json='{"mode":"paper","slippage_model":"recorded"}',
        risk_config_json='{"risk_per_trade":"0.0025","stops_required":true}',
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )


def _run(capsys: object, argv: list[str]) -> tuple[int, str, str]:
    code = research_runner_cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_runner_cli_run_artifact_emits_non_promotional_result(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    registry.create_candidate(_candidate())
    registry.mark_v4_registry_complete_through(
        through_ms=3_000,
        source_id="authoritative-v4-inventory",
    )
    registry.close()
    artifact = write_research_artifact(
        tmp_path / "artifact",
        batch_id="cli-batch",
        source_id="cli-source",
        replay_run_id="cli-replay",
        start_ms=1_000,
        end_ms=3_000,
        trades=(ArtifactTradeSpec(closed_at_ms=2_500, net_r=Decimal("0.25")),),
    )

    code, out, err = _run(
        capsys,
        [
            "run-artifact",
            "--registry",
            str(registry_path),
            "--attempt-id",
            "cli-attempt",
            "--candidate-id",
            "runner-cli-candidate",
            "--batch-id",
            artifact.batch_id,
            "--source-id",
            artifact.source_id,
            "--artifact-root",
            str(artifact.artifact_root),
        ],
    )

    assert code == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["label"] == "TOUCHED / NON-PROMOTIONAL"
    assert payload["attempt_id"] == "cli-attempt"
    assert payload["status"] == "succeeded"
    assert payload["start_ms"] == 1_000
    assert payload["end_ms"] == 3_000
    assert len(payload["report_id"]) == 64
    assert "net_pnl" not in payload


def test_runner_cli_attempts_is_deterministic_non_economic_history(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    record_runner_attempt_started(
        registry.connection,
        attempt_id="attempt-1",
        candidate_id="candidate-1",
        batch_id="batch-1",
        source_id="source-1",
        artifact_root="/artifact/output",
    )
    finish_runner_attempt(
        registry.connection,
        attempt_id="attempt-1",
        status=ResearchRunnerAttemptStatus.FAILED,
        start_ms=1_000,
        end_ms=2_000,
        report_id=None,
        error_type="TimeoutError",
        error_message="capture timeout",
    )
    registry.close()

    code, out, err = _run(
        capsys,
        ["attempts", "--registry", str(registry_path)],
    )

    expected = {
        "attempts": [
            {
                "artifact_root": "/artifact/output",
                "attempt_id": "attempt-1",
                "attempt_index": 1,
                "batch_id": "batch-1",
                "candidate_id": "candidate-1",
                "end_ms": 2_000,
                "error_message": "capture timeout",
                "error_type": "TimeoutError",
                "report_id": None,
                "source_id": "source-1",
                "start_ms": 1_000,
                "status": "failed",
            }
        ],
        "label": "TOUCHED / NON-PROMOTIONAL",
    }
    assert code == 0
    assert err == ""
    assert out == json.dumps(expected, sort_keys=True, separators=(",", ":")) + "\n"
    assert "net_pnl" not in out
    assert "mean_net_r" not in out


def test_runner_cli_requires_existing_registry_without_bootstrapping(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "missing.sqlite3"

    code, out, err = _run(
        capsys,
        ["attempts", "--registry", str(registry_path)],
    )

    assert code == 2
    assert out == ""
    assert not registry_path.exists()
    payload = json.loads(err)
    assert payload["error_type"] == "FileNotFoundError"
    assert "does not exist" in payload["error"]


def test_runner_cli_has_no_v4_or_live_execution_surface() -> None:
    help_text = research_runner_cli.build_parser().format_help().lower()
    source = inspect.getsource(research_runner_cli).lower()

    assert "run-artifact" in help_text
    assert "attempts" in help_text
    for forbidden in (
        "v4-mainnet-corpus",
        "phase9-v4-one-shot",
        "candidate_edge",
        "private_key",
        "wallet",
        "withdraw",
        "transfer",
        "send_order",
        "live_order",
    ):
        assert forbidden not in help_text
        assert forbidden not in source
