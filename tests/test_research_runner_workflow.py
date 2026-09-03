from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job_block(source: str, name: str, next_name: str | None) -> str:
    block = source.split(f"\n  {name}:\n", 1)[1]
    if next_name is not None:
        block = block.split(f"\n  {next_name}:\n", 1)[0]
    return block


def test_research_campaign_is_separate_paper_only_and_offset_from_v4() -> None:
    source = _source()
    lowered = source.lower()

    assert "name: Scheduled Research Mainnet Replay Campaign" in source
    assert 'cron: "2 7 * * *"' in source
    assert 'cron: "37 1,7,13,19 * * *"' not in source
    assert "COCOMELON_EXECUTION_MODE: paper" in source
    assert "cancel-in-progress: false" in source
    assert "record-mainnet-evidence" in source
    assert "prepare_research_cohort_source" in source
    assert "complete_research_cohort" in source
    assert "cocomelon-research-runner run-artifact" in source
    assert "research-authoritative-registry" in source

    for forbidden in (
        "v4-mainnet-corpus",
        "evidence_corpus_curator",
        "phase9_v4_one_shot",
        "candidate_edge",
        "private_key",
        "wallet",
        "withdraw",
        "transfer",
        "send_order",
        "live_order",
    ):
        assert forbidden not in lowered
    assert lowered.count("evidence-campaign-v4-scheduled") == 1
    preflight = source.split(
        "- name: Refuse research capture while V4 acquisition is active",
        1,
    )[1].split("- name: Upload prepared research control state", 1)[0]
    assert "scripts/research_v4_active_acquisition.sh" in preflight


def test_research_campaign_pins_candidate_strategy_before_trusted_capture() -> None:
    source = _source()

    assert "Resolve candidate code revision from authoritative registry" in source
    assert "SELECT code_revision FROM research_candidates WHERE candidate_id = ?" in source
    assert "candidate_revision: ${{ steps.candidate.outputs.revision }}" in source
    assert "Checkout candidate code revision" in source
    assert "ref: ${{ needs.prepare-control.outputs.candidate_revision }}" in source
    resolve_index = source.index("Resolve candidate code revision from authoritative registry")
    assert resolve_index < source.index("Checkout candidate code revision")
    assert source.index("Checkout candidate code revision") < source.index("Install Cocomelon")
    assert source.index("docker save") < source.index("record-mainnet-evidence")


def test_candidate_build_never_receives_authoritative_registry_or_observations() -> None:
    source = _source()
    candidate = _job_block(source, "candidate-build", "capture-control")

    assert "research.sqlite3" not in candidate
    assert "research-control-stage" not in candidate
    assert "record-mainnet-evidence" not in candidate
    assert "research-campaign/recording" not in candidate
    assert "SELECT config_digest FROM research_candidates" not in candidate
    assert candidate.index("Checkout candidate code revision") < candidate.index(
        "actions/setup-python@v5"
    )
    setup = candidate.split("- uses: actions/setup-python@v5", 1)[1].split(
        "- name: Install Cocomelon",
        1,
    )[0]
    assert "cache: pip" in setup
    assert "cache-dependency-path: candidate-src/pyproject.toml" in setup
    upload = candidate.split("- name: Upload candidate research stage", 1)[1]
    assert "candidate-package/" in upload
    assert "research-campaign" not in upload


def test_registry_restore_requires_trusted_main_workflow_provenance() -> None:
    source = _source()
    restore = source.split("- name: Restore authoritative research registry", 1)[1].split(
        "- name: Resolve candidate code revision from authoritative registry",
        1,
    )[0]

    assert "GH_TOKEN: ${{ github.token }}" in restore
    assert "/actions/artifacts?name=research-authoritative-registry" in restore
    assert "/actions/runs/$RUN_ID" in restore
    assert '.head_branch == "main"' in restore
    assert '.path == ".github/workflows/research-campaign-scheduled.yml"' in restore
    assert '.path == ".github/workflows/research-v4-registry-sync.yml"' in restore
    assert '.status == "completed"' in restore
    assert '.conclusion == "success" or .conclusion == "failure"' in restore
    assert "workflow_run.id" in restore
    assert "sort_by(.created_at) | reverse | .[0].id // empty" not in restore


