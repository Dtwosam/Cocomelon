import ast
from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper.yml")

def test_continuous_paper_worker_is_long_running_and_self_chaining() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "group: continuous-mainnet-paper-trader" in source
    assert "cancel-in-progress: false" in source
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
    assert 'run.get("status") == "in_progress"' in source
    assert 'run.get("status") in {"queued", "in_progress", "pending"}' not in source
    assert "Queue exact successor continuous paper worker" in source
    assert "\n  continue:\n" not in source
    upload_at = source.index("- name: Upload durable continuous paper state")
    dispatch_at = source.index(
        "- name: Queue exact successor continuous paper worker"
    )
    assert upload_at < dispatch_at

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
    assert "src/cocomelon/research/account_lifecycle_bridge.py" in source
    assert "src/cocomelon/research/cadence_shadow.py" in source
    assert "src/cocomelon/research/closed_trade_concentration.py" in source
    assert "src/cocomelon/research/closed_trade_friction.py" in source
    assert "src/cocomelon/research/closed_trade_robustness.py" in source
    assert "src/cocomelon/research/closed_trade_stability.py" in source
    assert "src/cocomelon/research/closed_trade_utc_hour.py" in source
    assert "src/cocomelon/research/continuous_paper_trade_paths.py" in source
    assert "src/cocomelon/research/continuous_paper_opening_rank.py" in source
    assert "src/cocomelon/research/continuous_paper_opening_opportunity.py" in source
    assert (
        "src/cocomelon/research/continuous_paper_opening_opportunity_paths.py"
        in source
    )
    assert "src/cocomelon/research/continuous_paper_drawdown.py" in source
    assert "src/cocomelon/research/delayed_entry_execution_shadow.py" in source
    assert "src/cocomelon/research/delayed_entry_contribution_decomposition.py" in source
    assert "src/cocomelon/research/delayed_entry_fill_capacity.py" in source
    assert "src/cocomelon/research/delayed_entry_fill_weighted.py" in source
    assert (
        "src/cocomelon/research/delayed_entry_fixed_schedule_portfolio.py"
        in source
    )
    assert "src/cocomelon/research/delayed_entry_mtm_portfolio.py" in source
    assert "src/cocomelon/research/delayed_entry_portfolio_capacity.py" in source
    assert "src/cocomelon/research/delayed_entry_risk_geometry.py" in source
    assert "src/cocomelon/research/delayed_entry_pair.py" in source
    assert "src/cocomelon/research/delayed_entry_pair_fill_weighted.py" in source
    assert "src/cocomelon/research/adaptive_delay_selector.py" in source
    assert "src/cocomelon/research/fill_aware_delay_selector.py" in source
    assert "src/cocomelon/research/delay_selector_comparison.py" in source
    assert "src/cocomelon/research/delayed_entry_same_exit.py" in source
    assert "src/cocomelon/research/entry_decision_age.py" in source
    assert "src/cocomelon/research/entry_markout.py" in source
    assert "src/cocomelon/research/entry_markout_predictiveness.py" in source
    assert "src/cocomelon/research/entry_markout_readiness.py" in source
    assert "src/cocomelon/research/excursion_timing.py" in source
    assert "src/cocomelon/research/entry_mid_markout_shadow.py" in source
    assert "src/cocomelon/research/entry_mid_markout_readiness.py" in source
    assert "src/cocomelon/research/profit_lock_counterfactual.py" in source
    assert "src/cocomelon/research/profit_lock_execution_readiness.py" in source
    assert "src/cocomelon/research/profit_lock_execution_shadow.py" in source
    assert "src/cocomelon/research/profit_lock_readiness.py" in source
    assert "src/cocomelon/research/prospective_delayed_price_confirmation.py" in source
    assert "src/cocomelon/research/prospective_entry_filter.py" in source
    assert "src/cocomelon/research/prospective_top10_rank_filter.py" in source
    assert "src/cocomelon/strategies" in source
    assert "touch /tmp/continuous-paper-upgrade-requested" in source
    assert "new continuous-paper runtime code detected on main" in source


