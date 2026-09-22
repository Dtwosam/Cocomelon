from __future__ import annotations

import json

from cocomelon.prospective_hype_blind_monitor_failure_cli import main


def test_failure_receipt_cli_emits_redacted_campaign_bound_receipt(
    capsys: object,
) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "discovery",
            "--reason-code",
            "HEALTH_ARTIFACT_MISSING",
            "--health-artifact-id",
            "none",
        ]
    ) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["stage"] == "discovery"
    assert payload["reason_code"] == "HEALTH_ARTIFACT_MISSING"
    assert payload["health_artifact_id"] is None
    assert payload["interim_economics_redacted"] is True
    assert len(payload["campaign_id"]) == 64
    assert len(payload["validation_plan_id"]) == 64
    assert len(payload["failure_id"]) == 64


def test_failure_receipt_cli_rejects_unbounded_reason(capsys: object) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "build",
            "--reason-code",
            "not redacted",
        ]
    ) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert payload["error_type"] == "ValueError"
