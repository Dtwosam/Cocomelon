from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from cocomelon.research.learning_candidate_package import (
    materialize_learning_candidate_package,
    verify_learning_candidate_package,
)
from cocomelon.research.learning_clean_validation_spec import (
    LearningCleanValidationSpecError,
    build_learning_clean_validation_spec,
    load_learning_clean_validation_spec,
    verify_learning_clean_validation_spec,
    write_learning_clean_validation_spec,
)
from tests.test_learning_experiment import _run


def _package(tmp_path):
    experiment, experiment_root = _run(tmp_path)
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    freeze_path = write_learning_candidate_freeze(tmp_path / "freeze", freeze)
    package_root = tmp_path / "package"
    materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )
    return experiment, freeze, package_root


def test_learning_clean_validation_spec_freezes_existing_learning_gate(
    tmp_path,
) -> None:
    experiment, freeze, package_root = _package(tmp_path)
    package = verify_learning_candidate_package(package_root)

    spec = build_learning_clean_validation_spec(package_root)

    assert spec.candidate_id == freeze.candidate_id
    assert spec.candidate_package_id == package.package_id
    assert spec.experiment_id == experiment.experiment_id
    assert spec.validation_start_ms == freeze.validation_not_before_ms
    assert spec.target_settled_trades == 20
    assert spec.stability_blocks == 4
    assert spec.trades_per_block == 5
    assert spec.metric == "realized_net_r"
    assert spec.min_overall_mean_net_r == Decimal("0")
    assert spec.min_block_mean_net_r == Decimal("0")
    assert spec.qualification_operator == "strict_gt"
    assert spec.paper_only is True
    assert spec.prospective_only is True
    assert spec.research_only is True
    assert spec.promotion_eligible is False
    assert spec.execution_ready is False
    assert len(spec.spec_id) == 64

    path = write_learning_clean_validation_spec(tmp_path / "spec", spec)
    assert load_learning_clean_validation_spec(path) == spec
    assert verify_learning_clean_validation_spec(
        path,
        package_root=package_root,
    ) == spec


def test_learning_clean_validation_spec_detects_package_change(tmp_path) -> None:
    _experiment, _freeze, package_root = _package(tmp_path)
    spec = build_learning_clean_validation_spec(package_root)
    path = write_learning_clean_validation_spec(tmp_path / "spec", spec)

    receipt = package_root / "candidate-package.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["package_id"] = "0" * 64
    receipt.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError):
        verify_learning_clean_validation_spec(
            path,
            package_root=package_root,
        )


def test_learning_clean_validation_spec_rejects_tampering(tmp_path) -> None:
    _experiment, _freeze, package_root = _package(tmp_path)
    spec = build_learning_clean_validation_spec(package_root)
    path = write_learning_clean_validation_spec(tmp_path / "spec", spec)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["target_settled_trades"] = 19
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        LearningCleanValidationSpecError,
        match="SPEC_INVALID",
    ):
        load_learning_clean_validation_spec(path)


def test_learning_clean_validation_spec_write_is_conflict_safe(tmp_path) -> None:
    _experiment, _freeze, package_root = _package(tmp_path)
    spec = build_learning_clean_validation_spec(package_root)
    output_root = tmp_path / "spec"

    first = write_learning_clean_validation_spec(output_root, spec)
    second = write_learning_clean_validation_spec(output_root, spec)
    assert first == second

    first.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(
        LearningCleanValidationSpecError,
        match="SPEC_CONFLICT",
    ):
        write_learning_clean_validation_spec(output_root, spec)
