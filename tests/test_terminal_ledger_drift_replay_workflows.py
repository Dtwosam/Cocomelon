from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("workflow_name", "status_file"),
    [
        (
            "prospective-risk-rejected-fast-markout-ledger.yml",
            "risk-rejected-fast-status.md",
        ),
        (
            "prospective-long-trend-carveout-fast-markout-ledger.yml",
            "long-trend-carveout-status.md",
        ),
        (
            "prospective-risk-rejected-stop-path-ledger.yml",
            "risk-rejected-stop-path-status.md",
        ),
    ],
)
def test_blocked_terminal_ledger_replay_preserves_source_lineage(
    workflow_name: str, status_file: str
) -> None:
    source = (Path(".github/workflows") / workflow_name).read_text(
        encoding="utf-8"
    )
    blocked = source.split(
        "      - name: Publish blocked ledger status", 1
    )[1].split("      - name: Fail closed on ledger drift", 1)[0]

    # Main push replays a genuine completed source on the new diagnostics.
    assert "  push:" in source
    assert f'      - ".github/workflows/{workflow_name}"' in source
    assert "  workflow_run:" in source

    # Provenance must survive the fail-closed branch; no new ledger is uploaded.
    assert (
        "PREVIOUS_WORKFLOW_RUN_ID: "
        "${{ steps.previous.outputs.previous_workflow_run_id }}" in blocked
    )
    assert (
        "SOURCE_ARTIFACT_DIGEST: "
        "${{ steps.source.outputs.artifact_digest }}" in blocked
    )
    assert "previous accepted ledger workflow run:" in blocked
    assert "source artifact SHA-256:" in blocked
    assert "f\"- error: `{error}`\"" in blocked
    assert f'cat /tmp/{status_file} >> "$GITHUB_STEP_SUMMARY"' in blocked
    assert "gh api" in blocked
    assert "Fail closed on ledger drift" in source
    assert "      - name: Upload" in source
    assert "LIVE TRADING: DISABLED." in source