def test_actions_token_is_confined_to_trusted_registry_jobs() -> None:
    source = _source()
    prepare = _job_block(source, "prepare-control", "candidate-build")
    candidate = _job_block(source, "candidate-build", "capture-control")
    capture = _job_block(source, "capture-control", "candidate-decisions")
    decisions = _job_block(source, "candidate-decisions", "refresh-authority")
    refresh = _job_block(source, "refresh-authority", "evaluate-research")
    evaluation = _job_block(source, "evaluate-research", "finalize-publish")
    finalization = _job_block(source, "finalize-publish", "dispatch-dashboard")
    dashboard_dispatch = _job_block(source, "dispatch-dashboard", None)
    refresh_dispatch = source.split(
        "- name: Dispatch post-capture V4 authority synchronization",
        1,
    )[1].split("- name: Download refreshed V4 authority after acquisition", 1)[0]
    refresh_download = source.split(
        "- name: Download refreshed V4 authority after acquisition",
        1,
    )[1].split("- name: Merge refreshed V4 authority after acquisition", 1)[0]
    refresh_merge = source.split(
        "- name: Merge refreshed V4 authority after acquisition",
        1,
    )[1].split("- name: Upload refreshed research stage", 1)[0]
    evaluation_rebase = evaluation.split(
        "- name: Rebase staged registry onto latest trusted authority under publisher lock",
        1,
    )[1].split("- name: Complete trusted research cohort from candidate decisions", 1)[0]
    evaluation_before_rebase = evaluation.split(
        "- name: Rebase staged registry onto latest trusted authority under publisher lock",
        1,
    )[0]
    evaluation_after_rebase = evaluation.split(
        "- name: Complete trusted research cohort from candidate decisions",
        1,
    )[1]
    finalizer_rebase = finalization.split(
        "- name: Rebase recovered fallback registry onto latest trusted authority",
        1,
    )[1].split("- name: Download capture evidence for final audit", 1)[0]
    finalizer_before_rebase = finalization.split(
        "- name: Rebase recovered fallback registry onto latest trusted authority",
        1,
    )[0]
    finalizer_after_rebase = finalization.split(
        "- name: Download capture evidence for final audit",
        1,
    )[1]

    assert "actions: read" in prepare
    assert "actions: write" in refresh
    assert "actions: read" in evaluation
    assert "actions: read" in finalization
    assert "actions: write" in dashboard_dispatch.split("steps:", 1)[0]
    for isolated in (candidate, capture, decisions):
        assert "GH_TOKEN:" not in isolated
    assert "GH_TOKEN:" not in evaluation_before_rebase
    assert "GH_TOKEN: ${{ github.token }}" in evaluation_rebase
    assert "GH_TOKEN:" not in evaluation_after_rebase
    assert "GH_TOKEN:" not in finalizer_before_rebase
    assert "GH_TOKEN: ${{ github.token }}" in finalizer_rebase
    assert "GH_TOKEN:" not in finalizer_after_rebase
    assert "GH_TOKEN: ${{ github.token }}" in dashboard_dispatch
    assert source.count("GH_TOKEN: ${{ github.token }}") == 8
    assert prepare.count("GH_TOKEN: ${{ github.token }}") == 3
    assert "GH_TOKEN: ${{ github.token }}" in prepare
    assert "GH_TOKEN: ${{ github.token }}" in refresh_dispatch
    assert "GH_TOKEN: ${{ github.token }}" in refresh_download
    assert "GH_TOKEN:" not in refresh_merge
    assert "/usr/bin/gh api" in prepare
    assert "/usr/bin/gh api" in refresh_dispatch
    assert "/usr/bin/gh api" in refresh_download
    assert "/usr/bin/gh api" in evaluation_rebase
    assert "/usr/bin/gh api" in finalizer_rebase
    assert "/usr/bin/gh api" in dashboard_dispatch
    assert "import sqlite3" in refresh_download
    assert "from cocomelon" not in refresh_download.lower()
    assert "merge_v4_authority_snapshot" in refresh_merge
    assert "merge_v4_authority_snapshot" in evaluation_rebase
    assert "merge_v4_authority_snapshot" in finalizer_rebase


