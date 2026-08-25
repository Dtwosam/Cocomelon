from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/evidence-corpus-curator.yml")
FROZEN_EVALUATOR_SHA = "629db6294822c97690c006591802f8a47e08652e"


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


def test_curator_preserves_corpus_if_phase9_downstream_fails() -> None:
    text = _text()

    upload = text.index("name: v2-mainnet-corpus")
    guard = text[max(0, upload - 300) : upload]
    assert "always()" in guard
    assert "steps.aggregate.outcome == 'success'" in guard


def test_curator_uses_immutable_phase9_evaluator_revision() -> None:
    text = _text()

    checkout = f"ref: {FROZEN_EVALUATOR_SHA}"
    install = "python -m pip install -e ./phase9-tooling"
    prepare = "cocomelon-mainnet-evidence prepare-phase9-v2"
    evaluate = "cocomelon-mainnet-evidence evaluate-phase9-v2"

    assert checkout in text
    assert "path: phase9-tooling" in text
    assert "git -C phase9-tooling rev-parse HEAD" in text
    assert "phase9-tooling-revision.txt" in text
    assert install in text
    assert text.index(checkout) < text.index(install) < text.index(prepare)
    assert text.index(install) < text.index(evaluate)


def test_completed_underpowered_protocol_becomes_terminal_without_evaluation() -> None:
    text = _text()

    assert "v2-phase9-terminal-insufficient" in text
    assert "phase9-terminal-artifacts.json" in text
    assert "PHASE9_TERMINAL_EXISTS" in text
    assert "test_window_complete" in text
    assert "terminal_insufficient" in text
    assert '"edge_status": "insufficient_evidence"' in text
    assert '"economic_claim": "phase9_readiness_only"' in text


def test_existing_terminal_insufficient_artifact_stops_future_oos_attempts() -> None:
    text = _text()

    assert "steps.phase9_artifacts.outputs.terminal_exists != 'true'" in text
    terminal_upload = text.index("name: v2-phase9-terminal-insufficient")
    evaluate = text.index("cocomelon-mainnet-evidence evaluate-phase9-v2")
    assert terminal_upload < evaluate
