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
    assert "from cocomelon.research.cohort import build_research_cohort" in source
    assert "cocomelon-research-runner run-artifact" in source
    assert "research-authoritative-registry" in source

    for forbidden in (
        "evidence-campaign-v4-scheduled",
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


def test_research_campaign_pins_runtime_to_candidate_code_revision() -> None:
    source = _source()

    assert "Resolve candidate code revision from authoritative registry" in source
    assert "SELECT code_revision FROM research_candidates WHERE candidate_id = ?" in source
    assert "candidate_revision: ${{ steps.candidate.outputs.revision }}" in source
    assert "Checkout candidate code revision" in source
    assert "ref: ${{ needs.prepare-control.outputs.candidate_revision }}" in source
    resolve_index = source.index("Resolve candidate code revision from authoritative registry")
    checkout_index = source.index("Checkout candidate code revision")
    assert resolve_index < checkout_index
    assert checkout_index < source.index("Install Cocomelon")
    assert source.index("Install Cocomelon") < source.index("record-mainnet-evidence")


def test_candidate_checkout_preserves_restored_authoritative_registry() -> None:
    source = _source()
    checkout = source.split("- name: Checkout candidate code revision", 1)[1].split(
        "- name: Install Cocomelon",
        1,
    )[0]

    assert "clean: false" in checkout
    assert "clean: true" not in checkout
    assert "persist-credentials: false" in checkout
    assert source.index("Restore authoritative research registry") < source.index(
        "Checkout candidate code revision"
    )


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


def test_actions_token_is_not_exposed_to_candidate_controlled_processes() -> None:
    source = _source()
    prepare = _job_block(source, "prepare-control", "candidate-build")
    candidate = _job_block(source, "candidate-build", "refresh-authority")
    refresh = _job_block(source, "refresh-authority", "evaluate-research")
    evaluation = _job_block(source, "evaluate-research", "finalize-publish")
    finalization = _job_block(source, "finalize-publish", None)
    refresh_download = source.split(
        "- name: Download refreshed V4 authority after acquisition",
        1,
    )[1].split("- name: Merge refreshed V4 authority after acquisition", 1)[0]
    refresh_merge = source.split(
        "- name: Merge refreshed V4 authority after acquisition",
        1,
    )[1].split(
        "- name: Upload refreshed research stage",
        1,
    )[0]

    assert "actions: read" in prepare
    assert "actions: read" in refresh
    for candidate_controlled in (candidate, evaluation, finalization):
        assert "actions: none" in candidate_controlled
        assert "GH_TOKEN:" not in candidate_controlled
    assert source.count("GH_TOKEN: ${{ github.token }}") == 2
    assert "GH_TOKEN: ${{ github.token }}" in prepare
    assert "GH_TOKEN: ${{ github.token }}" in refresh_download
    assert "GH_TOKEN:" not in refresh_merge
    assert "/usr/bin/gh api" in prepare
    assert "/usr/bin/gh api" in refresh_download
    assert "python" not in refresh_download
    assert "cocomelon" not in refresh_download.lower()
    assert "merge_v4_authority_snapshot" in refresh_merge
    assert "persist-credentials: false" in prepare.split(
        "Checkout research campaign control revision",
        1,
    )[1].split("- uses: actions/setup-python", 1)[0]


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


def test_research_campaign_refreshes_v4_authority_after_capture_before_evaluation() -> None:
    source = _source()
    refresh_download = source.split(
        "- name: Download refreshed V4 authority after acquisition",
        1,
    )[1].split("- name: Merge refreshed V4 authority after acquisition", 1)[0]
    refresh_merge = source.split(
        "- name: Merge refreshed V4 authority after acquisition",
        1,
    )[1].split(
        "- name: Upload refreshed research stage",
        1,
    )[0]

    assert source.index("Acquire one public mainnet research cohort") < source.index(
        "Download refreshed V4 authority after acquisition"
    )
    assert source.index("Download refreshed V4 authority after acquisition") < source.index(
        "Merge refreshed V4 authority after acquisition"
    )
    assert source.index("Merge refreshed V4 authority after acquisition") < source.index(
        "Evaluate authenticated research attempt"
    )
    assert "/actions/artifacts?name=research-authoritative-registry" in refresh_download
    assert '.path == ".github/workflows/research-v4-registry-sync.yml"' in refresh_download
    assert '.head_branch == "main"' in refresh_download
    assert '.status == "completed"' in refresh_download
    assert '.conclusion == "success"' in refresh_download
    assert "merge_v4_authority_snapshot" in refresh_merge
    assert "research-campaign/state/research.sqlite3" in refresh_merge
    assert "research-campaign/state/refreshed-v4-authority.sqlite3" in refresh_merge
    assert 'cp "$REGISTRY_PATH" research-campaign/state/research.sqlite3' not in refresh_download
    assert 'cp "$REGISTRY_PATH" research-campaign/state/research.sqlite3' not in refresh_merge


def test_research_campaign_uses_one_outcome_blind_acquisition_identity() -> None:
    source = _source()
    lowered = source.lower()

    assert source.count("record-mainnet-evidence") == 1
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


def test_finalizer_falls_back_to_last_available_stage_and_always_terminalizes() -> None:
    source = _source()
    finalization = _job_block(source, "finalize-publish", None)

    for step_name in (
        "Download evaluated stage for publication",
        "Download refreshed stage fallback",
        "Download candidate stage fallback",
        "Download control stage fallback",
    ):
        step = finalization.split(f"- name: {step_name}", 1)[1].split("\n      - name:", 1)[0]
        assert "continue-on-error: true" in step

    refreshed = finalization.split("- name: Download refreshed stage fallback", 1)[1].split(
        "- name: Download candidate stage fallback",
        1,
    )[0]
    candidate = finalization.split("- name: Download candidate stage fallback", 1)[1].split(
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

    for fallback in (refreshed, candidate, control):
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