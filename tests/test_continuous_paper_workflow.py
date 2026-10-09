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
    assert "  schedule:" not in source
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
    assert 'if [ "$EVENT_NAME" = "workflow_dispatch" ] && [ -n "$SOURCE_RUN_ID" ]' not in source
    assert 'status in {"queued", "pending"}' in source
    assert 'status != "in_progress"' in source
    assert '"Run continuous paper trader"' in source
    assert 'trader_status in {"queued", "pending", "in_progress"}' in source
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
    deferred_markout_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    durable_upload_at = source.index(
        "- name: Upload durable continuous paper state"
    )
    fallback_dispatch_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    assert fast_upload_at < fast_dispatch_at < fast_cleanup_at
    assert fast_cleanup_at < durable_upload_at < fallback_dispatch_at
    assert fallback_dispatch_at < deferred_markout_at

def test_independent_scheduled_recovery_keeps_active_trader_guard() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    watchdog = Path(
        ".github/workflows/independent-paper-recovery.yml"
    ).read_text(encoding="utf-8")
    assert "  schedule:" not in source
    assert '- cron: "3,13,23,33,43,53 * * * *"' in watchdog
    assert "group: independent-paper-rescue" in watchdog
    assert "cancel-in-progress: false" in source
    guard_at = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run is already active"
    )
    checkout_at = source.index("- uses: actions/checkout@v7", guard_at)
    guard = source[guard_at:checkout_at]
    assert 'echo "skip=true" >> "$GITHUB_OUTPUT"' in guard
    assert 'trader_status in {"queued", "pending", "in_progress"}' in guard
    assert 'step.get("conclusion") == "skipped"' in guard
    assert "if skipped_checkout:" in guard
    assert "sleep 75" not in guard


def test_exact_successor_dispatch_still_checks_for_other_active_traders() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_at = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run is already active"
    )
    checkout_at = source.index("- uses: actions/checkout@v7", guard_at)
    guard = source[guard_at:checkout_at]

    assert 'EVENT_NAME: ${{ github.event_name }}' in guard
    assert 'SOURCE_RUN_ID: ${{ inputs.source_run_id || \'\' }}' in guard
    assert (
        'if [ "$EVENT_NAME" = "workflow_dispatch" ] && '
        '[ -n "$SOURCE_RUN_ID" ]'
        not in guard
    )
    assert "continuous-paper.yml/runs?per_page=100" in guard
    assert 'trader_status in {"queued", "pending", "in_progress"}' in guard
    assert 'echo "skip=true" >> "$GITHUB_OUTPUT"' in guard


def test_guard_ignores_older_queued_run_from_stale_head() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_at = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run is already active"
    )
    checkout_at = source.index("- uses: actions/checkout@v7", guard_at)
    guard = source[guard_at:checkout_at]

    assert 'current_head = os.environ["GITHUB_SHA"]' in guard
    assert "run_id < current" in guard
    assert 'run.get("head_sha") != current_head' in guard
    assert "ignoring stale queued/pending" in guard
    assert "continue" in guard


def test_exact_successor_ignores_queued_speculative_push_or_schedule() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_at = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run is already active"
    )
    checkout_at = source.index("- uses: actions/checkout@v7", guard_at)
    guard = source[guard_at:checkout_at]
    pending_start = guard.index('if status in {"queued", "pending"}:')
    pending_end = guard.index('if status != "in_progress":', pending_start)
    pending = guard[pending_start:pending_end]

    # At handoff a new push run can be pending behind an old worker's
    # research tail even though it has never started trading.
    assert 'os.environ.get("SOURCE_RUN_ID")' in pending
    assert 'run.get("event") in {"push", "schedule"}' in pending
    assert "continue" in pending
    assert pending.index('run.get("event") in {"push", "schedule"}') < pending.index(
        "run_id < current"
    )
    # Only a real exact successor has SOURCE_RUN_ID. Ordinary watchdogs
    # must still guard all queued work, while truly active traders remain
    # guarded independently in the in_progress branch.
    assert 'trader_status in {"queued", "pending", "in_progress"}' in guard
    assert 'step.get("conclusion") == "skipped"' in guard


def test_guard_ignores_post_handoff_research_tails() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_at = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run is already active"
    )
    checkout_at = source.index("- uses: actions/checkout@v7", guard_at)
    guard = source[guard_at:checkout_at]

    assert "actions/runs/{run_id}/jobs?per_page=100" in guard
    assert 'job.get("name") == "paper"' in guard
    assert '"Run continuous paper trader"' in guard
    assert 'trader_status = steps.get("Run continuous paper trader")' in guard
    assert 'trader_status in {"queued", "pending", "in_progress"}' in guard
    assert "Deferred research alone never blocks an exact successor" in guard
    assert 'trader_status == "completed"' in guard
    assert 'and not os.environ.get("SOURCE_RUN_ID")' in guard
    assert "handoff_pending or handoff_dispatched" in guard
    assert "Queue exact successor from fast resume" in guard
    assert "Queue fallback exact successor continuous paper worker" in guard


def test_successor_dispatch_requires_visible_exact_receipt() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "run-name: Continuous Paper · "
        "${{ inputs.source_run_id || github.run_id }}"
        in source
    )

    fast_at = source.index("- name: Queue exact successor from fast resume")
    cleanup_at = source.index(
        "- name: Remove local fast resume archive",
        fast_at,
    )
    fast = source[fast_at:cleanup_at]
    assert 'expected_title="Continuous Paper · $GITHUB_RUN_ID"' in fast
    assert "event=workflow_dispatch&per_page=100" in fast
    assert 'run.get("display_title") == expected' in fast
    assert (
        'run.get("path") == ".github/workflows/continuous-paper.yml"'
        in fast
    )
    assert 'run.get("head_branch") == "main"' in fast
    assert (
        '(run.get("head_repository") or {}).get("full_name")'
        in fast
    )
    assert '== os.environ["GITHUB_REPOSITORY"]' in fast
    assert (
        'run.get("name") == "Continuous Mainnet Paper Trader"'
        not in fast
    )
    assert "for poll in $(seq 1 20)" in fast
    assert "exact successor dispatch did not materialize" in fast
    assert 'echo "successor_run_id=$successor_run_id"' in fast

    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    deferred_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff",
        fallback_at,
    )
    fallback = source[fallback_at:deferred_at]
    assert 'expected_title="Continuous Paper · $GITHUB_RUN_ID"' in fallback
    assert "event=workflow_dispatch&per_page=100" in fallback
    assert 'run.get("display_title") == expected' in fallback
    assert (
        'run.get("path") == ".github/workflows/continuous-paper.yml"'
        in fallback
    )
    assert 'run.get("head_branch") == "main"' in fallback
    assert (
        '(run.get("head_repository") or {}).get("full_name")'
        in fallback
    )
    assert '== os.environ["GITHUB_REPOSITORY"]' in fallback
    assert (
        'run.get("name") == "Continuous Mainnet Paper Trader"'
        not in fallback
    )
    assert "for poll in $(seq 1 20)" in fallback
    assert "fallback exact successor dispatch did not materialize" in fallback
    assert 'echo "successor_run_id=$successor_run_id"' in fallback


