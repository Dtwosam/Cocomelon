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
