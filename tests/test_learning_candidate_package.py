from __future__ import annotations

import json
import shutil

import pytest

from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from cocomelon.research.learning_candidate_package import (
    LearningCandidatePackageError,
    build_learning_candidate_package,
    materialize_learning_candidate_package,
    verify_learning_candidate_package,
)
from tests.test_learning_experiment import _run


def _sources(tmp_path):
    experiment, experiment_root = _run(tmp_path)
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    freeze_path = write_learning_candidate_freeze(
        tmp_path / "freeze",
        freeze,
    )
    return experiment, experiment_root, freeze, freeze_path


def test_learning_candidate_package_is_self_contained(tmp_path) -> None:
    experiment, experiment_root, freeze, freeze_path = _sources(tmp_path)
    package_root = tmp_path / "package"

    receipt = materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )

    assert receipt == package_root / "candidate-package.json"
    package = verify_learning_candidate_package(package_root)
    assert package.candidate_id == freeze.candidate_id
    assert package.experiment_id == experiment.experiment_id
    assert package.validation_not_before_ms == freeze.validation_not_before_ms
    assert package.prospective_only is True
    assert package.research_only is True
    assert package.promotion_eligible is False
    assert package.execution_ready is False
    assert len(package.package_id) == 64

    shutil.rmtree(experiment_root)
    shutil.rmtree(freeze_path.parent)

    assert verify_learning_candidate_package(package_root) == package


def test_learning_candidate_package_rejects_unexpected_source_file(tmp_path) -> None:
    _experiment, experiment_root, _freeze, freeze_path = _sources(tmp_path)
    (experiment_root / "notes.txt").write_text("not part of the frozen artifact\n")

    with pytest.raises(
        LearningCandidatePackageError,
        match="EXPERIMENT_FILE_SET_INVALID",
    ):
        build_learning_candidate_package(
            experiment_root=experiment_root,
            candidate_freeze_path=freeze_path,
        )


def test_learning_candidate_package_rejects_tampered_packaged_bytes(tmp_path) -> None:
    _experiment, experiment_root, _freeze, freeze_path = _sources(tmp_path)
    package_root = tmp_path / "package"
    materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )

    evaluation_path = package_root / "experiment" / "evaluation.json"
    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    payload["qualifies_development"] = False
    evaluation_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LearningCandidatePackageError,
        match="EXPERIMENT_DIGEST_MISMATCH",
    ):
        verify_learning_candidate_package(package_root)


def test_learning_candidate_package_write_is_idempotent_and_conflict_safe(
    tmp_path,
) -> None:
    _experiment, experiment_root, _freeze, freeze_path = _sources(tmp_path)
    package_root = tmp_path / "package"

    first = materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )
    second = materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )
    assert first == second

    (package_root / "candidate-freeze.json").write_text(
        '{"tampered":true}\n',
        encoding="utf-8",
    )
    with pytest.raises(
        LearningCandidatePackageError,
        match="LEARNING_CANDIDATE_PACKAGE_CONFLICT",
    ):
        materialize_learning_candidate_package(
            experiment_root=experiment_root,
            candidate_freeze_path=freeze_path,
            package_root=package_root,
        )
