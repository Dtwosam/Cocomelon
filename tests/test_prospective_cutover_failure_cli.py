from __future__ import annotations

import json

from cocomelon.prospective_hype_cutover_failure_cli import main


def test_cutover_failure_cli_emits_redacted_campaign_bound_receipt(
    capsys: object,
) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "monitor",
            "--reason-code",
            "CUTOVER_MONITOR_RECEIPT_MISSING",
            "--monitor-artifact-id",
            "101",
            "--state-artifact-id",
            "none",
        ]
    ) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["stage"] == "monitor"
    assert payload["reason_code"] == "CUTOVER_MONITOR_RECEIPT_MISSING"
    assert payload["monitor_artifact_id"] == "101"
    assert payload["state_artifact_id"] is None
    assert payload["interim_economics_redacted"] is True
    assert len(payload["campaign_id"]) == 64
    assert len(payload["validation_plan_id"]) == 64
    assert len(payload["failure_id"]) == 64


def test_cutover_failure_cli_rejects_unbounded_reason(capsys: object) -> None:
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
