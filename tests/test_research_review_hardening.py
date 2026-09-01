from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.runner_history import (
    load_runner_attempts,
    record_runner_attempt_started,
)

WORKFLOW = Path(".github/workflows/research-campaign-scheduled.yml")
SYNC_WORKFLOW = Path(".github/workflows/research-v4-registry-sync.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(source: str, name: str, next_name: str | None) -> str:
    block = source.split(f"\n  {name}:\n", 1)[1]
    if next_name is not None:
        block = block.split(f"\n  {next_name}:\n", 1)[0]
    return block


def test_running_attempt_source_interval_is_bound_once_before_evaluation(tmp_path: Path) -> None:
    history = import_module("cocomelon.research.runner_history")
    binder = history.bind_runner_attempt_source_interval
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        record_runner_attempt_started(
            registry.connection,
            attempt_id="attempt-1",
            candidate_id="candidate-1",
            batch_id="batch-1",
            source_id="source-1",
            artifact_root="research-campaign/output",
        )
        binder(
            registry.connection,
            attempt_id="attempt-1",
            start_ms=1_000,
            end_ms=2_000,
        )
        binder(
            registry.connection,
            attempt_id="attempt-1",
            start_ms=1_000,
            end_ms=2_000,
        )
        with pytest.raises(ResearchRegistryError, match="different source interval"):
            binder(
                registry.connection,
                attempt_id="attempt-1",
                start_ms=1_001,
                end_ms=2_000,
            )
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert len(attempts) == 1
    assert attempts[0].start_ms == 1_000
    assert attempts[0].end_ms == 2_000


def test_capture_binds_candidate_touch_before_any_candidate_runtime() -> None:
    source = _source()
    capture = _job(source, "capture-control", "candidate-decisions")
    decisions = _job(source, "candidate-decisions", "refresh-authority")

    assert "Bind trusted capture interval before candidate execution" in capture
    assert "bind_runner_attempt_source_interval" in capture
    assert "record_touched_interval" in capture
    assert (
        "research-capture-control-stage-${{ github.run_id }}-${{ github.run_attempt }}"
        in capture
    )
    assert (
        "research-capture-source-stage-${{ github.run_id }}-${{ github.run_attempt }}"
        in capture
    )
    assert source.index("Bind trusted capture interval before candidate execution") < source.index(
        "Run candidate strategy against trusted contexts"
    )
    assert "research.sqlite3" not in decisions
    assert (
        "research-capture-source-stage-${{ github.run_id }}-${{ github.run_attempt }}"
        in decisions
    )
    assert "research-capture-control-stage" not in decisions


def test_committed_checkpoint_registry_is_transferred_before_secondary_stage_upload() -> None:
    source = _source()
    evaluation = _job(source, "evaluate-research", "finalize-publish")
    finalization = _job(source, "finalize-publish", None)

    runner_index = evaluation.index("Evaluate authenticated research attempt")
    publish_index = evaluation.index("Publish committed authoritative research registry")
    stage_index = evaluation.index("Upload evaluated research stage")
    assert runner_index < publish_index < stage_index
    publish = evaluation[publish_index:stage_index]
    assert "name: research-authoritative-registry" in publish
    assert "research-campaign/state/research.sqlite3" in publish
    assert "continue-on-error: true" in publish
    assert "registry_published" in source

    assert "Download committed authoritative registry from evaluation" in finalization
    assert "research-authoritative-registry" in finalization
    fallback = finalization.split("- name: Download refreshed stage fallback", 1)[1]
    assert "hashFiles('research-campaign/state/research.sqlite3') == ''" in fallback
    final_publish = finalization.split("- name: Publish authoritative research registry", 1)[1]
    assert "needs.evaluate-research.outputs.registry_published != 'success'" in final_publish


def test_final_audit_retains_capture_and_candidate_failure_evidence_independently() -> None:
    source = _source()
    finalization = _job(source, "finalize-publish", None)

    capture = finalization.split("- name: Download capture evidence for final audit", 1)[1].split(
        "\n      - name:",
        1,
    )[0]
    decisions = finalization.split(
        "- name: Download candidate decision evidence for final audit",
        1,
    )[1].split("\n      - name:", 1)[0]
    assert "continue-on-error: true" in capture
    assert (
        "research-capture-source-stage-${{ github.run_id }}-${{ github.run_attempt }}"
        in capture
    )
    assert "research-campaign/audit/capture" in capture
    assert "continue-on-error: true" in decisions
    assert "research-decision-stage-${{ github.run_id }}-${{ github.run_attempt }}" in decisions
    assert "research-campaign/audit/decisions" in decisions
    audit = finalization.split("- name: Upload complete research campaign audit trail", 1)[1]
    assert "path: research-campaign/" in audit
    assert "retention-days: 30" in audit


def test_trusted_v4_registry_sync_producer_exists_before_research_schedule_can_run() -> None:
    source = SYNC_WORKFLOW.read_text(encoding="utf-8")
    lowered = source.lower()

    assert "name: Research V4 Acquisition Authority Sync" in source
    assert "research-authoritative-registry" in source
    assert ".github/workflows/evidence-campaign-v4-scheduled.yml" in source
    assert "v4-acquisition-stage-" in source
    assert "actions: read" in source
    assert "apply_v4_authority_inventory" in source
    assert "recording-session.json" in source
    assert "finished-at-utc.txt" in source
    assert "--paginate" in source
    for forbidden in (
        "net_pnl",
        "mean_net_r",
        "posterior_probability",
        "profit_factor",
        "final_equity",
        "v4-mainnet-corpus",
        "phase9_v4_one_shot",
    ):
        assert forbidden not in lowered


def test_v4_sync_bootstrap_creates_configured_candidate_idempotently(tmp_path: Path) -> None:
    bootstrap = import_module("cocomelon.research.bootstrap")
    ensure = bootstrap.ensure_bootstrap_candidate
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        first = ensure(
            registry,
            candidate_id="scheduled-research-root",
            code_revision="a" * 40,
        )
        second = ensure(
            registry,
            candidate_id="scheduled-research-root",
            code_revision="b" * 40,
        )
        stored = registry.load_candidate("scheduled-research-root")
    finally:
        registry.close()

    assert first.candidate_id == "scheduled-research-root"
    assert first.code_revision == "a" * 40
    assert second == first
    assert stored == first
    assert len(first.config_digest) == 64


def test_v4_sync_seeds_candidate_before_first_authoritative_publication() -> None:
    source = SYNC_WORKFLOW.read_text(encoding="utf-8")

    seed_index = source.index("Ensure configured research bootstrap candidate exists")
    inventory_index = source.index("Snapshot already-recorded V4 acquisition identities")
    publish_index = source.index("Publish synchronized authoritative research registry")
    assert seed_index < inventory_index < publish_index
    assert "RESEARCH_CANDIDATE_ID: ${{ vars.RESEARCH_CANDIDATE_ID }}" in source
    assert "ensure_bootstrap_candidate" in source


def test_research_requests_post_capture_authority_and_requires_covering_watermark() -> None:
    source = _source()
    refresh = _job(source, "refresh-authority", "evaluate-research")

    assert "actions: write" in refresh
    assert "Dispatch post-capture V4 authority synchronization" in refresh
    assert "research-v4-registry-sync.yml/dispatches" in refresh
    assert "BOUND_END_MS" in refresh
    assert "complete_through_ms" in refresh
    assert "does not cover bound research interval" in refresh
    assert source.index("Bind trusted capture interval before candidate execution") < source.index(
        "Dispatch post-capture V4 authority synchronization"
    )


def test_v4_sync_enumerates_every_workflow_run_attempt_independently() -> None:
    source = SYNC_WORKFLOW.read_text(encoding="utf-8")

    assert 'for ATTEMPT in $(seq 1 "$LATEST_ATTEMPT")' in source
    assert "/actions/runs/$RUN_ID/attempts/$ATTEMPT" in source
    assert "/actions/runs/$RUN_ID/attempts/$ATTEMPT/jobs?per_page=100" in source
    assert "v4-acquisition-stage-${RUN_ID}-attempt-${ATTEMPT}" in source
    assert "github-v4-${RUN_ID}-attempt-${ATTEMPT}" in source


def test_authoritative_registry_publishers_share_one_concurrency_group() -> None:
    campaign = _source()
    sync = SYNC_WORKFLOW.read_text(encoding="utf-8")
    group = "group: research-authoritative-registry-publisher"

    assert group in _job(sync, "synchronize", None)
    assert group in _job(campaign, "evaluate-research", "finalize-publish")
    assert group in _job(campaign, "finalize-publish", None)


def test_persisted_runner_artifact_root_matches_absolute_cli_request() -> None:
    source = _source()
    prepare = _job(source, "prepare-control", "candidate-build")
    evaluation = _job(source, "evaluate-research", "finalize-publish")

    assert (
        'artifact_root=str(Path(os.environ["GITHUB_WORKSPACE"]) / "research-campaign" / "output")'
        in prepare
    )
    assert '--artifact-root "$GITHUB_WORKSPACE/research-campaign/output"' in evaluation


def test_evaluation_rebases_latest_authority_after_acquiring_publisher_lock() -> None:
    source = _source()
    evaluation = _job(source, "evaluate-research", "finalize-publish")

    assert "group: research-authoritative-registry-publisher" in evaluation
    assert "actions: read" in evaluation
    assert "Rebase staged registry onto latest trusted authority under publisher lock" in evaluation
    rebase_index = evaluation.index(
        "Rebase staged registry onto latest trusted authority under publisher lock"
    )
    runner_index = evaluation.index("Evaluate authenticated research attempt")
    assert rebase_index < runner_index
    rebase = evaluation[rebase_index:runner_index]
    assert "GH_TOKEN: ${{ github.token }}" in rebase
    assert "/actions/artifacts?name=research-authoritative-registry" in rebase
    assert '.path == ".github/workflows/research-v4-registry-sync.yml"' in rebase
    assert "merge_v4_authority_snapshot" in rebase
    assert "candidate-src" not in evaluation


def test_successful_final_audit_retains_evaluated_products_independently() -> None:
    source = _source()
    finalization = _job(source, "finalize-publish", None)

    evaluated = finalization.split(
        "- name: Download evaluated products for final audit",
        1,
    )[1].split("\n      - name:", 1)[0]
    assert "if: ${{ always() }}" in evaluated
    assert "continue-on-error: true" in evaluated
    assert "research-evaluated-stage-${{ github.run_id }}-${{ github.run_attempt }}" in evaluated
    assert "research-campaign/audit/evaluated" in evaluated
    assert finalization.index("Download evaluated products for final audit") < finalization.index(
        "Upload complete research campaign audit trail"
    )


def test_success_completion_rejects_mismatched_prebound_interval(tmp_path: Path) -> None:
    bootstrap = import_module("cocomelon.research.bootstrap")
    history = import_module("cocomelon.research.runner_history")
    checkpoint = import_module("cocomelon.research.checkpoint_commit")
    registry = ResearchRegistry(tmp_path / "research.sqlite3")
    try:
        bootstrap.ensure_bootstrap_candidate(
            registry,
            candidate_id="candidate-1",
            code_revision="a" * 40,
        )
        record_runner_attempt_started(
            registry.connection,
            attempt_id="attempt-1",
            candidate_id="candidate-1",
            batch_id="batch-1",
            source_id="source-1",
            artifact_root="/trusted/research-campaign/output",
        )
        history.bind_runner_attempt_source_interval(
            registry.connection,
            attempt_id="attempt-1",
            start_ms=1_000,
            end_ms=2_000,
        )
        history.claim_runner_attempt_evaluation(
            registry.connection,
            attempt_id="attempt-1",
        )
        registry.connection.execute(
            """
            INSERT INTO research_batches (
                batch_id, candidate_id, source_id, replay_run_id,
                start_ms, end_ms, status, contamination_v4_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'admitted', NULL)
            """,
            ("batch-1", "candidate-1", "source-1", "replay-1", 1_001, 2_000),
        )
        registry.connection.commit()

        registry.connection.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(ResearchRegistryError, match="different source interval"):
                checkpoint.complete_runner_attempt_success_uncommitted(
                    registry.connection,
                    attempt_id="attempt-1",
                    candidate_id="candidate-1",
                    batch_id="batch-1",
                    report_id="report-1",
                )
        finally:
            registry.connection.rollback()
        attempts = load_runner_attempts(registry.connection)
    finally:
        registry.close()

    assert len(attempts) == 1
    assert attempts[0].start_ms == 1_000
    assert attempts[0].end_ms == 2_000


def test_finalizer_rebases_fallback_registry_after_acquiring_publisher_lock() -> None:
    source = _source()
    finalization = _job(source, "finalize-publish", None)

    assert "group: research-authoritative-registry-publisher" in finalization
    assert "actions: read" in finalization
    assert "Rebase recovered fallback registry onto latest trusted authority" in finalization
    rebase_index = finalization.index(
        "Rebase recovered fallback registry onto latest trusted authority"
    )
    publish_index = finalization.index("Publish authoritative research registry")
    assert rebase_index < publish_index
    rebase = finalization[rebase_index:publish_index]
    assert "GH_TOKEN: ${{ github.token }}" in rebase
    assert "/actions/artifacts?name=research-authoritative-registry" in rebase
    assert '.path == ".github/workflows/research-v4-registry-sync.yml"' in rebase
    assert "merge_v4_authority_snapshot" in rebase
    assert "needs.evaluate-research.outputs.registry_published != 'success'" in rebase
    publish = finalization[publish_index:]
    assert "steps.rebase-fallback-authority.outcome == 'success'" in publish


def test_status_records_authority_sync_as_implemented_and_advances_next_action() -> None:
    status = Path("docs/STATUS.md").read_text(encoding="utf-8")
    lowered = status.lower()
    next_action = status.split("## Exact next action", 1)[1]

    assert ".github/workflows/research-v4-registry-sync.yml" in status
    assert "implemented" in lowered
    assert "remaining operational dependency is a separate authoritative v4" not in lowered
    assert "Add a separate authoritative V4 interval/completeness synchronization path" not in next_action
    assert "Observe the implemented authoritative V4 interval/completeness synchronization path" in next_action
