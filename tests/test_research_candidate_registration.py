from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

from cocomelon.research.bootstrap import ensure_bootstrap_candidate
from cocomelon.research.cohort import research_replay_config_from_candidate
from cocomelon.research.contracts import ResearchCandidateState, TimeInterval
from cocomelon.research.registry import ResearchRegistry

research_cli = import_module("cocomelon.research_cli")


def _run_cli(capsys: object, argv: list[str]) -> tuple[int, str, str]:
    exit_code = research_cli.main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _bootstrap_registry(path: Path) -> None:
    registry = ResearchRegistry(path)
    try:
        ensure_bootstrap_candidate(
            registry,
            candidate_id="scheduled-research-root",
            code_revision="1" * 40,
        )
        registry.record_touched_interval(
            "scheduled-research-root",
            TimeInterval(1_000, 2_000),
            source_id="touched-root-source",
        )
    finally:
        registry.close()


def _write_spec(path: Path, *, starting_cash: str = "10000") -> None:
    path.write_text(
        json.dumps(
            {
                "candidate_id": "research-r1-exit-15m-v1",
                "parent_candidate_id": "scheduled-research-root",
                "execution_config": {
                    "config_version": "research-paper-15m-expiry-v1",
                    "max_position_age_ms": 900_000,
                    "starting_cash": starting_cash,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_register_candidate_spec_derives_identity_and_inherits_touched_lineage(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    spec_path = tmp_path / "challenger.json"
    _bootstrap_registry(registry_path)
    _write_spec(spec_path)

    code, out, err = _run_cli(
        capsys,
        [
            "register-candidate-spec",
            "--registry",
            str(registry_path),
            "--spec",
            str(spec_path),
        ],
    )

    assert code == 0
    assert err == ""
    assert json.loads(out) == {
        "candidate_id": "research-r1-exit-15m-v1",
        "command": "register-candidate-spec",
        "parent_candidate_id": "scheduled-research-root",
        "state": "draft",
    }

    registry = ResearchRegistry(registry_path)
    try:
        parent = registry.load_candidate("scheduled-research-root")
        child = registry.load_candidate("research-r1-exit-15m-v1")
    finally:
        registry.close()
    replay_config = research_replay_config_from_candidate(child)
    parent_replay_config = research_replay_config_from_candidate(parent)
    assert child.family_id == parent.family_id
    assert child.parent_candidate_id == parent.candidate_id
    assert child.ancestor_candidate_ids == (parent.candidate_id,)
    assert child.code_revision == parent.code_revision
    assert child.risk_config_json == parent.risk_config_json
    assert child.state is ResearchCandidateState.DRAFT
    assert child.local_touched_intervals == ()
    assert child.effective_touched_intervals == (TimeInterval(1_000, 2_000),)
    assert replay_config.execution.max_position_age_ms == 900_000
    assert replay_config.execution.config_version == "research-paper-15m-expiry-v1"
    assert replay_config.starting_cash == parent_replay_config.starting_cash


def test_register_candidate_spec_rejects_starting_cash_change(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    spec_path = tmp_path / "challenger.json"
    _bootstrap_registry(registry_path)
    _write_spec(spec_path, starting_cash="20000")
    code, out, err = _run_cli(capsys, [
        "register-candidate-spec",
        "--registry",
        str(registry_path),
        "--spec",
        str(spec_path),
    ])
    assert code != 0
    assert out == ""
    assert "starting_cash" in json.loads(err)["error"]


def test_register_candidate_spec_is_idempotent_for_exact_identity(
    tmp_path: Path,
    capsys: object,
) -> None:
    registry_path = tmp_path / "research.sqlite3"
    spec_path = tmp_path / "challenger.json"
    _bootstrap_registry(registry_path)
    _write_spec(spec_path)

    first = _run_cli(
        capsys,
        ["register-candidate-spec", "--registry", str(registry_path), "--spec", str(spec_path)],
    )
    second = _run_cli(
        capsys,
        ["register-candidate-spec", "--registry", str(registry_path), "--spec", str(spec_path)],
    )

    assert first[0] == second[0] == 0
    assert json.loads(first[1]) == json.loads(second[1])
    assert first[2] == second[2] == ""


def test_registration_workflow_is_registry_only_and_publisher_locked() -> None:
    workflow = Path(".github/workflows/research-candidate-register.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in workflow
    assert "research-authoritative-registry-publisher" in workflow
    assert "register-candidate-spec" in workflow
    assert "research-authoritative-registry" in workflow
    assert "record-mainnet-evidence" not in workflow
    assert "api.hyperliquid" not in workflow
    assert "RESEARCH_CHALLENGER_CANDIDATE_ID" not in workflow


def test_authority_consumers_trust_only_successful_registration_dispatch() -> None:
    for path in (
        Path(".github/workflows/research-campaign-scheduled.yml"),
        Path(".github/workflows/research-v4-registry-sync.yml"),
        Path(".github/workflows/research-dashboard.yml"),
    ):
        workflow = path.read_text(encoding="utf-8")
        assert 'research-candidate-register.yml' in workflow
        assert '(.event == "workflow_dispatch")' in workflow
