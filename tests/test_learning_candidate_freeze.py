from __future__ import annotations

import json
from dataclasses import replace

import pytest

from cocomelon.research import learning_candidate_freeze
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.learning_candidate_freeze import (
    LearningCandidateFreezeError,
    build_learning_candidate_freeze,
    verify_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from tests.test_learning_experiment import _run


def test_learning_candidate_freeze_binds_qualified_experiment(tmp_path) -> None:
    experiment, experiment_root = _run(tmp_path)
    frozen_at_ms = 200_000

    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=frozen_at_ms,
    )

    assert experiment.qualifies_development is True
    assert freeze.experiment_id == experiment.experiment_id
    assert freeze.model_family == experiment.model_family
    assert freeze.experiment_as_of_ms == 101_000
    assert freeze.frozen_at_ms == frozen_at_ms
    assert freeze.validation_not_before_ms == (
        frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
    )
    assert freeze.prospective_only is True
    assert freeze.research_only is True
    assert freeze.promotion_eligible is False
    assert freeze.execution_ready is False
    assert len(freeze.candidate_id) == 64

    path = write_learning_candidate_freeze(tmp_path / "freeze", freeze)
    verified = verify_learning_candidate_freeze(
        path,
        experiment_root=experiment_root,
    )
    assert verified == freeze


def test_learning_candidate_freeze_write_is_idempotent_and_conflict_safe(
    tmp_path,
) -> None:
    _experiment, experiment_root = _run(tmp_path)
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    output_root = tmp_path / "freeze"

    first = write_learning_candidate_freeze(output_root, freeze)
    second = write_learning_candidate_freeze(output_root, freeze)

    assert first == second
    payload = json.loads(first.read_text(encoding="utf-8"))
    payload["frozen_at_ms"] = 200_001
    first.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(
        LearningCandidateFreezeError,
        match="LEARNING_CANDIDATE_FREEZE_CONFLICT",
    ):
        write_learning_candidate_freeze(output_root, freeze)


def test_learning_candidate_freeze_rejects_unqualified_experiment(
    tmp_path,
    monkeypatch,
) -> None:
    experiment, experiment_root = _run(tmp_path)
    monkeypatch.setattr(
        learning_candidate_freeze,
        "verify_learning_experiment",
        lambda **_kwargs: replace(experiment, qualifies_development=False),
    )

    with pytest.raises(
        LearningCandidateFreezeError,
        match="LEARNING_EXPERIMENT_NOT_DEVELOPMENT_QUALIFIED",
    ):
        build_learning_candidate_freeze(
            experiment_root=experiment_root,
            frozen_at_ms=200_000,
        )


def test_learning_candidate_freeze_rejects_time_before_experiment(
    tmp_path,
) -> None:
    _experiment, experiment_root = _run(tmp_path)

    with pytest.raises(
        LearningCandidateFreezeError,
        match="LEARNING_CANDIDATE_FREEZE_PRECEDES_EXPERIMENT",
    ):
        build_learning_candidate_freeze(
            experiment_root=experiment_root,
            frozen_at_ms=100_999,
        )


def test_learning_candidate_freeze_verifier_rejects_tampering(tmp_path) -> None:
    _experiment, experiment_root = _run(tmp_path)
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    path = write_learning_candidate_freeze(tmp_path / "freeze", freeze)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candidate_id"] = "0" * 64
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LearningCandidateFreezeError,
        match="LEARNING_CANDIDATE_FREEZE_ID_MISMATCH",
    ):
        verify_learning_candidate_freeze(
            path,
            experiment_root=experiment_root,
        )
