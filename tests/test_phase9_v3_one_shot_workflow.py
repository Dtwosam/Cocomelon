from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/phase9-v3-one-shot.yml")
FROZEN_EVALUATOR_SHA = "39c2f6a57c0b2db9929fa4050e4c1f47e55f55ed"
STATE_BRANCH = "phase9-v3-protocol-state"
STATE_FILE = "phase9-v3-final.json"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v3_one_shot_consumes_only_completed_v3_curators() -> None:
    text = _text()

    assert "name: Phase 9 V3 One-Shot Evaluation" in text
    assert 'workflows: ["Verified V3 Mainnet Evidence Corpus Curator"]' in text
    assert "types: [completed]" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "v3-mainnet-corpus" in text


def test_v3_one_shot_pins_immutable_evaluator_revision() -> None:
    text = _text()

    assert f"PHASE9_EVALUATOR_REVISION: {FROZEN_EVALUATOR_SHA}" in text
    assert f"ref: {FROZEN_EVALUATOR_SHA}" in text
    assert "path: phase9-v3-tooling" in text
    assert "git -C phase9-v3-tooling rev-parse HEAD" in text
    assert "python -m pip install -e ./phase9-v3-tooling" in text
    assert "cocomelon-mainnet-evidence prepare-phase9-v3" in text
    assert "cocomelon-mainnet-evidence evaluate-phase9-v3" in text


def test_v3_one_shot_freezes_snapshot_before_evaluation() -> None:
    text = _text()

    prepare = text.index("cocomelon-mainnet-evidence prepare-phase9-v3")
    snapshot = text.index("name: v3-phase9-frozen-snapshot")
    evaluate = text.index("cocomelon-mainnet-evidence evaluate-phase9-v3")
    assert prepare < snapshot < evaluate
    assert "phase9-readiness.json" in text
    assert "ready_for_untouched_evaluation" in text
    assert "test_window_complete" in text


def test_v3_one_shot_has_terminal_insufficient_result() -> None:
    text = _text()

    assert "v3-phase9-terminal-insufficient" in text
    assert '"edge_status": "insufficient_evidence"' in text
    assert '"economic_claim": "phase9_readiness_only"' in text
    terminal = text.index("name: v3-phase9-terminal-insufficient")
    evaluate = text.index("cocomelon-mainnet-evidence evaluate-phase9-v3")
    assert terminal < evaluate


def test_v3_one_shot_uses_durable_final_state_guard() -> None:
    text = _text()

    assert STATE_BRANCH in text
    assert STATE_FILE in text
    assert '"protocol_id": "v3-phase9-one-shot"' in text
    assert "durable_final_exists" in text
    assert "steps.phase9_v3_durable.outputs.final_exists != 'true'" in text
    assert "v3-phase9-final-state-candidate" in text


def test_v3_one_shot_persists_state_in_narrow_write_job() -> None:
    text = _text()

    assert "persist-phase9-v3-state:" in text
    persist = text.index("persist-phase9-v3-state:")
    evaluation = text.index("evaluate-v3:")
    assert evaluation < persist
    persist_text = text[persist:]
    assert "needs: evaluate-v3" in persist_text
    assert "contents: write" in persist_text
    assert "actions: read" in persist_text
    assert "actions/download-artifact@v4" in persist_text
    assert "gh api --method PUT" in persist_text
    assert "refusing to replace" in persist_text.lower()


def test_v3_normal_evaluation_job_remains_read_only_and_paper_safe() -> None:
    text = _text()

    evaluate = text.index("evaluate-v3:")
    persist = text.index("persist-phase9-v3-state:")
    evaluation_text = text[evaluate:persist]
    assert "contents: write" not in evaluation_text
    assert "contents: read" in text[:persist]
    assert "COCOMELON_EXECUTION_MODE: live" not in text
    assert "testnet" not in text.lower()
