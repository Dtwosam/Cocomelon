from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-dashboard-catchup.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_dashboard_catchup_dispatches_only_when_trusted_source_is_newer() -> None:
    source = _source()
    lowered = source.lower()

    assert "name: Research Dashboard Catch-up Dispatcher" in source
    assert 'cron: "*/5 * * * *"' in source
    assert "workflow_dispatch:" in source
    assert "actions: write" in source
    assert "contents: none" in source
    assert "GITHUB_TOKEN: ${{ github.token }}" in source

    assert "/actions/runs?per_page=100" in source
    assert '.head_branch == "main"' in source
    assert '.status == "completed"' in source
    assert '.path == ".github/workflows/research-campaign-scheduled.yml"' in source
    assert '.path == ".github/workflows/research-v4-registry-sync.yml"' in source
    assert '.path == ".github/workflows/research-dashboard.yml"' in source
    assert '.conclusion == "success" or .conclusion == "failure"' in source
    assert '.conclusion == "success"' in source
    assert '.status != "completed"' in source
    assert "LATEST_SOURCE_COMPLETED_AT" in source
    assert "LATEST_DASHBOARD_COMPLETED_AT" in source
    assert "latest dashboard attempt already follows trusted research state" in source
    assert "research dashboard refresh already active" in source

    dashboard_attempt_query = source.split(
        'LATEST_DASHBOARD_COMPLETED_AT="$(' , 1
    )[1].split(')"\n\n          if [[ -n "$LATEST_DASHBOARD_COMPLETED_AT" ]]', 1)[0]
    assert '.conclusion == "success"' not in dashboard_attempt_query
    assert '.conclusion == "failure"' not in dashboard_attempt_query

    assert "actions/workflows/research-dashboard.yml/dispatches" in source
    assert "--method POST" in source
    assert "-f ref=main" in source

    for forbidden in (
        "actions/checkout",
        "actions/download-artifact",
        "issues: write",
        "research.sqlite3",
        "research-authoritative-registry",
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "private_key",
        "wallet",
        "withdraw",
        "transfer",
        "send_order",
        "live_order",
    ):
        assert forbidden not in lowered