def test_continuous_paper_state_handoff_prefers_fast_resume_with_fallback() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "- name: Measure durable continuous paper state" in source
    assert "scripts/summarize_continuous_paper_state.py" in source
    assert "--json-out /tmp/continuous-paper-state-size.json" in source
    assert "--markdown-out /tmp/continuous-paper-state-size.md" in source
    assert 'tee -a "$GITHUB_STEP_SUMMARY"' in source
    assert "- name: Pack fast continuous paper resume state" in source
    assert "- name: Export compact continuous decision facts" in source
    assert "id: decision_fact_export" in source
    assert "cocomelon-continuous-paper-decision-export" in source
    assert "--facts \"$STATE_ROOT/facts.sqlite3\"" in source
    assert "--output-dir \"$STATE_ROOT/learning-decisions\"" in source
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
    deferred_markout_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    decision_export_at = source.index(
        "- name: Export compact continuous decision facts"
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
        < decision_export_at
        < durable_pack_at
        < durable_upload_at
        < fallback_dispatch_at
        < deferred_markout_at
    )
    assert "run: rm -f continuous-paper-resume.tar.zst" in source
    first_terminal_research_upload_at = source.index(
        "- name: Upload cadence shadow research state"
    )
    assert durable_upload_at < first_terminal_research_upload_at
    assert durable_upload_at < fallback_dispatch_at
    research_gate_at = source.index(
        "- name: Fail closed on upgrade handoff source"
    )
    comparison_dispatch_at = source.index(
        "- name: Queue exact LONG trend horizon comparison"
    )
    assert (
        fallback_dispatch_at
        < deferred_markout_at
        < research_gate_at
        < comparison_dispatch_at
    )
    assert comparison_dispatch_at < first_terminal_research_upload_at


def test_upgrade_handoff_rebuilds_full_stack_markouts_after_successor_dispatch() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        '"src/cocomelon/research/deferred_full_stack_forward_markout.py"'
        in source
    )
    assert (
        '"scripts/rebuild_deferred_full_stack_forward_markout.py"'
        in source
    )
    changed_runtime = source.split("changed_runtime=", 1)[1]
    assert (
        "src/cocomelon/research/deferred_full_stack_forward_markout.py"
        in changed_runtime
    )
    assert (
        "scripts/rebuild_deferred_full_stack_forward_markout.py"
        in changed_runtime
    )
    assert "Rebuild deferred full-stack markouts after handoff" in source
    assert "id: fallback_resume_dispatch" in source
    assert "id: deferred_full_stack_markout_rebuild" in source
    assert (
        "steps.fast_resume_dispatch.outcome == 'success' || "
        "steps.fallback_resume_dispatch.outcome == 'success'"
        in source
    )
    assert "continue-on-error: true" in source
    assert 'if [ "$exit_reason" != "upgrade_requested" ]; then' in source
    assert (
        "python scripts/rebuild_deferred_full_stack_forward_markout.py"
        in source
    )
    assert "successor already dispatched: true" in source
    assert "RESEARCH ONLY / NO EXECUTION / NO READINESS" in source

    dispatch_at = source.index(
        "- name: Queue exact successor from fast resume"
    )
    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    rebuild_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    assert dispatch_at < fallback_at < rebuild_at < compact_at


def test_upgrade_handoff_rebuilds_capacity_economics_after_successor_dispatch() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        '"src/cocomelon/research/deferred_full_stack_capacity_reflow.py"'
        in source
    )
    assert (
        '"scripts/rebuild_deferred_full_stack_capacity_reflow.py"'
        in source
    )
    changed_runtime = source.split("changed_runtime=", 1)[1]
    assert (
        "src/cocomelon/research/deferred_full_stack_capacity_reflow.py"
        in changed_runtime
    )
    assert (
        "scripts/rebuild_deferred_full_stack_capacity_reflow.py"
        in changed_runtime
    )
    assert (
        "Rebuild deferred capacity-reflow economics after handoff"
        in source
    )
    assert "id: deferred_capacity_reflow_rebuild" in source
    assert (
        "steps.fast_resume_dispatch.outcome == 'success' || "
        "steps.fallback_resume_dispatch.outcome == 'success'"
        in source
    )
    assert (
        "python scripts/rebuild_deferred_full_stack_capacity_reflow.py"
        in source
    )
    assert "RESEARCH ONLY / NO EXECUTION / NO RISK CHANGE" in source

    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    markout_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    capacity_at = source.index(
        "- name: Rebuild deferred capacity-reflow economics after handoff"
    )
    gate_at = source.index(
        "- name: Fail closed on upgrade handoff source"
    )
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    assert fallback_at < markout_at < capacity_at < gate_at < compact_at


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
    # Once the guard has rejected a push it must finish promptly. The
    # watchdog searches historical push run IDs, not just active runs.
    assert "holding runtime push rendezvous for active worker handoff" not in source
    assert "sleep 75" not in source
    assert "requesting graceful handoff independently of heartbeat" in source
    assert 'request_runtime_handoff "$trader_pid" "$replacement_run"' in source
    assert "for _ in $(seq 1 120)" in source
    assert 'kill -INT "$trader_pid"' in source
    assert 'kill -TERM "$trader_pid"' in source
    assert 'kill -KILL "$trader_pid"' in source
    assert 'mkfifo "$output_fifo"' in source
    assert 'watch_for_newer_runtime_run "$trader_pid" &' in source
    assert "upgrade_watch_pid=$!" in source
    assert "trap cleanup_runtime_processes EXIT" in source


