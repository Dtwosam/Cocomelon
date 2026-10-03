import ast
from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper.yml")

def test_continuous_paper_worker_is_long_running_and_self_chaining() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "group: continuous-mainnet-paper-trader-"
        "${{ inputs.source_run_id || 'guarded' }}"
        in source
    )
    assert "cancel-in-progress: false" in source
    assert 'duration-seconds 19800' in source
    assert 'selection-refresh-seconds 300' in source
    assert 'continuous-paper-state-${{ github.run_id }}-${{ github.run_attempt }}' in source
    assert (
        'continuous-paper-cadence-shadow-${{ github.run_id }}-'
        '${{ github.run_attempt }}'
        in source
    )
    assert (
        "path: continuous-paper-state/cadence-shadow-state.json"
        in source
    )
    assert (
        "hashFiles('continuous-paper-state/cadence-shadow-state.json')"
        in source
    )
    assert (
        'continuous-paper-learning-features-${{ github.run_id }}-'
        '${{ github.run_attempt }}'
    ) in source
    assert "path: continuous-paper-state/learning-features" in source
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
    assert (
        'run.get("status") in {"queued", "pending", "in_progress"}'
        in source
    )
    assert "Queue exact successor from fast resume" in source
    assert "Queue fallback exact successor continuous paper worker" in source
    assert "\n  continue:\n" not in source
    fast_upload_at = source.index(
        "- name: Upload fast continuous paper resume state"
    )
    fast_dispatch_at = source.index(
        "- name: Queue exact successor from fast resume"
    )
    fast_cleanup_at = source.index(
        "- name: Remove local fast resume archive"
    )
    durable_upload_at = source.index(
        "- name: Upload durable continuous paper state"
    )
    fallback_dispatch_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    assert fast_upload_at < fast_dispatch_at < fast_cleanup_at
    assert fast_cleanup_at < durable_upload_at < fallback_dispatch_at

def test_continuous_paper_state_handoff_prefers_fast_resume_with_fallback() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "- name: Measure durable continuous paper state" in source
    assert "scripts/summarize_continuous_paper_state.py" in source
    assert "--json-out /tmp/continuous-paper-state-size.json" in source
    assert "--markdown-out /tmp/continuous-paper-state-size.md" in source
    assert 'tee -a "$GITHUB_STEP_SUMMARY"' in source
    assert "- name: Pack fast continuous paper resume state" in source
    assert "continuous-paper-resume.tar.zst" in source
    assert "zstd -T0 -3 --no-progress" in source
    assert "compression-level: 0" in source
    assert "retention-days: 14" in source
    assert "- name: Pack durable continuous paper state" in source
    assert 'tar -cf continuous-paper-state.tar -C "$STATE_ROOT" .' in source
    assert "path: continuous-paper-state.tar" in source
    assert "compression-level: 6" in source
    assert source.count(
        "bash scripts/restore_continuous_paper_state.sh"
    ) == 4
    assert "RESUME_ARTIFACT_NAME" in source
    assert "STATE_ARTIFACT_NAME" in source
    assert "fast resume restore failed; waiting for exact durable fallback" in source
    assert "for poll in $(seq 1 40)" in source
    assert "durable fallback did not appear" in source
    assert "SOURCE_HEAD_SHA" in source
    assert "ARTIFACT_HEAD_SHA" in source
    assert 'status = run.get("status")' in source
    assert (
        'run.get("conclusion") not in {"success", "failure"}'
        in source
    )
    assert (
        "completed predecessor run must be success or failure"
        in source
    )
    assert (
        'run.get("conclusion") in {"success", "failure"}'
        in source
    )
    assert source.count("timeout-minutes: 30") >= 2

    measure_at = source.index(
        "- name: Measure durable continuous paper state"
    )
    fast_pack_at = source.index(
        "- name: Pack fast continuous paper resume state"
    )
    fast_upload_at = source.index(
        "- name: Upload fast continuous paper resume state"
    )
    fast_dispatch_at = source.index(
        "- name: Queue exact successor from fast resume"
    )
    fast_cleanup_at = source.index(
        "- name: Remove local fast resume archive"
    )
    durable_pack_at = source.index(
        "- name: Pack durable continuous paper state"
    )
    durable_upload_at = source.index(
        "- name: Upload durable continuous paper state"
    )
    fallback_dispatch_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    assert (
        measure_at
        < fast_pack_at
        < fast_upload_at
        < fast_dispatch_at
        < fast_cleanup_at
        < durable_pack_at
        < durable_upload_at
        < fallback_dispatch_at
    )
    assert "run: rm -f continuous-paper-resume.tar.zst" in source
    assert durable_upload_at < fallback_dispatch_at


