from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-cadence-prediction-ledger.yml"
)


def test_prediction_ledger_workflow_is_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Prospective Cadence Microstructure Audit" in source
    assert "prospective-cadence-prediction-ledger" in source
    assert 'PREDICTION_LEDGER_ISSUE: "687"' in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "update_cadence_prospective_prediction_ledger.py" in source
    assert "cadence-microstructure-prediction-ledger-" in source
    assert "cancel-in-progress: false" in source
    assert "workflow_dispatch:" in source
    assert "schedule:" not in source


def test_prediction_ledger_workflow_fails_closed_on_drift() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Publish blocked ledger status" in source
    assert "Fail closed on ledger drift" in source
    assert "**Status:** BLOCKED" in source
    assert "Prior canonical" in source
    assert "exit 1" in source


def test_prediction_ledger_does_not_dispatch_or_trade() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions: write" not in source
    assert "workflow_dispatch" in source
    assert "continuous-paper.yml" not in source
    assert "gh workflow run" not in source
    assert "execution_authority" not in source