def test_upgrade_handoff_is_not_a_successful_research_source() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    fail_at = source.index(
        "- name: Fail closed on upgrade handoff source"
    )

    assert fallback_at < fail_at
    fail_block = source[fail_at:]
    assert "id: research_source_gate" in fail_block
    assert "session-summary.json" in fail_block
    assert 'exit_reason == "upgrade_requested"' not in fail_block
    assert '[ "$exit_reason" = "upgrade_requested" ]' in fail_block
    assert "exit 75" in fail_block
    assert (
        "upgrade handoff run is state-continuity only "
        "and must not be a successful research source"
        in fail_block
    )


def test_research_ready_durable_state_dispatches_exact_horizon_comparison() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    durable_at = source.index(
        "- name: Upload durable continuous paper state"
    )
    gate_at = source.index(
        "- name: Fail closed on upgrade handoff source"
    )
    dispatch_at = source.index(
        "- name: Queue exact LONG trend horizon comparison"
    )
    terminal_research_at = source.index(
        "- name: Upload cadence shadow research state"
    )

    assert durable_at < gate_at < dispatch_at < terminal_research_at
    dispatch_block = source[dispatch_at:terminal_research_at]
    assert "steps.research_source_gate.outcome == 'success'" in dispatch_block
    assert "steps.durable_state_upload.outcome == 'success'" in dispatch_block
    assert "continue-on-error: true" in dispatch_block
    assert (
        "gh workflow run "
        "prospective-long-trend-exact-horizon-comparison.yml"
        in dispatch_block
    )
    assert '-f "source_run_id=$GITHUB_RUN_ID"' in dispatch_block
    assert '-f "source_run_attempt=$GITHUB_RUN_ATTEMPT"' in dispatch_block


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
    assert "src/cocomelon/research/continuous_paper_decision_export.py" in source
    assert "src/cocomelon/research/continuous_paper_decision_facts.py" in source
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
        '"src/cocomelon/research/prospective_weekly_drawdown_5m_exit_source.py"'
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
    assert pack_at < compact_at


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
    assert pack_at < compact_at


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
    assert pack_at < compact_at


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
    assert "approved integrity last miss / clean start / evaluated" in source
    assert "long-trend carveout clean start / evaluated / admit" in source
    assert "clean {minutes}m stack spread / carveout spread" in source

    markout_rebuild_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    markout_upload_at = source.index(
        "- name: Upload full-stack fast-markout research summary"
    )
    priority_rebuild_at = source.index(
        "- name: Rebuild correlation bucket priority audit after handoff"
    )
    assert markout_rebuild_at < markout_upload_at < priority_rebuild_at


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




def test_compact_learning_source_includes_weekly_drawdown_5m_candidate() -> None:
    source = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    upload = source.split(
        "      - name: Upload compact continuous learning source",
        1,
    )[1].split(
        "      - name:",
        1,
    )[0]

    assert (
        "continuous-paper-state/"
        "prospective-weekly-drawdown-5m-exit-source.json"
        in upload
    )



def test_upgrade_handoff_rebuilds_cooldown_evidence_after_successor_dispatch() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        '"src/cocomelon/research/deferred_consecutive_loss_cooldown.py"'
        in source
    )
    assert (
        '"scripts/rebuild_deferred_consecutive_loss_cooldown.py"'
        in source
    )
    changed_runtime = source.split("changed_runtime=", 1)[1]
    assert (
        "src/cocomelon/research/deferred_consecutive_loss_cooldown.py"
        in changed_runtime
    )
    assert (
        "scripts/rebuild_deferred_consecutive_loss_cooldown.py"
        in changed_runtime
    )
    assert "Rebuild deferred cooldown evidence after handoff" in source
    assert "id: deferred_cooldown_rebuild" in source
    assert (
        "python scripts/rebuild_deferred_consecutive_loss_cooldown.py"
        in source
    )
    assert "RESEARCH ONLY / NO EXECUTION / NO RISK CHANGE" in source
    assert "Upload early cooldown evidence" in source
    assert (
        "steps.deferred_cooldown_rebuild.outcome == 'success'"
        in source
    )
    assert "continuous-paper-cooldown-evidence-" in source
    assert "1h fee-adjusted PnL=" in source
    assert "robust option/market=" in source

    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    markout_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    priority_at = source.index(
        "- name: Rebuild correlation bucket priority audit after handoff"
    )
    loss_audit_at = source.index(
        "- name: Rebuild loss-streak context audit after handoff"
    )
    cooldown_at = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    cooldown_upload_at = source.index(
        "- name: Upload early cooldown evidence"
    )
    holder_at = source.index(
        "- name: Rebuild exact correlation holder release economics after handoff"
    )
    capacity_at = source.index(
        "- name: Rebuild deferred capacity-reflow economics after handoff"
    )
    gate_at = source.index(
        "- name: Fail closed on upgrade handoff source"
    )
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    assert (
        fallback_at
        < markout_at
        < priority_at
        < loss_audit_at
        < cooldown_at
        < cooldown_upload_at
        < holder_at
        < capacity_at
        < gate_at
        < compact_at
    )


def test_upgrade_handoff_builds_correlation_priority_after_markouts() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        '"src/cocomelon/research/prospective_correlation_bucket_priority.py"'
        in source
    )
    assert (
        '"src/cocomelon/research/deferred_correlation_bucket_priority.py"'
        in source
    )
    assert (
        '"scripts/rebuild_deferred_correlation_bucket_priority.py"'
        in source
    )
    assert "Rebuild correlation bucket priority audit after handoff" in source
    assert (
        "prospective-correlation-bucket-priority-summary.json"
        in source
    )
    assert "RESEARCH ONLY / NO EXECUTION / NO RISK CHANGE" in source

    markout_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    markout_upload_at = source.index(
        "- name: Upload full-stack fast-markout research summary"
    )
    priority_at = source.index(
        "- name: Rebuild correlation bucket priority audit after handoff"
    )
    priority_upload_at = source.index(
        "- name: Upload correlation bucket priority audit"
    )
    loss_audit_at = source.index(
        "- name: Rebuild loss-streak context audit after handoff"
    )
    capacity_at = source.index(
        "- name: Rebuild deferred capacity-reflow economics after handoff"
    )
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    assert (
        markout_at
        < markout_upload_at
        < priority_at
        < priority_upload_at
        < loss_audit_at
        < capacity_at
        < compact_at
    )



