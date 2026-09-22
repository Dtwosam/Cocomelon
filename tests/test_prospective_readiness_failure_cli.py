from __future__ import annotations

import json

from cocomelon.prospective_hype_readiness_failure_cli import main


def test_readiness_failure_cli_emits_redacted_bound_receipt(
    capsys: object,
) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "build",
            "--reason-code",
            "READINESS_CONTRACT_VERIFY_FAILED",
            "--observer-workflow-sha256",
            "a" * 64,
        ]
    ) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["stage"] == "build"
    assert payload["reason_code"] == "READINESS_CONTRACT_VERIFY_FAILED"
    assert payload["observer_workflow_sha256"] == "a" * 64
    assert payload["interim_economics_redacted"] is True
    assert len(payload["campaign_id"]) == 64
    assert len(payload["candidate_spec_id"]) == 64
    assert len(payload["validation_plan_id"]) == 64
    assert len(payload["failure_id"]) == 64


def test_readiness_failure_cli_accepts_missing_workflow_sha(
    capsys: object,
) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "build",
            "--reason-code",
            "READINESS_WORKFLOW_MISSING",
            "--observer-workflow-sha256",
            "none",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["observer_workflow_sha256"] is None
