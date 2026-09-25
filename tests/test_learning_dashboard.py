from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.learning_dashboard import (
    LearningDashboardError,
    build_learning_operations_status,
    render_learning_operations_markdown,
)


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _state(root: Path) -> None:
    learning_digest = "a" * 64
    feature_digest = "b" * 64
    _write(
        root / "last-sync.json",
        {
            "command": "research-learning-sync",
            "upstream_run_id": 123,
            "upstream_run_attempt": 1,
            "upstream_head_sha": "c" * 40,
            "upstream_artifact_id": 456,
            "upstream_artifact_digest": "sha256:" + "d" * 64,
            "learning_record_count": 37,
            "learning_state_digest": learning_digest,
            "feature_snapshot_count": 37,
            "feature_state_digest": feature_digest,
            "created_records": 2,
            "receipt_id": "e" * 64,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        },
    )
    _write(
        root / "readiness.json",
        {
            "command": "learning-readiness",
            "as_of_ms": 999_000,
            "evidence_kind": "paper_execution",
            "ledger_state_digest": learning_digest,
            "feature_store_state_digest": feature_digest,
            "eligible_record_count": 35,
            "quarantined_record_count": 2,
            "feature_complete_record_count": 35,
            "blocked_record_count": 0,
            "structurally_ready": True,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        },
    )


def _cycle(root: Path, *, status: str = "not_ready") -> None:
    _write(
        root / "cycle.json",
        {
            "status": status,
            "as_of_ms": 999_000,
            "learning_state_digest": "a" * 64,
            "feature_state_digest": "b" * 64,
            "eligible_record_count": 35,
            "settled_train_record_count": 15,
            "validation_record_count": 20,
            "baseline_structurally_ready": True,
            "tree_structurally_ready": True,
            "cycle_id": "f" * 64,
            "research_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
        },
    )


def test_learning_dashboard_reports_non_economic_readiness(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _state(state)

    status = build_learning_operations_status(state)

    assert status["state"] == "waiting_for_cycle"
    assert status["learning_record_count"] == 37
    assert status["feature_snapshot_count"] == 37
    assert status["eligible_record_count"] == 35
    assert status["quarantined_record_count"] == 2
    assert status["blocked_record_count"] == 0
    assert status["structurally_ready"] is True
    assert status["target_train_records"] == 200
    assert status["target_validation_records"] == 20
    assert status["cycle_status"] == "not_published"
    assert status["research_only"] is True
    assert status["promotion_eligible"] is False
    assert status["execution_ready"] is False


def test_learning_dashboard_reports_cycle_capacity_without_economics(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    cycle = tmp_path / "cycle"
    _state(state)
    _cycle(cycle)

    status = build_learning_operations_status(state, cycle_root=cycle)
    markdown = render_learning_operations_markdown(status)

    assert status["state"] == "waiting_for_capacity"
    assert status["cycle_status"] == "not_ready"
    assert status["settled_train_record_count"] == 15
    assert status["validation_record_count"] == 20
    assert status["train_record_shortfall"] == 185
    assert status["validation_record_shortfall"] == 0
    assert "Continuous Learning Operations" in markdown
    assert "15 / 200" in markdown
    assert "20 / 20" in markdown
    assert "NO EXECUTION" in markdown
    assert "pnl" not in markdown.lower()
    assert "net_r" not in markdown.lower()


def test_learning_dashboard_rejects_state_digest_mismatch(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _state(state)
    readiness = json.loads((state / "readiness.json").read_text(encoding="utf-8"))
    readiness["ledger_state_digest"] = "0" * 64
    _write(state / "readiness.json", readiness)

    with pytest.raises(
        LearningDashboardError,
        match="LEARNING_STATE_DIGEST_MISMATCH",
    ):
        build_learning_operations_status(state)


def test_learning_dashboard_rejects_execution_authority(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _state(state)
    sync = json.loads((state / "last-sync.json").read_text(encoding="utf-8"))
    sync["execution_ready"] = True
    _write(state / "last-sync.json", sync)

    with pytest.raises(
        LearningDashboardError,
        match="EXECUTION_AUTHORITY_FORBIDDEN",
    ):
        build_learning_operations_status(state)


def test_learning_dashboard_rejects_cycle_from_other_state(tmp_path: Path) -> None:
    state = tmp_path / "state"
    cycle = tmp_path / "cycle"
    _state(state)
    _cycle(cycle)
    payload = json.loads((cycle / "cycle.json").read_text(encoding="utf-8"))
    payload["feature_state_digest"] = "9" * 64
    _write(cycle / "cycle.json", payload)

    with pytest.raises(
        LearningDashboardError,
        match="CYCLE_FEATURE_STATE_DIGEST_MISMATCH",
    ):
        build_learning_operations_status(state, cycle_root=cycle)