def test_safe_handoff_rebuilds_loss_streak_context_after_successor() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '"src/cocomelon/research/loss_streak_context_audit.py"' in source
    assert (
        '"src/cocomelon/research/deferred_loss_streak_context_audit.py"'
        in source
    )
    assert (
        '"scripts/rebuild_deferred_loss_streak_context_audit.py"'
        in source
    )
    changed_runtime = source.split("changed_runtime=", 1)[1]
    assert "src/cocomelon/research/loss_streak_context_audit.py" in changed_runtime
    assert (
        "src/cocomelon/research/deferred_loss_streak_context_audit.py"
        in changed_runtime
    )
    assert (
        "scripts/rebuild_deferred_loss_streak_context_audit.py"
        in changed_runtime
    )
    assert "Rebuild loss-streak context audit after handoff" in source
    assert "id: deferred_loss_streak_context_audit" in source
    audit_at = source.index(
        "- name: Rebuild loss-streak context audit after handoff"
    )
    audit_end = source.index(
        "- name: Upload loss-streak context audit",
        audit_at,
    )
    audit_block = source[audit_at:audit_end]
    assert 'if [ "$exit_reason" != "upgrade_requested" ]; then' not in audit_block
    assert "python scripts/rebuild_deferred_loss_streak_context_audit.py" in audit_block
    assert 'echo "ready=true" >> "$GITHUB_OUTPUT"' in source
    upload_at = source.index("- name: Upload loss-streak context audit")
    upload_block = source[upload_at:source.index(
        "- name: Rebuild deferred cooldown evidence after handoff",
        upload_at,
    )]
    assert (
        "steps.deferred_loss_streak_context_audit.outcome == 'success'"
        in upload_block
    )
    assert (
        "hashFiles('continuous-paper-state/"
        "loss-streak-context-audit-summary.json')"
        not in upload_block
    )
    assert "loss-streak-context-audit-summary.json" in source
    assert "continuous-paper-loss-streak-context-" in source
    assert "RESEARCH ONLY / NO EXECUTION / NO STRATEGY CHANGE" in source
    assert "baseline resolved / unresolved / non-loss controls" in source
    assert "loss share=" in source
    assert "baseline=" in source
    assert "delta=" in source

    fast_dispatch_at = source.index(
        "- name: Queue exact successor from fast resume"
    )
    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    loss_audit_at = source.index(
        "- name: Rebuild loss-streak context audit after handoff"
    )
    gate_at = source.index(
        "- name: Fail closed on upgrade handoff source"
    )
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    priority_at = source.index(
        "- name: Rebuild correlation bucket priority audit after handoff"
    )
    capacity_at = source.index(
        "- name: Rebuild deferred capacity-reflow economics after handoff"
    )
    assert (
        fast_dispatch_at
        < fallback_at
        < priority_at
        < loss_audit_at
        < capacity_at
        < gate_at
        < compact_at
    )


def test_capacity_release_books_are_watched_and_exported() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    module = (
        "src/cocomelon/research/"
        "continuous_paper_capacity_release_books.py"
    )
    release_execution = (
        "src/cocomelon/research/"
        "correlation_holder_release_execution.py"
    )
    deferred_release_execution = (
        "src/cocomelon/research/"
        "deferred_correlation_holder_release_execution.py"
    )
    rebuild_script = (
        "scripts/rebuild_correlation_holder_release_execution.py"
    )
    assert module in source
    assert module in source.split("changed_runtime=", 1)[1]
    assert release_execution in source
    assert release_execution in source.split("changed_runtime=", 1)[1]
    assert deferred_release_execution in source
    assert deferred_release_execution in source.split(
        "changed_runtime=", 1
    )[1]
    assert rebuild_script in source
    assert rebuild_script in source.split("changed_runtime=", 1)[1]
    assert "continuous-paper-state/capacity-release-books" in source
    compact = source.split(
        "- name: Upload compact continuous learning source",
        1,
    )[1].split("- name:", 1)[0]
    assert compact.index(
        "continuous-paper-state/opening-opportunities"
    ) < compact.index(
        "continuous-paper-state/capacity-release-books"
    )


def test_holder_release_execution_rebuild_is_after_successor_and_before_reflow() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "Rebuild exact correlation holder release economics after handoff"
        in source
    )
    assert "id: deferred_holder_release_execution" in source
    assert (
        "python scripts/rebuild_correlation_holder_release_execution.py"
        in source
    )
    assert (
        "correlation-holder-release-execution-summary.json"
        in source
    )
    assert (
        "continuous-paper-correlation-holder-release-execution-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
        in source
    )
    assert "legacy-unbound release books" in source
    assert "RESEARCH ONLY / NO EXECUTION / NO RISK CHANGE" in source

    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    holder_at = source.index(
        "- name: Rebuild exact correlation holder release economics after handoff"
    )
    holder_upload_at = source.index(
        "- name: Upload exact correlation holder release economics"
    )
    capacity_at = source.index(
        "- name: Rebuild deferred capacity-reflow economics after handoff"
    )
    compact_at = source.index(
        "- name: Upload compact continuous learning source"
    )
    assert (
        fallback_at
        < holder_at
        < holder_upload_at
        < capacity_at
        < compact_at
    )

    compact = source.split(
        "- name: Upload compact continuous learning source",
        1,
    )[1].split("- name:", 1)[0]
    assert (
        "continuous-paper-state/"
        "correlation-holder-release-execution-summary.json"
        in compact
    )



