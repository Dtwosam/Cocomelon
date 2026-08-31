from __future__ import annotations

import hashlib
import json
from importlib import import_module
from pathlib import Path

from cocomelon.research.contracts import ResearchCandidateManifest, ResearchCandidateState
from cocomelon.research.registry import ResearchRegistry

research_dashboard_cli = import_module("cocomelon.research_dashboard_cli")

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


def _report_id(payload: dict[str, object]) -> str:
    unsigned = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(unsigned.encode("utf-8")).hexdigest()


def _run(capsys: object, argv: list[str]) -> tuple[int, str, str]:
    exit_code = research_dashboard_cli.main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_status_cli_emits_json_and_markdown_from_same_empty_snapshot(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    registry.close()

    json_code, json_out, json_err = _run(
        capsys,
        ["--registry", str(registry_path), "--format", "json"],
    )
    markdown_code, markdown_out, markdown_err = _run(
        capsys,
        ["--registry", str(registry_path)],
    )

    assert json_code == markdown_code == 0
    assert json_err == markdown_err == ""
    assert json.loads(json_out) == {
        "label": "TOUCHED / NON-PROMOTIONAL",
        "candidate_count": 0,
        "state_counts": {},
        "candidates": [],
    }
    assert markdown_out.startswith(
        "# Research Status\n\n**TOUCHED / NON-PROMOTIONAL**"
    )
    assert "Research results are not promotion or verified-edge evidence." in markdown_out


def test_status_cli_requires_existing_registry_and_does_not_create_one(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "missing.sqlite3"

    code, out, err = _run(capsys, ["--registry", str(registry_path)])

    assert code != 0
    assert out == ""
    assert not registry_path.exists()
    error = json.loads(err)
    assert error["error_type"] == "FileNotFoundError"
    assert "does not exist" in error["error"]


def test_status_cli_fails_closed_on_unauthenticated_report(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    registry = ResearchRegistry(registry_path)
    registry.create_candidate(_candidate("fabricated"))
    fabricated: dict[str, object] = {
        "candidate_id": "fabricated",
        "candidate_state": ResearchCandidateState.RESEARCHING.value,
    }
    report_id = _report_id(fabricated)
    registry.record_performance_report(
        candidate_id="fabricated",
        report_id=report_id,
        payload=fabricated,
    )
    registry.close()

    code, out, err = _run(
        capsys,
        ["--registry", str(registry_path), "--format", "json"],
    )

    assert code != 0
    assert out == ""
    error = json.loads(err)
    assert error["error_type"] == "ResearchRegistryError"
    assert "unauthenticated performance report" in error["error"]


def test_status_cli_surface_has_no_mutation_or_live_options() -> None:
    help_text = research_dashboard_cli.build_parser().format_help().lower()

    assert "--registry" in help_text
    assert "--format" in help_text
    for forbidden in (
        "create-candidate",
        "record-batch",
        "checkpoint",
        "freeze-candidate",
        "register-v4-interval",
        "live-order",
        "send-order",
    ):
        assert forbidden not in help_text
