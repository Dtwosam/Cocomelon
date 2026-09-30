from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-cadence-actual-trade-overlap.yml"
)


def test_overlap_workflow_is_research_only_and_non_gating() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Prospective Cadence Actual Trade Overlap" in source
    assert 'STATUS_ISSUE: "704"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "actions: write" not in source
    assert "update_prospective_trade_overlap_ledger.py" in source
    assert "continuous-paper-learning-source-" in source
    assert "cadence-microstructure-prediction-ledger-" in source
    assert "diagnostic only" in source
    assert "does not change the frozen readiness gate" in source
    assert "gh workflow run" not in source


def test_overlap_workflow_fails_closed_on_mutation() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Publish blocked overlap status" in source
    assert "Fail closed on overlap drift" in source
    assert "**Status:** BLOCKED" in source
    assert "Prior immutable " in source
    assert "remains authoritative." in source
    assert "exit 1" in source


def test_overlap_workflow_waits_for_compact_source_without_backfill() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "waiting for first compact paper learning source" in source
    assert "No fuzzy or historical backfill match is attempted" in source
    assert "journal.sqlite3" in source
    assert "strategy_decision_id == prediction decision_id" in source
    assert 'cron: "*/15 * * * *"' in source
    assert "cancel-in-progress: false" in source


def test_overlap_workflow_keeps_one_append_only_artifact() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cadence-prospective-actual-trade-overlap.json" in source
    assert "name: cadence-prospective-actual-trade-overlap" in source
    assert "retention-days: 90" in source


def test_overlap_status_metadata_is_not_shell_interpreted() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cat > /tmp/status.md <<EOF" not in source
    assert source.count("Path(\"/tmp/status.md\").write_text(") == 3
    assert "os.environ['PREDICTION_RUN_ID']" in source
    assert "os.environ['PAPER_RUN_ID']" in source
