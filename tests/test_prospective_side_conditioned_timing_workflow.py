from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-side-conditioned-timing.yml"
)


def test_timing_audit_is_pinned_and_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Prospective Side-Conditioned Timing Audit" in source
    assert "Continuous Mainnet Paper Trader" in source
    assert 'cron: "47 * * * *"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "31c73c809b2c6cce2d189c87715d4f9d7c18c290" in source
    assert 'TIMING_ISSUE: "682"' in source
    assert "continuous-paper-side-conditioned-timing-" in source
    assert "continuous-paper-state-" not in source
    assert "evaluate_prospective_side_conditioned_delay.py" in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_timing_audit_cannot_override_candidate_boundary() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "--started-at" not in source
    assert "--start-ms" not in source
    assert "prospective-side-conditioned-delay-state.json" in source
    assert "latest_evidence_eligible_with_timing_artifact" in source
    assert 'resolution_mode="durable_handoff_event"' in source
    assert "ready_for_review" in source
    assert "Robustness is descriptive only" in source


def test_continuous_paper_uploads_compact_timing_state() -> None:
    source = Path(
        ".github/workflows/continuous-paper.yml"
    ).read_text(encoding="utf-8")

    assert "continuous-paper-side-conditioned-timing-" in source
    assert "continuous-paper-state/journal.sqlite3" in source
    assert (
        "continuous-paper-state/"
        "delayed-entry-execution-shadow-state.json"
    ) in source
    assert (
        "continuous-paper-state/"
        "delayed-entry-120s-execution-shadow-state.json"
    ) in source
    assert (
        "continuous-paper-state/"
        "prospective-side-conditioned-delay-state.json"
    ) in source


def test_blocked_status_preserves_runtime_metadata_without_shell_backticks() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cat > /tmp/timing-status.md <<EOF" not in source
    assert "python - <<'PY' > /tmp/timing-status.md" in source
    assert "os.environ['SOURCE_RUN_ID']" in source
    assert "os.environ['SOURCE_RUN_ATTEMPT']" in source
    assert "os.environ['SOURCE_RESOLUTION_MODE']" in source
    assert "os.environ['TIMING_SHA']" in source
