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
        "cadence-microstructure-prospective.json"
        in source
    )
    assert "development_qualified" in source
    assert "compact research artifacts unavailable" in source