def test_continuous_paper_failure_still_dispatches_exact_state() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    fast_at = source.index(
        "- name: Queue exact successor from fast resume"
    )
    cleanup_at = source.index(
        "- name: Remove local fast resume archive",
        fast_at,
    )
    fast_block = source[fast_at:cleanup_at]
    assert (
        "if: ${{ always() && steps.guard.outputs.skip != 'true' "
        "&& steps.fast_resume_upload.outcome == 'success' }}"
        in fast_block
    )

    durable_at = source.index(
        "- name: Upload durable continuous paper state"
    )
    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker",
        durable_at,
    )
    assert "id: durable_state_upload" in source[
        durable_at:fallback_at
    ]
    fallback_block = source[fallback_at:]
    assert (
        "if: ${{ always() && steps.guard.outputs.skip != 'true' "
        "&& steps.fast_resume_dispatch.outcome != 'success' "
        "&& steps.durable_state_upload.outcome == 'success' }}"
        in fallback_block
    )
    assert (
        'run.get("conclusion") in {"success", "failure"}'
        in source
    )


def test_continuous_paper_upgrade_watchdog_does_not_require_heartbeat() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    watchdog_at = source.index("watch_for_newer_runtime_run()")
    trader_at = source.index("cocomelon-continuous-paper \\")
    assert watchdog_at < trader_at
    assert 'sleep 60' in source
    assert 'run.get("event") == "push"' in source
    assert 'run.get("head_branch") == "main"' in source
    watchdog_source = source[watchdog_at:trader_at]
    assert 'run.get("head_sha") != os.environ["GITHUB_SHA"]' in watchdog_source
    assert (
        'run.get("status") in {"queued", "pending", "in_progress"}'
        not in watchdog_source
    )
    assert 'int(run.get("run_number", 0)) > current_number' in watchdog_source
    assert "holding runtime push rendezvous for active worker handoff" in source
    assert "sleep 75" in source
    assert "requesting graceful handoff independently of heartbeat" in source
    assert "upgrade_watch_pid=$!" in source
    assert "trap 'kill \"$upgrade_watch_pid\"" in source


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
    assert "scripts/summarize_continuous_paper_state.py" in source
    assert "scripts/restore_continuous_paper_state.sh" in source
    assert "scripts/stream_zip_member.py" in source
    assert "src/cocomelon/risk" in source
    assert "src/cocomelon/research/account_lifecycle_bridge.py" in source
    assert "src/cocomelon/research/cadence_shadow.py" in source
    assert "src/cocomelon/research/cadence_opportunity_learning.py" in source
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
    assert (
        "src/cocomelon/research/continuous_paper_opening_opportunity_exit_books.py"
        in source
    )
    assert (
        "src/cocomelon/research/continuous_paper_replacement_funding.py"
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
    assert "src/cocomelon/research/prospective_trade_quality.py" in source
    assert "src/cocomelon/research/prospective_side_conditioned_delay.py" in source
    assert (
        "src/cocomelon/research/prospective_capacity_reflow_forward_markout.py"
        in source
    )
    assert (
        "src/cocomelon/research/prospective_capacity_reflow_forward_excursion.py"
        in source
    )
    assert (
        "src/cocomelon/research/prospective_capacity_reflow_exit_fill.py"
        in source
    )
    assert (
        "src/cocomelon/research/prospective_capacity_reflow_realized_pnl.py"
        in source
    )
    assert (
        "src/cocomelon/research/prospective_replacement_exit_policy.py"
        in source
    )
    assert (
        "src/cocomelon/research/prospective_replacement_exit_robustness.py"
        in source
    )
    assert (
        "src/cocomelon/research/prospective_replacement_exit_readiness.py"
        in source
    )
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
    assert '"src/cocomelon/research/cadence_opportunity_learning.py"' in source
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
    assert (
        '"src/cocomelon/research/continuous_paper_opening_opportunity_exit_books.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/continuous_paper_replacement_funding.py"'
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
    assert '"src/cocomelon/research/prospective_trade_quality.py"' in source
    assert '"src/cocomelon/research/prospective_side_conditioned_delay.py"' in source
    assert '\\n      - "src/cocomelon/research/prospective_trade_quality.py"' not in source
    assert (
        '"src/cocomelon/research/prospective_capacity_reflow_forward_markout.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/prospective_capacity_reflow_forward_excursion.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/prospective_full_stack_exit_capacity_reflow.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/prospective_capacity_reflow_exit_fill.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/prospective_capacity_reflow_realized_pnl.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/prospective_replacement_exit_policy.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/prospective_replacement_exit_robustness.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/prospective_replacement_exit_readiness.py"'
        in source
    )
    assert '"src/cocomelon/strategies/**"' in source
    assert '"src/cocomelon/hyperliquid/**"' in source
    assert '"scripts/render_continuous_paper_live_status.py"' in source
    assert '"scripts/summarize_continuous_paper_state.py"' in source
    assert '"scripts/restore_continuous_paper_state.sh"' in source
    assert '"scripts/stream_zip_member.py"' in source


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
    assert "opening_opportunity_exit_book_registration_count" in source
    assert "opening_opportunity_exit_book_capture_count" in source
    assert "opening_opportunity_exit_book_pending_count" in source
    assert "opening_opportunity_exit_book_missed_count" in source
    assert "opening_opportunity_exit_book_state_digest" in source
    assert "opening_opportunity_exit_book_capture_error" in source
    assert "replacement_funding_registration_count" in source
    assert "replacement_funding_required_boundary_count" in source
    assert "replacement_funding_oracle_candidate_count" in source
    assert "replacement_funding_capture_count" in source
    assert "replacement_funding_pending_count" in source
    assert "replacement_funding_missed_count" in source
    assert "replacement_funding_state_digest" in source
    assert "replacement_funding_capture_error" in source
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


def test_continuous_paper_exports_full_stack_entry_exit_summary() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "prospective-full-stack-entry-exit-summary.json"
        in source
    )
    assert (
        "continuous-paper-full-stack-entry-exit-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
        in source
    )
    assert "Render full-stack entry-exit research summary" in source
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    pack_at = source.index(
        "- name: Pack durable continuous paper state"
    )
    assert compact_at < pack_at


def test_continuous_paper_exports_full_stack_capacity_reflow_summary() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "prospective-full-stack-capacity-reflow-summary.json"
        in source
    )
    assert (
        "continuous-paper-full-stack-capacity-reflow-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
        in source
    )
    assert "Render full-stack capacity-reflow research summary" in source
    assert "exact realized option-horizons / available" in source
    assert "cross-horizon economics aggregated: false" in source
    assert "portfolio counterfactual: false" in source
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    pack_at = source.index(
        "- name: Pack durable continuous paper state"
    )
    assert compact_at < pack_at


