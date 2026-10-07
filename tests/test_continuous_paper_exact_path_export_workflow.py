from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/continuous-paper-exact-path-export.yml"
)


def test_exact_path_export_is_separate_research_workflow() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Continuous Paper Exact Path Export" in source
    assert 'workflows:' in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert "github.event.workflow_run.conclusion == 'success'" not in source
    assert "EVENT_CONCLUSION:" in source
    assert "paper_run_is_evidence_eligible()" in source
    assert "steps.source.outputs.eligible == 'true'" in source
    assert "workflow_dispatch:" in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "execution_authority" in source
    assert "promotion_authority" in source


def test_exact_path_export_binds_exact_source_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("head_branch") != "main"' in source
    assert 'run.get("status") != "completed"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert (
        'local expected_name="continuous-paper-state-'
        '$candidate_run_id-$candidate_attempt"'
        in source
    )
    assert "latest_evidence_eligible_with_state_artifact" in source
    assert "expected at most one non-expired source artifact" in source


def test_exact_path_export_streams_only_small_research_slice() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "python scripts/stream_zip_member.py "
        "continuous-paper-state.tar"
    ) in source
    assert "./trade-paths/records" in source
    assert "./trade-paths \\" not in source
    assert "./session-summary.json" in source
    assert "paper.sqlite3" not in source
    assert "facts.sqlite3" not in source
    assert "journal.sqlite3" not in source
    assert "trade_path_tree_sha256" in source
    assert "session trade-path count does not match exported records" in source
    assert "continuous-paper-exact-paths-" in source


def test_exact_path_export_accepts_only_durable_handoff_tail_failures() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "paper_run_is_evidence_eligible()" in source
    assert '"Run continuous paper trader"' in source
    assert '"Measure durable continuous paper state"' in source
    assert '"Upload durable continuous paper state"' in source
    assert 'frozenset({"Fail closed on upgrade handoff source"})' in source
    assert '"Queue fallback exact successor continuous paper worker"' in source
    assert '"Queue exact successor from fast resume"' in source
    assert 'resolution_mode="durable_handoff_event"' in source
    assert "latest_evidence_eligible_with_state_artifact" in source
    assert "selected source paper run is not evidence-eligible" in source


def test_automated_source_resolution_prefers_newest_completed_run() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'sorted(runs, key=lambda item: item["id"], reverse=True)' in source
    assert 'branch=main&status=completed&per_page=100' in source
    assert 'if [ "$candidate_run_id" = "$EVENT_RUN_ID" ]; then' in source
