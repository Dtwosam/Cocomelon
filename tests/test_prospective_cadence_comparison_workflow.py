from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-cadence-comparison.yml"
)


def test_prospective_comparison_is_pinned_and_research_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "Prospective Cadence Model Comparison" in source
    assert "Continuous Mainnet Paper Trader" in source
    assert "actions: read" in source
    assert "contents: read" in source
    assert "issues: write" in source
    assert "efde8803da35d16529157729c2080a1cd99f9a4a" in source
    assert "34acb37c2f06c53eb81fe298db63ce4093c8de7b" in source
    assert "continuous-paper-cadence-shadow-" in source
    assert "continuous-paper-learning-features-" in source
    assert "continuous-paper-state-" not in source
    assert "cadence_microstructure_prospective" in source
    assert "cadence_tree_prospective_baseline" in source
    assert "paired comparison decision-id sets differ" in source
    assert "frozen_training_rows_sha256" in source
    assert 'COMPARISON_ISSUE: "679"' in source
    assert "gh workflow run" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_prospective_comparison_checks_same_future_rows() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert '"prospective_start_ms"' in source
    assert '"prospective_rows"' in source
    assert '"required_prospective_rows"' in source
    assert '"boundary_ms","market","direction","realized_net_return"' in source
    assert "microstructure_minus_baseline_net_return_sum" in source
    assert "microstructure_only_realized_net_return_sum" in source
    assert "baseline_only_realized_net_return_sum" in source


def test_prospective_comparison_catchup_and_no_evidence_contract() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "actions/workflows/continuous-paper.yml/"
        "runs?status=success&branch=main&per_page=100"
    ) in source
    assert (
        "actions/runs?status=success&per_page=100"
        not in source
    )
    assert "cadence-model-comparison-no-evidence.json" in source
    assert "cadence-model-comparison-no-evidence-" in source
    assert '"status": "no_evidence"' in source
    assert (
        '"reason": "compact_research_artifacts_unavailable"'
        in source
    )
    assert "cat > /tmp/comparison-status.md <<EOF" not in source
    assert 'Path("/tmp/comparison-status.md").write_text' in source
