from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from cocomelon.research.learning_candidate_package import (
    materialize_learning_candidate_package,
)
from cocomelon.research.learning_candidate_predictor import (
    LearningCandidatePredictorError,
    build_learning_candidate_predictor,
)
from cocomelon.research.learning_clean_validation_spec import (
    build_learning_clean_validation_spec,
    write_learning_clean_validation_spec,
)
from cocomelon.research.learning_experiment import run_learning_experiment
from cocomelon.research.learning_grouped_mean import GROUPED_MEAN_MODEL_FAMILY
from cocomelon.research.learning_tree import TREE_MODEL_FAMILY
from cocomelon.research.outcome_learning import LearningEvidenceKind
from tests.test_learning_experiment import _ledger, _run


def _package_from_experiment(
    tmp_path,
    *,
    experiment_root,
):
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    freeze_path = write_learning_candidate_freeze(
        tmp_path / f"freeze-{experiment_root.name}",
        freeze,
    )
    package_root = tmp_path / f"package-{experiment_root.name}"
    materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )
    spec = build_learning_clean_validation_spec(package_root)
    spec_path = write_learning_clean_validation_spec(
        tmp_path / f"spec-{experiment_root.name}",
        spec,
    )
    return freeze, package_root, spec, spec_path


def test_grouped_mean_predictor_uses_frozen_train_partition(tmp_path) -> None:
    _experiment, experiment_root = _run(tmp_path)
    freeze, package_root, spec, spec_path = _package_from_experiment(
        tmp_path,
        experiment_root=experiment_root,
    )

    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=spec_path,
    )
    prediction = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )

    assert freeze.validation_not_before_ms == spec.validation_start_ms
    assert predictor.package.model_family == GROUPED_MEAN_MODEL_FAMILY
    assert prediction.predicted_net_r == Decimal("0.05")
    assert prediction.prediction_threshold == Decimal("0")
    assert prediction.trade_eligible is True
    assert prediction.reason_code == "prediction_meets_threshold"
    assert prediction.paper_only is True
    assert prediction.research_only is True
    assert prediction.promotion_eligible is False
    assert prediction.execution_ready is False
    assert len(prediction.prediction_id) == 64

    repeated = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )
    assert repeated == prediction
    assert repeated.prediction_id == prediction.prediction_id


def test_grouped_mean_predictor_no_trades_unknown_group(tmp_path) -> None:
    _experiment, experiment_root = _run(tmp_path)
    _freeze, package_root, spec, spec_path = _package_from_experiment(
        tmp_path,
        experiment_root=experiment_root,
    )
    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=spec_path,
    )

    prediction = predictor.score(
        feature_values=("BTC", "long"),
        observed_at_ms=spec.validation_start_ms,
    )

    assert prediction.predicted_net_r is None
    assert prediction.trade_eligible is False
    assert prediction.reason_code == "prediction_not_available"


def test_predictor_rejects_pre_validation_observation(tmp_path) -> None:
    _experiment, experiment_root = _run(tmp_path)
    _freeze, package_root, spec, spec_path = _package_from_experiment(
        tmp_path,
        experiment_root=experiment_root,
    )
    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=spec_path,
    )

    with pytest.raises(
        LearningCandidatePredictorError,
        match="PREDICTION_BEFORE_VALIDATION_START",
    ):
        predictor.score(
            feature_values=("HYPE", "long"),
            observed_at_ms=spec.validation_start_ms - 1,
        )


def test_tree_predictor_reconstructs_frozen_model(tmp_path) -> None:
    pytest.importorskip("sklearn")
    learning_root = _ledger(tmp_path)
    experiment_root = tmp_path / "tree-experiment"
    result = run_learning_experiment(
        learning_root=learning_root,
        feature_store_dir=tmp_path / "tree-features",
        output_root=experiment_root,
        as_of_ms=101_000,
        evidence_kind=LearningEvidenceKind.PAPER_EXECUTION,
        feature_registry=("market", "direction"),
        model_family=TREE_MODEL_FAMILY,
        model_config={
            "min_train_rows": 4,
            "validation_rows": 4,
            "max_leaf_nodes": 3,
            "min_samples_leaf": 2,
            "learning_rate": "0.05",
            "max_iter": 10,
            "l2_regularization": "1",
        },
        decision_policy={
            "prediction_threshold": "0",
            "stability_blocks": 2,
            "min_block_trades": 2,
            "min_validation_trades": 4,
            "min_validation_mean_target": "0",
        },
        implementation_commit_sha="b" * 40,
    )
    assert result.qualifies_development is True
    _freeze, package_root, spec, spec_path = _package_from_experiment(
        tmp_path,
        experiment_root=experiment_root,
    )

    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=spec_path,
    )
    prediction = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )

    assert predictor.package.model_family == TREE_MODEL_FAMILY
    assert prediction.predicted_net_r is not None
    assert prediction.predicted_net_r.is_finite()
    assert prediction.predicted_net_r > Decimal("0")
    assert prediction.trade_eligible is True
