from __future__ import annotations

import json

from cocomelon.prospective_hype_state_readiness_failure_cli import main


def test_state_readiness_failure_cli_emits_redacted_bound_receipt(
    capsys: object,
) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "verify",
            "--reason-code",
            "STATE_READINESS_VERIFY_FAILED",
            "--state-artifact-id",
            "123",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["stage"] == "verify"
    assert payload["reason_code"] == "STATE_READINESS_VERIFY_FAILED"
    assert payload["state_artifact_id"] == "123"
    assert payload["interim_economics_redacted"] is True
    assert len(payload["campaign_id"]) == 64
    assert len(payload["candidate_spec_id"]) == 64
    assert len(payload["validation_plan_id"]) == 64
    assert len(payload["failure_id"]) == 64


def test_state_readiness_failure_cli_accepts_missing_artifact_id(
    capsys: object,
) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "discovery",
            "--reason-code",
            "STATE_ARTIFACT_DISCOVERY_FAILED",
            "--state-artifact-id",
            "none",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state_artifact_id"] is None
