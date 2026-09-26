from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/continuous-paper-learning-cycle.yml")
PYPROJECT = Path("pyproject.toml")


def _source() -> str:
    assert WORKFLOW.is_file()
    return WORKFLOW.read_text(encoding="utf-8")


def test_continuous_paper_cycle_follows_exact_learning_sync() -> None:
    source = _source()
    assert "Continuous Paper Research Learning Cycle" in source
    assert 'workflows: ["Continuous Paper Learning Evidence Sync"]' in source
    assert "types: [completed]" in source
    assert "workflow_dispatch:" in source
    assert "upstream_run_id:" in source
    assert 'run.get("path") != ".github/workflows/continuous-paper-learning-evidence.yml"' in source
    assert 'run.get("name") != "Continuous Paper Learning Evidence Sync"' in source
    assert "continuous-paper-learning-state" in source
    assert 'digest.startswith("sha256:")' in source


def test_continuous_paper_cycle_revalidates_state_before_learning() -> None:
    source = _source()
    assert "last-sync.json" in source
    assert "readiness.json" in source
    assert "last-source-receipt.json" in source
    assert 'sync.get("command") != "continuous-paper-learning-sync"' in source
    assert 'readiness.get("evidence_kind") != "paper_execution"' in source
    assert 'receipt.get("source_kind") != "continuous_paper_worker"' in source
    assert "LearningEvidenceLedger" in source
    assert "LearningFeatureSnapshotStore" in source
    assert "persisted ledger digest changed" in source
    assert "persisted feature digest changed" in source


def test_continuous_paper_cycle_uses_frozen_learner_without_promotion() -> None:
    source = _source()
    assert "cocomelon-learning-cycle" in source
    assert 'if [ "$STATUS" -ne 0 ] && [ "$STATUS" -ne 3 ]; then' in source
    assert "settled chronological train records" in source
    assert "validation records" in source
    assert "candidate freeze: disabled" in source
    assert "cocomelon-learning-candidate-freeze" not in source
    assert "promotion eligible: false" in source
    assert "execution enabled: false" in source
    assert "api.hyperliquid" not in source
    assert "private_key" not in source.lower()


def test_continuous_paper_cycle_cli_is_packaged() -> None:
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert (
        'cocomelon-learning-cycle = "cocomelon.learning_cycle_cli:main"'
        in pyproject
    )


def test_continuous_paper_cycle_artifact_binds_exact_sync_identity() -> None:
    source = _source()
    publish = source.split(
        "- name: Publish immutable continuous-paper learning cycle",
        1,
    )[1]
    assert (
        "continuous-paper-learning-cycle-${{ steps.state.outputs.run_id }}-"
        "${{ steps.state.outputs.run_attempt }}"
    ) in publish
    assert "retention-days: 90" in publish