def test_attempt_identity_is_persisted_before_candidate_setup() -> None:
    source = _source()

    assert "Persist acquisition attempt before candidate setup" in source
    assert source.index("Persist acquisition attempt before candidate setup") < source.index(
        "Checkout candidate code revision"
    )
    assert source.index("Persist acquisition attempt before candidate setup") < source.index(
        "Install Cocomelon"
    )
    failure = source.split("- name: Persist workflow failure in attempt ledger", 1)[1].split(
        "- name: Upload complete research campaign audit trail",
        1,
    )[0]
    assert "import sqlite3" in failure
    assert "UPDATE research_runner_attempts" in failure


def test_refresh_authorizes_capture_before_candidate_and_evaluation_recombines_decisions() -> None:
    source = _source()
    refresh = _job_block(source, "refresh-authority", "evaluate-research")
    decisions = _job_block(source, "candidate-decisions", "refresh-authority")
    evaluation = _job_block(source, "evaluate-research", "finalize-publish")
    refresh_download = source.split(
        "- name: Download refreshed V4 authority after acquisition",
        1,
    )[1].split("- name: Merge refreshed V4 authority after acquisition", 1)[0]
    refresh_merge = source.split(
        "- name: Merge refreshed V4 authority after acquisition",
        1,
    )[1].split("- name: Upload refreshed research stage", 1)[0]

    assert "Download prepared research control state for authority merge" in refresh
    assert "research-control-stage-${{ github.run_id }}-${{ github.run_attempt }}" in refresh
    assert "Download trusted research capture stage" in refresh
    assert "research-capture-source-stage-${{ github.run_id }}-${{ github.run_attempt }}" in refresh
    assert "Download candidate research stage" not in refresh
    assert "research-decision-stage-${{ github.run_id }}-${{ github.run_attempt }}" not in refresh
    assert "refresh-authority" in decisions.split("steps:", 1)[0]
    assert "candidate-decisions" not in refresh.split("steps:", 1)[0]
    assert "candidate-decisions" in evaluation.split("steps:", 1)[0]
    assert "Download candidate research stage" in evaluation
    assert "research-decision-stage-${{ github.run_id }}-${{ github.run_attempt }}" in evaluation
    assert source.index("Acquire one public mainnet research cohort") < source.index(
        "Download refreshed V4 authority after acquisition"
    )
    assert refresh.index("Download refreshed V4 authority after acquisition") < refresh.index(
        "Merge refreshed V4 authority after acquisition"
    )
    assert refresh.index("Merge refreshed V4 authority after acquisition") < refresh.index(
        "Authorize candidate observation and record research touch"
    )
    assert '"$RUN_PATH" != ".github/workflows/research-v4-registry-sync.yml"' in refresh_download
    assert '"$RUN_BRANCH" != "main"' in refresh_download
    assert '"$RUN_STATUS" != "completed"' in refresh_download
    assert '"$RUN_CONCLUSION" != "success"' in refresh_download
    assert "merge_v4_authority_snapshot" in refresh_merge
    assert "assert_batch_disjoint_from_v4" in refresh_merge
    assert "record_touched_interval" in refresh_merge
    assert "research-campaign/state/research.sqlite3" in refresh_merge
    assert "research-campaign/state/refreshed-v4-authority.sqlite3" in refresh_merge
    assert 'cp "$REGISTRY_PATH" research-campaign/state/research.sqlite3' not in refresh_download
    assert 'cp "$REGISTRY_PATH" research-campaign/state/research.sqlite3' not in refresh_merge


def test_evaluation_registry_and_economics_are_owned_only_by_trusted_control_code() -> None:
    source = _source()
    evaluation = _job_block(source, "evaluate-research", "finalize-publish")

    assert "Checkout trusted research runner control revision" in evaluation
    assert "ref: ${{ github.sha }}" in evaluation
    assert "path: control-src" in evaluation
    assert "candidate-src" not in evaluation
    assert "needs.prepare-control.outputs.candidate_revision" not in evaluation
    assert evaluation.index("Checkout trusted research runner control revision") < evaluation.index(
        "actions/setup-python@v5"
    )
    setup = evaluation.split("- uses: actions/setup-python@v5", 1)[1].split(
        "- name: Download refreshed research stage",
        1,
    )[0]
    assert "cache-dependency-path: control-src/pyproject.toml" in setup
    assert "python -m pip install -e ./control-src" in evaluation
    assert "complete_research_cohort" in evaluation
    assert "cocomelon-research-runner run-artifact" in evaluation
    assert "research-campaign/state/research.sqlite3" in evaluation