def test_continuous_paper_actions_api_calls_back_off_before_failing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    guard_at = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run is already active"
    )
    checkout_at = source.index("- uses: actions/checkout@v7", guard_at)
    guard = source[guard_at:checkout_at]
    assert "guard_runs_loaded=false" in guard
    assert "for guard_delay in 0 15 30 60 120 240 480 600 600 600 600 600" in guard
    assert 'sleep "$guard_delay"' in guard
    assert "guard_runs_loaded=true" in guard
    assert 'if [ "$guard_runs_loaded" != "true" ]; then' in guard
    assert "continuous-paper guard API unavailable" in guard
    assert "continuous-paper guard job API unavailable" in guard
    assert "time.sleep(10)" in guard
    assert "continuous-paper guard could not inspect active run jobs" in guard

    fast_at = source.index("- name: Queue exact successor from fast resume")
    cleanup_at = source.index(
        "- name: Remove local fast resume archive",
        fast_at,
    )
    fast = source[fast_at:cleanup_at]
    assert "successor receipt API unavailable" in fast
    assert "exact successor dispatch API unavailable" in fast
    assert "for attempt in $(seq 1 8)" in fast
    assert "find_successor || true" in fast
    assert "dispatch command never succeeded" in fast

    fallback_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    research_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff",
        fallback_at,
    )
    fallback = source[fallback_at:research_at]
    assert "successor receipt API unavailable" in fallback
    assert "fallback successor dispatch API unavailable" in fallback
    assert "for attempt in $(seq 1 8)" in fallback
    assert "find_successor || true" in fallback
    assert "dispatch command never succeeded" in fallback



def test_upgrade_handoff_builds_cooldown_context_stability() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-cooldown-context-stability" in source
    assert "cooldown-context-stability-summary.json" in source
    assert "continuous-paper-cooldown-context-stability-" in source
    assert "direction-only candidates allowed" in source
    assert "RESEARCH ONLY / NO STRATEGY OR RISK CHANGE" in source

    cooldown_upload_at = source.index(
        "- name: Upload early cooldown evidence"
    )
    stability_at = source.index(
        "- name: Build cooldown context stability after handoff"
    )
    stability_upload_at = source.index(
        "- name: Upload cooldown context stability"
    )
    holder_release_at = source.index(
        "- name: Rebuild exact correlation holder release economics "
        "after handoff"
    )
    assert (
        cooldown_upload_at
        < stability_at
        < stability_upload_at
        < holder_release_at
    )

    upload = source[stability_upload_at:holder_release_at]
    assert (
        "steps.deferred_cooldown_context_stability.outcome == 'success'"
        in upload
    )
    assert "if-no-files-found: error" in upload



def test_upgrade_handoff_builds_cooldown_context_selection_record() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '"src/cocomelon/research/cooldown_context_stability.py"' in source
    assert '"src/cocomelon/research/cooldown_context_selection.py"' in source
    assert '"src/cocomelon/cooldown_context_stability_cli.py"' in source
    assert '"src/cocomelon/cooldown_context_selection_cli.py"' in source

    assert "cocomelon-cooldown-context-selection" in source
    assert "cooldown-context-selection-record.json" in source
    assert "prospective freeze required before strategy use" in source

    stability_at = source.index(
        "- name: Build cooldown context stability after handoff"
    )
    selection_at = source.index(
        "- name: Build cooldown context selection record"
    )
    upload_at = source.index(
        "- name: Upload cooldown context stability"
    )
    holder_release_at = source.index(
        "- name: Rebuild exact correlation holder release economics "
        "after handoff"
    )
    assert stability_at < selection_at < upload_at < holder_release_at

    upload = source[upload_at:holder_release_at]
    assert "cooldown-context-stability-summary.json" in upload
    assert "cooldown-context-selection-record.json" in upload
    assert (
        "steps.deferred_cooldown_context_selection.outcome == 'success'"
        in upload
    )
    assert "if-no-files-found: error" in upload



def test_upgrade_handoff_freezes_and_scores_loss_context_prospectively() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Restore immutable loss-context candidate freeze" in source
    assert "Freeze stable loss context prospectively" in source
    assert "Score frozen loss context on future trades" in source
    assert "Upload immutable loss-context candidate" in source
    assert "cocomelon-loss-context-freeze" in source
    assert "cocomelon-loss-context-prospective" in source
    assert "loss-context-candidate-freeze.json" in source
    assert "loss-context-prospective-report.json" in source
    assert "continuous-paper-loss-context-candidate" in source
    assert "RESEARCH ONLY / NO STRATEGY OR RISK CHANGE" in source

    audit_at = source.index(
        "- name: Rebuild loss-streak context audit after handoff"
    )
    restore_at = source.index(
        "- name: Restore immutable loss-context candidate freeze"
    )
    freeze_at = source.index(
        "- name: Freeze stable loss context prospectively"
    )
    score_at = source.index(
        "- name: Score frozen loss context on future trades"
    )
    upload_at = source.index(
        "- name: Upload immutable loss-context candidate"
    )
    cooldown_at = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    assert audit_at < restore_at < freeze_at < score_at < upload_at < cooldown_at

    restore = source[restore_at:freeze_at]
    assert "head_branch" in restore
    assert ".github/workflows/continuous-paper.yml" in restore
    assert "verify_loss_context_candidate_freeze" in restore

    freeze = source[freeze_at:score_at]
    assert "--source-paper-run-id" in freeze
    assert "--source-paper-run-attempt" in freeze
    assert "--source-paper-head-sha" in freeze

    score = source[score_at:upload_at]
    assert "--state-root" in score
    assert "ready for review / changes strategy / execution" in score


def test_loss_context_summary_never_frames_direction_as_authority() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    audit_at = source.index(
        "- name: Rebuild loss-streak context audit after handoff"
    )
    upload_at = source.index(
        "- name: Upload loss-streak context audit",
        audit_at,
    )
    audit = source[audit_at:upload_at]
    assert "direction-only candidates allowed" in audit
    assert "context-filter candidates / stable" in audit
    assert "execution / strategy / risk authority" in audit



