from __future__ import annotations

import json

from cocomelon.prospective_hype_lineage_failure_cli import main


def test_lineage_failure_cli_emits_redacted_campaign_bound_receipt(
    capsys: object,
) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "verify",
            "--reason-code",
            "LINEAGE_APPEND_ONLY_VERIFY_FAILED",
            "--previous-artifact-id",
            "101",
            "--current-artifact-id",
            "202",
        ]
    ) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["stage"] == "verify"
    assert payload["reason_code"] == "LINEAGE_APPEND_ONLY_VERIFY_FAILED"
    assert payload["previous_artifact_id"] == "101"
    assert payload["current_artifact_id"] == "202"
    assert payload["interim_economics_redacted"] is True
    assert len(payload["campaign_id"]) == 64
    assert len(payload["validation_plan_id"]) == 64
    assert len(payload["failure_id"]) == 64


def test_lineage_failure_cli_rejects_unbounded_reason(capsys: object) -> None:
    assert main(
        [
            "--audited-at-ms",
            "100",
            "--stage",
            "verify",
            "--reason-code",
            "not redacted",
        ]
    ) == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)

    assert payload["error_type"] == "ValueError"