def test_continuous_paper_exports_full_stack_exit_capacity_reflow_summary() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "prospective-full-stack-exit-capacity-reflow-summary.json"
        in source
    )
    assert (
        "continuous-paper-full-stack-exit-capacity-reflow-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
        in source
    )
    assert "Render full-stack exit-capacity-reflow research summary" in source
    assert "exact early-released positions / integrity clean" in source
    assert "cross-horizon economics aggregated: false" in source
    assert "portfolio counterfactual: false" in source
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    pack_at = source.index(
        "- name: Pack durable continuous paper state"
    )
    assert compact_at < pack_at


def test_full_stack_fast_markout_is_exported_and_runtime_watched() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        '"src/cocomelon/research/prospective_full_stack_forward_markout.py"'
        in source
    )
    assert (
        "src/cocomelon/research/prospective_full_stack_forward_markout.py"
        in source.split("changed_runtime=", 1)[1]
    )
    assert (
        "continuous-paper-state/"
        "prospective-full-stack-forward-markout-summary.json"
        in source
    )
    assert "Upload full-stack fast-markout research summary" in source
    assert "Render full-stack fast-markout research summary" in source
    assert "RESEARCH ONLY / NO EXECUTION / NO READINESS" in source
    assert "risk-rejected opportunities / evaluated / stack admit" in source
    assert "risk-rejected reasons" in source
    assert "risk-rejected {minutes}m stack admit/block mean" in source

def test_long_trend_execution_shadow_source_is_compact_and_watched() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    module = (
        "src/cocomelon/research/"
        "prospective_long_trend_carveout_execution_shadow_source.py"
    )
    artifact = (
        "continuous-paper-state/"
        "prospective-long-trend-execution-shadow-source.json"
    )
    assert module in source
    assert module in source.split("changed_runtime=", 1)[1]
    assert artifact in source
    compact = source.split(
        "- name: Upload compact continuous learning source",
        1,
    )[1].split("- name:", 1)[0]
    assert artifact in compact