def test_loss_context_paired_shadow_runtime_handoff_is_non_blocking() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for path in (
        "src/cocomelon/research/loss_context_paired_portfolio_shadow.py",
        "src/cocomelon/research/loss_context_paired_shadow_runtime.py",
        "src/cocomelon/research/loss_context_portfolio_shadow_candidate.py",
    ):
        assert f'"{path}"' in source
        changed_runtime = source.split("changed_runtime=", 1)[1]
        assert path in changed_runtime

    restore_at = source.index(
        "- name: Restore immutable loss-context shadow candidate for runtime"
    )
    trader_at = source.index("- name: Run continuous paper trader")
    assert restore_at < trader_at
    restore_block = source[restore_at:trader_at]
    assert "continue-on-error: true" in restore_block
    assert (
        "continuous-paper-loss-context-portfolio-shadow-candidate"
        in restore_block
    )
    assert "verify_loss_context_portfolio_shadow_freeze" in restore_block
    assert "restored=none" in restore_block

    fast_dispatch_at = source.index(
        "- name: Queue exact successor from fast resume"
    )
    fallback_dispatch_at = source.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    shadow_upload_at = source.index(
        "- name: Upload paired loss-context portfolio shadow state"
    )
    review_at = source.index(
        "- name: Review paired loss-context portfolio shadow"
    )
    review_upload_at = source.index(
        "- name: Upload paired loss-context portfolio shadow review"
    )
    deferred_research_at = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    assert (
        fast_dispatch_at
        < fallback_dispatch_at
        < shadow_upload_at
        < review_at
        < review_upload_at
        < deferred_research_at
    )
    shadow_upload = source[shadow_upload_at:review_at]
    assert "continue-on-error: true" in shadow_upload
    assert "loss-context-paired-portfolio-shadow-summary.json" in shadow_upload
    assert "scoped-v2/paired-shadow-state.json" in shadow_upload
    assert (
        "continuous-paper-state/"
        "loss-context-paired-portfolio-shadow-scoped-v2"
    ) in shadow_upload
    assert (
        "continuous-paper-state/loss-context-paired-portfolio-shadow\n"
    ) not in shadow_upload

    review = source[review_at:review_upload_at]
    assert (
        "loss-context-paired-portfolio-shadow-scoped-v2/review-ledger.jsonl"
    ) in review
    assert (
        "loss-context-paired-portfolio-shadow/review-ledger.jsonl"
    ) not in review
    assert "continue-on-error: true" in review
    assert "cocomelon-loss-context-paired-shadow-review" in review
    assert "review-ledger.jsonl" in review
    assert "candidate absolute total / realized net PnL" in review
    assert "candidate-minus-baseline total / realized / max-DD delta" in review
    assert "ready for review / failures" in review
    assert "RESEARCH REVIEW ONLY / NO STRATEGY CHANGE" in review

    review_upload = source[review_upload_at:deferred_research_at]
    assert (
        "steps.loss_context_paired_shadow_review.outcome == 'success'"
    ) in review_upload



def test_loss_context_handoff_chain_uses_raw_success_outcomes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index(
        "- name: Rebuild loss-streak context audit after handoff"
    )
    end = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff",
        start,
    )
    chain = source[start:end]

    assert (
        "steps.deferred_loss_streak_context_audit.outcome == 'success'"
        in chain
    )
    assert "steps.loss_context_freeze.outcome == 'success'" in chain
    assert "steps.loss_context_prospective.outcome == 'success'" in chain
    assert (
        "steps.loss_context_account_readiness.outcome == 'success'"
        in chain
    )
    assert (
        "steps.loss_context_capacity_reflow.outcome == 'success'"
        in chain
    )
    assert (
        "steps.loss_context_holder_release_execution.outcome == 'success'"
        in chain
    )
    assert (
        "steps.loss_context_replacement_entry_fill.outcome == 'success'"
        in chain
    )
    assert (
        "steps.loss_context_replacement_exit_pnl.outcome == 'success'"
        in chain
    )
    assert (
        "steps.loss_context_portfolio_composition.outcome == 'success'"
        in chain
    )
    assert (
        "steps.loss_context_portfolio_shadow_freeze.outcome == 'success'"
        in chain
    )
    assert (
        "hashFiles('continuous-paper-state/"
        "loss-streak-context-audit-summary.json')"
        not in chain
    )
    assert (
        "hashFiles('continuous-paper-state/"
        "loss-context-account-readiness-summary.json')"
        not in chain
    )


def test_loss_context_optional_freezes_fail_closed_without_candidates() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    for step_id in (
        "loss_context_prospective",
        "loss_context_account_readiness",
        "loss_context_capacity_reflow",
        "loss_context_holder_release_execution",
        "loss_context_replacement_entry_fill",
        "loss_context_replacement_exit_pnl",
        "loss_context_portfolio_composition",
    ):
        marker = f"id: {step_id}"
        start = source.index(marker)
        next_step = source.find("\n      - name:", start)
        block = source[start:] if next_step < 0 else source[start:next_step]
        assert 'echo "ready=true" >> "$GITHUB_OUTPUT"' in block



def test_cooldown_handoff_chain_uses_raw_success_outcomes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index(
        "- name: Rebuild deferred cooldown evidence after handoff"
    )
    end = source.index(
        "- name: Rebuild exact correlation holder release economics after handoff",
        start,
    )
    chain = source[start:end]

    assert "steps.deferred_cooldown_rebuild.outcome == 'success'" in chain
    assert (
        "steps.deferred_cooldown_context_stability.outcome == 'success'"
        in chain
    )
    assert (
        "steps.deferred_cooldown_context_selection.outcome == 'success'"
        in chain
    )
    assert "steps.cooldown_context_freeze.outcome == 'success'" in chain
    assert (
        "hashFiles('continuous-paper-state/"
        "cooldown-context-stability-summary.json')"
        not in chain
    )
    assert (
        "hashFiles('continuous-paper-state/"
        "cooldown-context-selection-record.json')"
        not in chain
    )


def test_cooldown_optional_freezes_fail_closed_without_candidates() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    for step_id in (
        "deferred_cooldown_context_stability",
        "deferred_cooldown_context_selection",
        "cooldown_context_prospective",
    ):
        marker = f"id: {step_id}"
        start = source.index(marker)
        next_step = source.find("\n      - name:", start)
        block = source[start:] if next_step < 0 else source[start:next_step]
        assert 'echo "ready=true" >> "$GITHUB_OUTPUT"' in block


def test_optional_research_freezes_fail_closed_without_qualified_candidate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    loss_start = source.index(
        "- name: Freeze stable loss context prospectively"
    )
    loss_end = source.index(
        "- name: Score frozen loss context on future trades",
        loss_start,
    )
    loss_block = source[loss_start:loss_end]
    assert "no stable loss context selected" in loss_block
    assert "exit 78" in loss_block

    portfolio_start = source.index(
        "- name: Freeze loss-context portfolio shadow prospectively"
    )
    portfolio_end = source.index(
        "- name: Upload immutable loss-context portfolio shadow candidate",
        portfolio_start,
    )
    portfolio_block = source[portfolio_start:portfolio_end]
    assert "portfolio composition is not ready" in portfolio_block
    assert "exit 78" in portfolio_block

    cooldown_start = source.index(
        "- name: Freeze selected cooldown context prospectively"
    )
    cooldown_end = source.index(
        "- name: Score frozen cooldown context on future evidence",
        cooldown_start,
    )
    cooldown_block = source[cooldown_start:cooldown_end]
    assert "no stable cooldown context selected" in cooldown_block
    assert "exit 78" in cooldown_block



