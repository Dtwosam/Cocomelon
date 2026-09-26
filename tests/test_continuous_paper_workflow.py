from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper.yml")

def test_continuous_paper_worker_is_long_running_and_self_chaining() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'duration-seconds 19800' in source
    assert 'selection-refresh-seconds 300' in source
    assert 'continuous-paper-state-${{ github.run_id }}-${{ github.run_attempt }}' in source
    assert "gh workflow run continuous-paper.yml" in source
    assert 'source_run_id' in source
    assert '7,37 * * * *' in source
    assert "push:" in source
    assert "issues: write" in source
    assert 'LIVE_STATUS_ISSUE: "469"' in source
    assert "PREDECESSOR_RUN_ID:" in source
    assert '--title "Continuous Paper Trader — Live Status"' in source
    assert 'gh issue edit "$LIVE_STATUS_ISSUE"' in source
    assert "COCOMELON_PAPER_HEARTBEAT" in source
    assert '".github/workflows/continuous-paper.yml"' in source
    assert 'EVENT_NAME: ${{ github.event_name }}' in source
    assert "SOURCE_RUN_ID" in source
    assert 'if [ "$EVENT_NAME" = "workflow_dispatch" ] && [ -n "$SOURCE_RUN_ID" ]' in source

def test_continuous_paper_worker_is_hard_locked_to_paper() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()
    assert "cocomelon_execution_mode: paper" in source
    runtime = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8").lower()
    assert "live_orders: bool = false" in runtime
    assert '"live_orders": false' in runtime
    assert "private_key" not in source
    assert "withdraw" not in source
    assert "transfer" not in source


def test_continuous_paper_worker_gracefully_rotates_on_runtime_changes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "--stop-file /tmp/continuous-paper-upgrade-requested" in source
    assert 'git fetch --quiet --depth=1 origin main' in source
    assert 'git diff --name-only "$GITHUB_SHA" FETCH_HEAD --' in source
    assert "src/cocomelon/continuous_paper.py" in source
    assert "src/cocomelon/risk" in source
    assert "src/cocomelon/research/cadence_shadow.py" in source
    assert "src/cocomelon/research/continuous_paper_trade_paths.py" in source
    assert "src/cocomelon/strategies" in source
    assert "touch /tmp/continuous-paper-upgrade-requested" in source
    assert "new continuous-paper runtime code detected on main" in source


def test_continuous_paper_bootstrap_watches_runtime_dependencies() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert '"src/cocomelon/continuous_paper.py"' in source
    assert '"src/cocomelon/execution/**"' in source
    assert '"src/cocomelon/risk/**"' in source
    assert '"src/cocomelon/research/cadence_shadow.py"' in source
    assert '"src/cocomelon/research/continuous_paper_trade_paths.py"' in source
    assert '"src/cocomelon/strategies/**"' in source
    assert '"src/cocomelon/hyperliquid/**"' in source
    assert '"scripts/render_continuous_paper_live_status.py"' in source


def test_continuous_paper_worker_binds_openings_to_exact_worker_identity() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert '--worker-run-id "$GITHUB_RUN_ID"' in source
    assert '--worker-run-attempt "$GITHUB_RUN_ATTEMPT"' in source
    assert '--worker-head-sha "$GITHUB_SHA"' in source
    assert "opening lineage records:" in source
    assert "opening_lineage_state_digest" in source
    assert "closed trade paths:" in source
    assert "trade_path_state_digest" in source
    assert "trade_path_capture_error" in source
