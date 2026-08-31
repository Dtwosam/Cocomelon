from __future__ import annotations

import hashlib
import json
import sqlite3
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from cocomelon.research.contracts import ResearchCandidateState
from cocomelon.research.observations import record_trade_observations
from cocomelon.research.registry import ResearchRegistry
from cocomelon.research.sequential import evaluate_checkpoint

research_cli = import_module("cocomelon.research_cli")

DAY_MS = 86_400_000
EXECUTION_CONFIG_INPUT = '{"slippage_model":"recorded","mode":"paper"}'
RISK_CONFIG_INPUT = '{"stops_required":true,"max_position_r":"1"}'
EXECUTION_CONFIG_CANONICAL = '{"mode":"paper","slippage_model":"recorded"}'
RISK_CONFIG_CANONICAL = '{"max_position_r":"1","stops_required":true}'
V4_INVENTORY_SOURCE = "authoritative-v4-inventory"
EMPTY_SAMPLE_DIGEST = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"


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
    observations = tuple(
        {
            "trade_id": f"{candidate_id}-cli-trade-{index}",
            "closed_at_ms": (index % 7) * DAY_MS + 1_000 + index,
            "net_pnl": "5",
            "net_r": "0.5",
            "equity_before": "1000",
        }
        for index in range(40)
    )
    record_trade_observations(
        registry.connection,
        candidate_id=candidate_id,
        observations=observations,
    )
    checkpoint = evaluate_checkpoint(
        net_r_values=tuple(Decimal("0.5") for _ in observations),
        closed_trade_days=7,
    )
    assert checkpoint.candidate_state is ResearchCandidateState.RESEARCH_PROMISING
    payload: dict[str, object] = {
        "candidate_id": candidate_id,
        "candidate_state": checkpoint.candidate_state.value,
        "checkpoint_state": checkpoint.checkpoint_state.value,
        "closed_trade_count": checkpoint.trade_count,
        "closed_trade_days": checkpoint.closed_trade_days,
        "posterior_probability_positive": (
            None
            if checkpoint.posterior_probability_positive is None
            else str(checkpoint.posterior_probability_positive)
        ),
        "policy_digest": checkpoint.policy_digest,
        "reason_codes": list(checkpoint.reason_codes),
        "realized_closed_trade_max_drawdown_fraction": "0",
        "max_realized_planned_risk_utilization": "0",
        "batch_ids": [],
        "source_ids": [],
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    report_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    registry.record_performance_report(
        candidate_id=candidate_id,
        report_id=report_id,
        payload=payload,
    )
    return report_id


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
    report_id = _record_promising_report(registry, "candidate-r1")
    registry.apply_checkpoint_state(
        "candidate-r1",
        ResearchCandidateState.RESEARCH_PROMISING,
        report_id=report_id,
    )
    registry.close()

    freeze_code, freeze_out, freeze_err = _run_cli(
        capsys,
        [
            "freeze-candidate",
            "--registry",
            str(registry_path),
            "--candidate-id",
            "candidate-r1",
            "--freeze-ms",
            "25000",
        ],
    )
    assert freeze_code == 0
    assert freeze_err == ""
    assert json.loads(freeze_out)["state"] == "frozen_challenger"

    dataset_path = tmp_path / "checkpoint.json"
    dataset_path.write_text(
        json.dumps(
            {
                "batches": [
                    {
                        "batch_id": "batch-checkpoint",
                        "source_id": "source-checkpoint",
                        "replay_run_id": "replay-checkpoint",
                        "start_ms": 50000,
                        "end_ms": 60000,
                        "trade_ids": [],
                        "sample_digest": EMPTY_SAMPLE_DIGEST,
                    }
                ],
                "health": {
                    "hard_risk_failure": False,
                    "operational_failure": False,
                },
                "samples": [],
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