def test_exact_research_ledgers_require_eligible_paper_source() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    gate_at = source.index("- name: Fail closed on upgrade handoff source")
    durable_at = source.index("- name: Upload durable continuous paper state")
    compact_at = source.index("- name: Upload compact continuous learning source")

    for name, command in (
        (
            "Queue exact profit-lock execution ledger",
            "gh workflow run profit-lock-execution-ledger.yml",
        ),
        (
            "Queue exact momentum-pullback fast-markout ledger",
            "gh workflow run prospective-momentum-pullback-fast-markout-ledger.yml",
        ),
        (
            "Queue exact range-compression entry evidence",
            "gh workflow run prospective-range-compression-entry-evidence.yml",
        ),
    ):
        at = source.index(f"- name: {name}")
        next_at = source.find("\n      - name:", at + 1)
        block = source[at:next_at if next_at >= 0 else len(source)]
        assert durable_at < gate_at < compact_at < at
        assert "always()" in block
        assert "steps.guard.outputs.skip != 'true'" in block
        assert "steps.durable_state_upload.outcome == 'success'" in block
        assert "steps.research_source_gate.outcome == 'success'" in block
        assert "steps.compact_learning_upload.outcome == 'success'" in block
        assert "continue-on-error: true" in block
        assert command in block
        assert '-f "source_run_id=$GITHUB_RUN_ID"' in block
        assert '-f "source_run_attempt=$GITHUB_RUN_ATTEMPT"' in block

    gate_block = source[
        gate_at:
        source.index("- name: Queue exact LONG trend horizon comparison", gate_at)
    ]
    assert '[ "$exit_reason" = "upgrade_requested" ]' in gate_block
    assert "exit 75" in gate_block


def test_forward_loss_context_cohort_is_frozen_before_runtime_and_reported_after_handoff() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    anchor_at = source.index(
        "- name: Anchor immutable forward-only loss-context cohort"
    )
    runtime_at = source.index("- name: Run continuous paper trader")
    pack_at = source.index("- name: Pack fast continuous paper resume state")
    review_at = source.index(
        "- name: Review immutable forward-only loss-context coverage after handoff"
    )
    upload_at = source.index("- name: Upload forward-only loss-context coverage")
    assert anchor_at < runtime_at < pack_at < review_at < upload_at

    anchor = source[anchor_at:runtime_at]
    review = source[review_at:upload_at]
    next_step = source.index(
        "- name: Rebuild deferred full-stack markouts after handoff", upload_at
    )
    upload = source[upload_at:next_step]
    assert "python -m cocomelon.research.loss_context_prospective_cohort anchor" in anchor
    assert "--source-run-id" in anchor
    assert "--source-run-attempt" in anchor
    assert "--source-head-sha" in anchor
    assert "loss-context-forward-cohort-anchor.json" in anchor
    assert "python -m cocomelon.research.loss_context_prospective_cohort report" in review
    assert "steps.forward_loss_context_anchor.outcome == 'success'" in review
    assert "steps.fast_resume_dispatch.outcome == 'success'" in review
    assert "steps.fallback_resume_dispatch.outcome == 'success'" in review
    assert "loss-context-forward-cohort-report.json" in review
    assert "forward closed-trade net PnL" in review
    assert "LONG / SHORT" in review
    assert "research discovery ready" in review
    assert "steps.forward_loss_context_review.outcome == 'success'" in upload
    assert "loss-context-forward-cohort-anchor.json" in upload
    assert "loss-context-forward-cohort-report.json" in upload


def test_skipped_push_guard_never_blocks_exact_successor() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    guard_at = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run"
    )
    checkout_at = source.index("- uses: actions/checkout@v7", guard_at)
    guard = source[guard_at:checkout_at]

    assert 'step.get("name") == "Run actions/checkout@v7"' in guard
    assert 'step.get("conclusion") == "skipped"' in guard
    assert "if skipped_checkout:" in guard
    assert "continue" in guard[guard.index("if skipped_checkout:"):]
    assert "trader_status in" in guard
    assert 'trader_status in {"queued", "pending", "in_progress"}' in guard
    assert "after trading has stopped" in guard

    # A skipped push used to sleep for 75 seconds after recording
    # skip=true. The newly dispatched successor could observe its
    # pending trader step and skip too, leaving no running paper worker.
    skipped_path = guard[guard.index('if [ -n "$ACTIVE" ]; then'):]
    assert 'echo "skip=true" >> "$GITHUB_OUTPUT"' in skipped_path
    assert 'sleep 75' not in skipped_path
    assert 'sleep 60' not in skipped_path

    # True in-progress trader jobs still guard against duplicate workers.
    assert '"in_progress"' in guard
    assert 'print(run_id)' in guard



def test_guarded_recovery_prefers_finished_trader_upload_over_older_account() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index(
        "- name: Restore latest trusted state for watchdog/manual recovery"
    )
    end = source.index(
        "- name: Restore immutable loss-context shadow candidate for runtime",
        start,
    )
    recovery = source[start:end]
    assert "key=lambda item: item.get(\"created_at\", \"\")" in recovery
    assert "reverse=True" in recovery
    assert 'run.get("status") == "in_progress"' in recovery
    assert "actions/runs/{run_id}/jobs?per_page=100" in recovery
    assert 'job.get("name") == "paper"' in recovery
    for step in (
        "Run continuous paper trader",
        "Pack durable continuous paper state",
        "Upload durable continuous paper state",
    ):
        assert step in recovery
    assert 'step.get("status") == "completed"' in recovery
    assert 'step.get("conclusion") == "success"' in recovery
    assert '"Pack durable continuous paper state",' in recovery
    assert '"Upload durable continuous paper state",' in recovery
    assert "} <= successful_steps:" in recovery
    assert "continue" in recovery
    assert 'run.get("status") == "completed"' in recovery
    assert 'run.get("conclusion") in {"success", "failure"}' in recovery
    assert "ARTIFACT_HEAD_SHA" in recovery
    assert "bash scripts/restore_continuous_paper_state.sh" in recovery




