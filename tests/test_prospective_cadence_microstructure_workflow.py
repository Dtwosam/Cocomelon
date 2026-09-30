from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW = Path(
    ".github/workflows/prospective-cadence-microstructure.yml"
)


def _workflow() -> dict[str, object]:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_prospective_microstructure_audit_is_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    payload = _workflow()

    assert "workflow_run" in payload[True]
    assert (
        payload[True]["workflow_run"]["workflows"]
        == ["Continuous Mainnet Paper Trader"]
    )
    assert payload["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
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
