from pathlib import Path


SYNC_WORKFLOW = Path(".github/workflows/research-v4-registry-sync.yml")


def _job(source: str, name: str, next_name: str | None = None) -> str:
    block = source.split(f"\n  {name}:\n", 1)[1]
    if next_name is not None:
        block = block.split(f"\n  {next_name}:\n", 1)[0]
    return block


def test_successful_v4_authority_sync_dispatches_dashboard_from_isolated_job() -> None:
    source = SYNC_WORKFLOW.read_text(encoding="utf-8")
    synchronize = _job(source, "synchronize", "dispatch-dashboard")
    dashboard = _job(source, "dispatch-dashboard")

    assert "actions: write" not in synchronize
    assert "needs: synchronize" in dashboard
    assert "needs.synchronize.result == 'success'" in dashboard
    assert "actions: write" in dashboard
    assert "contents: none" in dashboard
    assert "GH_TOKEN: ${{ github.token }}" in dashboard
    assert "actions/workflows/research-dashboard.yml/dispatches" in dashboard
    assert "--method POST" in dashboard
    assert "-f ref=main" in dashboard
    assert "actions/checkout" not in dashboard
    assert "research.sqlite3" not in dashboard
    assert "v4-mainnet-corpus" not in dashboard