def test_paper_upgrade_watchdog_pathspec_is_one_shell_command() -> None:
    """Regression: naked filenames were executed on each heartbeat."""
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "continuous-paper.yml"
    ).read_text(encoding="utf-8")
    beginning = workflow.index('changed_runtime="$(')
    end = workflow.index(')"', beginning)
    snippet = workflow[beginning:end]
    lines = snippet.splitlines()
    assert len(lines) >= 4
    assert lines[1].lstrip().startswith("git diff --name-only ")
    for line in lines[1:-2]:
        assert line.rstrip().endswith("\\"), (
            "upgrade pathspec split into an unintended executable shell command"
        )
    assert "src/cocomelon/research/prospective_early_reserved_trailing.py" in snippet
    assert "src/cocomelon/research/prospective_early_vs_late_trailing.py" in snippet



def test_full_journal_chart_and_long_loss_evidence_runs_immediately_after_handoff() -> None:
    """Full journal research must not wait behind slow unrelated rebuilds."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    fallback = workflow.index(
        "- name: Queue fallback exact successor continuous paper worker"
    )
    stages = [
        "- name: Audit all closed paper trades and recorded entry-to-exit charts",
        "- name: Upload all closed paper-trade economics and charts",
        "- name: Attribute full-journal LONG losses to entry and exit evidence",
        "- name: Upload all-paper LONG loss attribution",
    ]
    indices = [workflow.index(stage) for stage in stages]
    paired_shadow = workflow.index(
        "- name: Upload paired loss-context portfolio shadow state"
    )
    slow_research = workflow.index(
        "- name: Rebuild deferred full-stack markouts after handoff"
    )
    exit_chart_gate = workflow.index(
        "- name: Cross-verify early-versus-late IOC exits against full chart coverage"
    )
    assert fallback < indices[0] < indices[1] < indices[2] < indices[3]
    assert indices[3] < paired_shadow < slow_research < exit_chart_gate
    assert all(workflow.count(step) == 1 for step in stages)
    chart = workflow[indices[0]:indices[1]]
    loss = workflow[indices[2]:indices[3]]
    assert "steps.fast_resume_dispatch.outcome == 'success'" in chart
    assert "steps.fallback_resume_dispatch.outcome == 'success'" in chart
    assert "steps.guard.outputs.skip != 'true'" in chart
    assert "hashFiles('continuous-paper-state/session-summary.json')" in chart
    assert "continue-on-error: true" in chart
    assert "scripts/rebuild_deferred_all_trade_chart_audit.py" in chart
    assert "steps.deferred_all_trade_chart_audit.outcome == 'success'" in workflow[
        indices[1]:indices[2]
    ]
    assert "steps.deferred_all_trade_chart_audit.outcome == 'success'" in loss
    assert "continue-on-error: true" in loss
    assert "scripts/rebuild_deferred_long_entry_loss_attribution.py" in loss
    assert "steps.deferred_long_loss_attribution.outcome == 'success'" in workflow[
        indices[3]:paired_shadow
    ]
    assert "steps.deferred_all_trade_chart_audit.outcome == 'success'" in workflow[
        exit_chart_gate:workflow.index(
            "- name: Upload forward early-vs-late chart coverage gate",
            exit_chart_gate,
        )
    ]


def test_deferred_feed_source_provenance_runs_only_after_safe_chart_audit() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    sections = [
        "Audit all closed paper trades and recorded entry-to-exit charts",
        "Upload all closed paper-trade economics and charts",
        "Diagnose unresolved source streams behind paper chart gaps",
        "Upload paper feed source debt by exact stream",
        "Attribute full-journal LONG losses to entry and exit evidence",
    ]
    positions = [source.index(label) for label in sections]
    assert positions == sorted(positions)
    assert all(source.count(label) == 1 for label in sections)
    assert "steps.deferred_all_trade_chart_audit.outcome == 'success'" in source
    assert "id: deferred_feed_gap_source_audit" in source
    assert "steps.deferred_feed_gap_source_audit.outcome == 'success'" in source
    assert "scripts/rebuild_deferred_feed_gap_source_audit.py" in source
    assert "continuous-paper-feed-gap-source-audit-" in source
    assert "continuous-paper-state/deferred-feed-gap-source-audit.json" in source
    assert "continuous-paper-state/named-gap-recovery-witnesses.jsonl" in source



def test_speculative_push_cannot_take_lease_while_exact_handoff_is_pending() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index(
        "- name: Skip bootstrap/watchdog when a continuous paper run is already active"
    )
    end = source.index("- uses: actions/checkout@v7", start)
    guard = source[start:end]
    assert guard.index(
        'trader_status in {"queued", "pending", "in_progress"}'
    ) < guard.index('trader_status == "completed"')
    assert 'and not os.environ.get("SOURCE_RUN_ID")' in guard
    for step in (
        "Pack fast continuous paper resume state",
        "Upload fast continuous paper resume state",
        "Queue exact successor from fast resume",
        "Queue fallback exact successor continuous paper worker",
    ):
        assert step in guard
    assert 'step.get("conclusion") == "success"' in guard
    assert 'step.get("status") in {' in guard
    assert "handoff_pending or handoff_dispatched" in guard
    assert "speculative recovery yields to" in guard
    assert guard.index("if skipped_checkout:") < guard.index(
        'trader_status == "completed"'
    )


def test_manual_recovery_prefers_latest_verified_fast_or_durable_source() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index(
        "- name: Restore latest trusted state for watchdog/manual recovery"
    )
    end = source.index(
        "- name: Restore immutable loss-context shadow candidate for runtime",
        start,
    )
    restore = source[start:end]
    assert '"continuous-paper-resume-"' in restore
    assert '"continuous-paper-state-"' in restore
    assert 'key=lambda item: item.get("created_at", "")' in restore
    assert "reverse=True" in restore
    assert '"Run continuous paper trader" not in successful_steps' in restore
    assert '"Upload fast continuous paper resume state"' in restore
    assert '"Upload durable continuous paper state"' in restore
    assert '"Pack durable continuous paper state"' in restore
    assert "continuous-paper-resume.tar.zst" in restore
    assert "ARTIFACT_MEMBER" in restore
    assert 'if [ "$ARTIFACT_MEMBER" = "continuous-paper-resume.tar.zst" ]; then' in restore
    assert 'bash scripts/restore_continuous_paper_state.sh' in restore
