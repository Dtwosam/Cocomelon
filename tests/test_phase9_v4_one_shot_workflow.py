from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/phase9-v4-one-shot.yml")
FROZEN_EVALUATOR_SHA = "0b7b126d19306679c029807b2e2e86d614fb8847"
STATE_BRANCH = "phase9-v4-protocol-state"
STATE_FILE = "phase9-v4-final.json"
FREEZE_FILE = "phase9-v4-freeze.json"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v4_one_shot_consumes_only_completed_v4_curators() -> None:
    text = _text()
    assert "name: Phase 9 V4 One-Shot Evaluation" in text
    assert 'workflows: ["Verified V4 Mainnet Evidence Corpus Curator"]' in text
    assert "types: [completed]" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "v4-mainnet-corpus" in text


def test_v4_one_shot_pins_immutable_evaluator_revision() -> None:
    text = _text()
    assert f"PHASE9_EVALUATOR_REVISION: {FROZEN_EVALUATOR_SHA}" in text
    assert f"ref: {FROZEN_EVALUATOR_SHA}" in text
    assert "path: phase9-v4-tooling" in text
    assert "git -C phase9-v4-tooling rev-parse HEAD" in text
    assert "python -m pip install -e ./phase9-v4-tooling" in text
    assert "cocomelon-mainnet-evidence prepare-phase9-v4" in text
    assert "cocomelon-mainnet-evidence evaluate-phase9-v4" in text


def test_v4_one_shot_freezes_snapshot_before_evaluation() -> None:
    text = _text()
    prepare = text.index("cocomelon-mainnet-evidence prepare-phase9-v4")
    snapshot = text.index("name: v4-phase9-frozen-snapshot")
    evaluate = text.index("cocomelon-mainnet-evidence evaluate-phase9-v4")
    assert prepare < snapshot < evaluate
    assert "phase9-readiness.json" in text
    assert "ready_for_untouched_evaluation" in text
    assert "test_window_complete" in text


def test_v4_one_shot_has_terminal_insufficient_result() -> None:
    text = _text()
    assert "v4-phase9-terminal-insufficient" in text
    assert '"edge_status": "insufficient_evidence"' in text
    assert '"economic_claim": "phase9_readiness_only"' in text
    terminal = text.index("name: v4-phase9-terminal-insufficient")
    evaluate = text.index("cocomelon-mainnet-evidence evaluate-phase9-v4")
    assert terminal < evaluate


def test_v4_one_shot_uses_durable_final_state_guard() -> None:
    text = _text()
    assert STATE_BRANCH in text
    assert STATE_FILE in text
    assert '"protocol_id": "v4-phase9-one-shot"' in text
    assert "durable_final_exists" in text
    assert "final_exists" in text
    assert "v4-phase9-final-state-candidate" in text


def test_v4_one_shot_persists_state_in_narrow_write_job() -> None:
    text = _text()
    assert "persist-phase9-v4-state:" in text
    persist = text.index("persist-phase9-v4-state:")
    evaluation = text.index("evaluate-v4:")
    assert evaluation < persist
    persist_text = text[persist:]
    assert "needs: evaluate-v4" in persist_text
    assert "contents: write" in persist_text
    assert "actions: read" in persist_text
    assert "actions/download-artifact@v4" in persist_text
    assert "gh api --method PUT" in persist_text
    assert "refusing to replace" in persist_text.lower()


def test_v4_one_shot_has_permanent_freeze_lock_before_economic_evaluation() -> None:
    text = _text()
    assert FREEZE_FILE in text
    assert "persist-phase9-v4-freeze:" in text
    assert "prepare-v4:" in text
    assert "v4-phase9-freeze-candidate" in text
    assert '"freeze_id"' in text
    assert '"freeze_state": "frozen"' in text
    persist_freeze = text.index("persist-phase9-v4-freeze:")
    evaluate = text.index("evaluate-v4:")
    command = text.index("cocomelon-mainnet-evidence evaluate-phase9-v4")
    assert persist_freeze < evaluate < command
    evaluate_text = text[evaluate:]
    assert "persist-phase9-v4-freeze" in evaluate_text


def test_v4_one_shot_refuses_new_corpus_after_freeze_lock() -> None:
    text = _text().lower()
    assert "durable_freeze_exists" in text
    assert "refusing to select a replacement v4 oos corpus" in text
    assert "source_curator_run_id" in text
    assert "corpus_artifact_id" in text
    assert "corpus_zip_sha256" in text
    assert "snapshot_id" in text


def test_v4_final_state_is_bound_to_durable_freeze() -> None:
    text = _text()
    assert "phase9-v4-durable-freeze.json" in text
    assert '"freeze_id": freeze["freeze_id"]' in text
    assert "V4 final state freeze id mismatch" in text


def test_v4_prepare_and_evaluation_jobs_remain_read_only_and_paper_safe() -> None:
    text = _text()
    prepare = text.index("prepare-v4:")
    persist_freeze = text.index("persist-phase9-v4-freeze:")
    evaluate = text.index("evaluate-v4:")
    persist_state = text.index("persist-phase9-v4-state:")
    prepare_text = text[prepare:persist_freeze]
    evaluation_text = text[evaluate:persist_state]
    assert "contents: write" not in prepare_text
    assert "contents: write" not in evaluation_text
    assert "contents: read" in text[:persist_freeze]
    assert "COCOMELON_EXECUTION_MODE: live" not in text
    assert "testnet" not in text.lower()