def test_continuous_paper_bootstrap_watches_runtime_dependencies() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert '"src/cocomelon/continuous_paper.py"' in source
    assert '"src/cocomelon/execution/**"' in source
    assert '"src/cocomelon/risk/**"' in source
    assert '"src/cocomelon/research/account_lifecycle_bridge.py"' in source
    assert '"src/cocomelon/research/cadence_shadow.py"' in source
    assert '"src/cocomelon/research/closed_trade_concentration.py"' in source
    assert '"src/cocomelon/research/closed_trade_friction.py"' in source
    assert '"src/cocomelon/research/closed_trade_robustness.py"' in source
    assert '"src/cocomelon/research/closed_trade_stability.py"' in source
    assert '"src/cocomelon/research/closed_trade_utc_hour.py"' in source
    assert '"src/cocomelon/research/continuous_paper_trade_paths.py"' in source
    assert '"src/cocomelon/research/continuous_paper_opening_rank.py"' in source
    assert '"src/cocomelon/research/continuous_paper_opening_opportunity.py"' in source
    assert (
        '"src/cocomelon/research/continuous_paper_opening_opportunity_paths.py"'
        in source
    )
    assert '"src/cocomelon/research/continuous_paper_drawdown.py"' in source
    assert '"src/cocomelon/research/delayed_entry_execution_shadow.py"' in source
    assert '"src/cocomelon/research/delayed_entry_contribution_decomposition.py"' in source
    assert '"src/cocomelon/research/delayed_entry_fill_capacity.py"' in source
    assert '"src/cocomelon/research/delayed_entry_fill_weighted.py"' in source
    assert (
        '"src/cocomelon/research/delayed_entry_fixed_schedule_portfolio.py"'
        in source
    )
    assert '"src/cocomelon/research/delayed_entry_mtm_portfolio.py"' in source
    assert '"src/cocomelon/research/delayed_entry_portfolio_capacity.py"' in source
    assert '"src/cocomelon/research/delayed_entry_risk_geometry.py"' in source
    assert '"src/cocomelon/research/delayed_entry_pair.py"' in source
    assert '"src/cocomelon/research/delayed_entry_pair_fill_weighted.py"' in source
    assert '"src/cocomelon/research/adaptive_delay_selector.py"' in source
    assert '"src/cocomelon/research/fill_aware_delay_selector.py"' in source
    assert '"src/cocomelon/research/delay_selector_comparison.py"' in source
    assert '"src/cocomelon/research/delayed_entry_same_exit.py"' in source
    assert '"src/cocomelon/research/entry_decision_age.py"' in source
    assert '"src/cocomelon/research/entry_markout.py"' in source
    assert '"src/cocomelon/research/entry_markout_predictiveness.py"' in source
    assert '"src/cocomelon/research/entry_markout_readiness.py"' in source
    assert '"src/cocomelon/research/excursion_timing.py"' in source
    assert '"src/cocomelon/research/entry_mid_markout_shadow.py"' in source
    assert '"src/cocomelon/research/entry_mid_markout_readiness.py"' in source
    assert '"src/cocomelon/research/opening_fill_liquidity.py"' in source
    assert '"src/cocomelon/research/profit_lock_counterfactual.py"' in source
    assert '"src/cocomelon/research/profit_lock_execution_readiness.py"' in source
    assert '"src/cocomelon/research/profit_lock_execution_shadow.py"' in source
    assert '"src/cocomelon/research/profit_lock_readiness.py"' in source
    assert '"src/cocomelon/research/prospective_delayed_price_confirmation.py"' in source
    assert '"src/cocomelon/research/prospective_entry_filter.py"' in source
    assert '"src/cocomelon/research/prospective_top10_rank_filter.py"' in source
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
    assert "opening scanner-rank records:" in source
    assert "opening_rank_state_digest" in source
    assert "opening_rank_capture_error" in source
    assert "opening fill-liquidity records:" in source
    assert "opening_fill_liquidity_state_digest" in source
    assert "opening_fill_liquidity_capture_error" in source
    assert "opening_opportunity_state_digest" in source
    assert "opening_opportunity_capture_error" in source
    assert "opening_opportunity_path_count" in source
    assert "opening_opportunity_path_complete_count" in source
    assert "opening_opportunity_path_state_digest" in source
    assert "opening_opportunity_path_capture_error" in source
    assert "closed trade paths:" in source
    assert "staged open trade paths:" in source
    assert "trade_path_open_count" in source
    assert "trade_path_state_digest" in source
    assert "trade_path_capture_error" in source


def _research_runtime_dependencies() -> tuple[str, ...]:
    prefix = "cocomelon.research."
    pending = [Path("src/cocomelon/continuous_paper.py")]
    seen_files: set[Path] = set()
    dependencies: set[str] = set()

    while pending:
        source_path = pending.pop()
        if source_path in seen_files:
            continue
        seen_files.add(source_path)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if not module.startswith(prefix):
                continue
            child = Path(
                "src/cocomelon/research/"
                + module.removeprefix(prefix).replace(".", "/")
                + ".py"
            )
            if not child.exists():
                continue
            normalized = child.as_posix()
            if normalized in dependencies:
                continue
            dependencies.add(normalized)
            pending.append(child)

    return tuple(sorted(dependencies))


def test_continuous_paper_watches_recursive_research_dependencies() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    missing = [
        dependency
        for dependency in _research_runtime_dependencies()
        if source.count(dependency) < 2
    ]
    assert missing == []
