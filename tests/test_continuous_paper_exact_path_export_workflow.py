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
    assert "github.event.workflow_run.conclusion == 'success'" in source
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
    assert 'run.get("conclusion") != "success"' in source
    assert "source run attempt mismatch" in source
    assert "source repository mismatch" in source
    assert (
        'artifact_name="continuous-paper-state-$source_run_id-$source_attempt"'
        in source
    )
    assert "expected exactly one non-expired source artifact" in source


def test_exact_path_export_streams_only_small_research_slice() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "python scripts/stream_zip_member.py "
        "continuous-paper-state.tar"
    ) in source
    assert "./trade-paths" in source
    assert "./session-summary.json" in source
    assert "paper.sqlite3" not in source
    assert "facts.sqlite3" not in source
    assert "journal.sqlite3" not in source
    assert "trade_path_tree_sha256" in source
    assert "session trade-path count does not match exported records" in source
    assert "continuous-paper-exact-paths-" in source
