from __future__ import annotations

import json
from pathlib import Path

from cocomelon import learning_cycle_cli
from cocomelon.research.learning_cycle import LearningCycleResult


def _result(tmp_path: Path, *, status: str) -> LearningCycleResult:
    return LearningCycleResult(
        output_root=tmp_path / "cycle",
        status=status,
        as_of_ms=123,
        learning_state_digest="a" * 64,
        feature_state_digest="b" * 64,
        eligible_record_count=220 if status == "completed" else 10,
        settled_train_record_count=200 if status == "completed" else 0,
        validation_record_count=20 if status == "completed" else 10,
        validation_start_opened_at_ms=1_000 if status == "completed" else None,
        baseline_structurally_ready=(status == "completed"),
        tree_structurally_ready=(status == "completed"),
        baseline_experiment_id=("c" * 64 if status == "completed" else None),
        tree_experiment_id=("d" * 64 if status == "completed" else None),
        baseline_qualifies_development=(
            False if status == "completed" else None
        ),
        tree_qualifies_development=(
            False if status == "completed" else None
        ),
    )


def test_learning_cycle_cli_returns_three_for_valid_not_ready_state(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        learning_cycle_cli,
        "run_learning_cycle",
        lambda **_kwargs: _result(tmp_path, status="not_ready"),
    )

    code = learning_cycle_cli.main(
        [
            "--learning-root",
            str(tmp_path / "learning"),
            "--feature-store-dir",
            str(tmp_path / "features"),
            "--output-root",
            str(tmp_path / "cycle"),
            "--as-of-ms",
            "123",
            "--implementation-commit-sha",
            "e" * 40,
            "--expected-learning-state-digest",
            "a" * 64,
            "--expected-feature-state-digest",
            "b" * 64,
        ]
    )

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_ready"
    assert payload["research_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False


def test_learning_cycle_cli_returns_zero_for_completed_cycle(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        learning_cycle_cli,
        "run_learning_cycle",
        lambda **_kwargs: _result(tmp_path, status="completed"),
    )

    code = learning_cycle_cli.main(
        [
            "--learning-root",
            str(tmp_path / "learning"),
            "--feature-store-dir",
            str(tmp_path / "features"),
            "--output-root",
            str(tmp_path / "cycle"),
            "--as-of-ms",
            "123",
            "--implementation-commit-sha",
            "e" * 40,
            "--expected-learning-state-digest",
            "a" * 64,
            "--expected-feature-state-digest",
            "b" * 64,
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
