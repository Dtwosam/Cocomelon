from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-corpus-curator.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_curator_checks_for_existing_one_shot_phase9_artifacts() -> None:
    text = _text()

    assert "v2-phase9-frozen-snapshot" in text
    assert "v2-phase9-evaluation" in text
    assert "phase9-evaluation-artifacts.json" in text
    assert "phase9-snapshot-artifacts.json" in text


def test_curator_prepares_and_uploads_frozen_snapshot_before_evaluation() -> None:
    text = _text()

    prepare = "cocomelon-mainnet-evidence prepare-phase9-v2"
    upload = "name: v2-phase9-frozen-snapshot"
    evaluate = "cocomelon-mainnet-evidence evaluate-phase9-v2"
    assert prepare in text
    assert upload in text
    assert evaluate in text
    assert text.index(prepare) < text.index(upload) < text.index(evaluate)
    assert "phase9-readiness.json" in text
    assert "ready_for_untouched_evaluation" in text


def test_curator_never_rolls_or_replaces_existing_oos_snapshot() -> None:
    text = _text()

    assert "PHASE9_SNAPSHOT_EXISTS" in text
    assert "PHASE9_EVALUATION_EXISTS" in text
    assert "if-no-files-found: error" in text
    assert "retention-days: 90" in text
    assert "one_shot_oos" in text
    assert "COCOMELON_EXECUTION_MODE: live" not in text
    assert "testnet" not in text.lower()
