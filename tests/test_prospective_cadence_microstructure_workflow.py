from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-cadence-microstructure.yml"
)


def test_prospective_microstructure_audit_is_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_run:" in source
    assert "Continuous Mainnet Paper Trader" in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "continuous-paper-cadence-shadow-" in source
    assert "continuous-paper-learning-features-" in source
    assert "continuous-paper-state-" not in source
    assert (
        "evaluate_cadence_microstructure_prospective.py"
        in source
    )
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_prospective_microstructure_audit_preserves_freeze() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "--prospective-start-ms" not in source
    assert (
        "ref: efde8803da35d16529157729c2080a1cd99f9a4a"
        in source
    )
    assert (
        "FROZEN_CANDIDATE_SHA: "
        "efde8803da35d16529157729c2080a1cd99f9a4a"
        in source
    )
    assert (
        "cadence-microstructure-prospective.json"
        in source
    )
    assert "development_qualified" in source
    assert "compact research artifacts unavailable" in source


def test_prospective_audit_publishes_only_research_status_issue() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "issues: write" in source
    assert 'PROSPECTIVE_STATUS_ISSUE: "674"' in source
    assert "Publish canonical prospective status" in source
    assert "Publish unavailable prospective status" in source
    assert "repos/$GITHUB_REPOSITORY/issues/$PROSPECTIVE_STATUS_ISSUE" in source
    assert "--method PATCH" in source
    assert "issue 469" not in source.lower()
    assert "issues/469" not in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_prospective_status_keeps_immutable_candidate_identity() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "FROZEN_CANDIDATE_SHA: "
        "efde8803da35d16529157729c2080a1cd99f9a4a"
        in source
    )
    assert (
        "frozen_training_rows_sha256"
        in source
    )
    assert "Historical/touched outcomes do not count" in source
    assert "No paper orders are changed by this audit" in source


def test_prospective_audit_catches_up_missed_success_events() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "23 * * * *"' in source
    assert "Resolve source paper run" in source
    assert "EVENT_SOURCE_CONCLUSION" in source
    assert 'EVENT_SOURCE_CONCLUSION" == "success"' in source
    assert "latest_success_catchup" in source
    assert (
        "actions/workflows/continuous-paper.yml/runs?"
        "branch=main&status=completed&per_page=100"
        in source
    )
    assert "latest_success_with_cadence_artifacts" in source
    assert '.path == ".github/workflows/continuous-paper.yml"' in source
    assert "SOURCE_RUN_ID=$source_run_id" in source
    assert "SOURCE_RUN_ATTEMPT=$source_run_attempt" in source
    assert "SOURCE_RESOLUTION_MODE=$resolution_mode" in source
    assert (
        "github.event.workflow_run.conclusion == 'success'"
        not in source
    )


def test_manual_prospective_audit_keeps_exact_source_identity() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'EVENT_NAME" == "workflow_dispatch"' in source
    assert 'source_run_id="$INPUT_SOURCE_RUN_ID"' in source
    assert 'source_run_attempt="$INPUT_SOURCE_RUN_ATTEMPT"' in source
    assert 'resolution_mode="manual_exact"' in source
