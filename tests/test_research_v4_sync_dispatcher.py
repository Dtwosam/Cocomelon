from pathlib import Path

DISPATCHER = Path(".github/workflows/research-v4-sync-dispatcher.yml")


def test_v4_completion_dispatches_trusted_authority_sync_without_data_access() -> None:
    source = DISPATCHER.read_text(encoding="utf-8")
    lowered = source.lower()

    assert "name: Research V4 Authority Sync Dispatcher" in source
    assert "workflow_run:" in source
    assert "Scheduled Genuine Mainnet Evidence Campaign V4" in source
    assert "types: [completed]" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event.workflow_run.event == 'schedule'" in source
    assert "github.event.workflow_run.conclusion" not in source

    assert "contents: none" in source
    assert "actions: write" in source
    assert "actions/checkout" not in source
    assert "research.sqlite3" not in source
    assert "v4-mainnet-corpus" not in source
    assert "record-mainnet-evidence" not in source

    assert "research-v4-registry-sync.yml/runs?per_page=100" in source
    assert 'select(.status != "completed")' in source
    assert "V4 authority sync already active; dispatch skipped" in source
    assert "research-v4-registry-sync.yml/dispatches" in source
    assert "--method POST" in source
    assert "-f ref=main" in source

    for forbidden in (
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "profit_factor",
        "final_equity",
    ):
        assert forbidden not in lowered
