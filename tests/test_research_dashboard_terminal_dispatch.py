from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_campaign_dispatches_dashboard_from_isolated_terminal_job() -> None:
    source = _source()

    assert "\n  refresh-dashboard:\n" in source
    finalizer_index = source.index("\n  finalize-publish:\n")
    dashboard_index = source.index("\n  refresh-dashboard:\n")
    assert finalizer_index < dashboard_index

    dashboard = source.split("\n  refresh-dashboard:\n", 1)[1]
    header, steps = dashboard.split("\n    steps:\n", 1)

    assert "needs: finalize-publish" in header
    assert "if: ${{ always() }}" in header
    assert "actions: write" in header
    assert "contents: none" in header
    assert "GITHUB_TOKEN: ${{ github.token }}" in steps
    assert "actions/workflows/research-dashboard.yml/dispatches" in steps
    assert "--method POST" in steps
    assert "-f ref=main" in steps

    for forbidden in (
        "actions/checkout",
        "actions/download-artifact",
        "research.sqlite3",
        "research-authoritative-registry",
        "research-capture",
        "candidate-revision",
        "candidate-image",
        "strategy-decisions",
        "net_pnl",
        "posterior_probability",
    ):
        assert forbidden not in dashboard.lower()