def test_research_campaign_uses_bounded_outcome_blind_capture_horizon() -> None:
    source = _source()
    capture = _job_block(source, "capture-control", "candidate-decisions")
    lowered = source.lower()

    assert source.count("record-mainnet-evidence") == 1
    assert "--seconds 1800" in capture
    assert source.count("acquisition-attempt.txt") == 1
    assert "GITHUB_RUN_ID" in source
    assert "GITHUB_RUN_ATTEMPT" in source
    assert "record_runner_attempt_started" in source
    assert "UPDATE research_runner_attempts" in source

    for economic_branch in (
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "profitable",
        "profitability",
        "pnl >",
        "pnl <",
    ):
        assert economic_branch not in lowered


def test_research_campaign_publishes_audit_state_on_failure() -> None:
    source = _source()

    assert "if: ${{ always() }}" in source
    assert "path: research-campaign/" in source
    assert "research-campaign/state/research.sqlite3" in source
    assert "research-campaign/output/" in source
    assert "research-campaign/diagnostics/" in source
    assert "if-no-files-found: error" in source
    assert "authoritative-registry-unavailable.txt" in source


def test_finalizer_falls_back_to_last_registry_stage_and_always_terminalizes() -> None:
    source = _source()
    finalization = _job_block(source, "finalize-publish", "dispatch-dashboard")

    for step_name in (
        "Download evaluated stage for publication",
        "Download refreshed stage fallback",
        "Download control stage fallback",
    ):
        step = finalization.split(f"- name: {step_name}", 1)[1].split("\n      - name:", 1)[0]
        assert "continue-on-error: true" in step

    refreshed = finalization.split("- name: Download refreshed stage fallback", 1)[1].split(
        "- name: Download control stage fallback",
        1,
    )[0]
    control = finalization.split("- name: Download control stage fallback", 1)[1].split(
        "- name: Persist workflow failure in attempt ledger",
        1,
    )[0]
    terminalize = finalization.split(
        "- name: Persist workflow failure in attempt ledger",
        1,
    )[1].split("- name: Upload complete research campaign audit trail", 1)[0]

    for fallback in (refreshed, control):
        assert "hashFiles('research-campaign/state/research.sqlite3') == ''" in fallback
    assert "if: ${{ always() }}" in terminalize


def test_failed_attempt_is_retained_in_next_authoritative_registry_snapshot() -> None:
    source = _source()
    publish = source.split("- name: Publish authoritative research registry", 1)[1]

    assert "hashFiles('research-campaign/state/research.sqlite3')" in publish
    assert "always()" in publish
    assert "success()" not in publish
    assert source.index("Persist workflow failure in attempt ledger") < source.index(
        "Publish authoritative research registry"
    )


def test_research_campaign_never_synthesizes_v4_completeness_from_schedule() -> None:
    source = _source()
    lowered = source.lower()

    assert "mark_v4_registry_complete_through" not in source
    assert "record_v4_interval" not in source
    assert "v4 registry completeness" in lowered
    assert "nominal" not in lowered


def test_finalizer_dispatches_dashboard_through_isolated_actions_write_job() -> None:
    source = _source()
    finalization = _job_block(source, "finalize-publish", "dispatch-dashboard")
    dispatch = _job_block(source, "dispatch-dashboard", None)
    permissions = dispatch.split("steps:", 1)[0]

    assert "needs: finalize-publish" in dispatch
    assert "needs.finalize-publish.result == 'success'" in dispatch
    assert "actions: write" in permissions
    assert "GH_TOKEN: ${{ github.token }}" in dispatch
    assert "actions/workflows/research-dashboard.yml/dispatches" in dispatch
    assert "--method POST" in dispatch
    assert "-f ref=main" in dispatch
    assert "actions/checkout" not in dispatch
    assert "research.sqlite3" not in dispatch
    assert "record-mainnet-evidence" not in dispatch
    assert "actions: write" not in finalization.split("steps:", 1)[0]
