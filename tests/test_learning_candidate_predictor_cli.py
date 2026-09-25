from __future__ import annotations

import json

from cocomelon.learning_candidate_predictor_cli import main
from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from cocomelon.research.learning_candidate_package import (
    materialize_learning_candidate_package,
)
from cocomelon.research.learning_clean_validation_spec import (
    build_learning_clean_validation_spec,
    write_learning_clean_validation_spec,
)
from tests.test_learning_experiment import _run


def test_learning_candidate_predictor_cli_scores_frozen_features(
    tmp_path,
    capsys,
) -> None:
    _experiment, experiment_root = _run(tmp_path)
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
    spec = build_learning_clean_validation_spec(package_root)
    spec_path = write_learning_clean_validation_spec(tmp_path / "spec", spec)
    feature_path = tmp_path / "features.json"
    feature_path.write_text(
        json.dumps({"market": "HYPE", "direction": "long"}),
        encoding="utf-8",
    )

    status = main(
        [
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--features-json",
            str(feature_path),
            "--observed-at-ms",
            str(spec.validation_start_ms),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-candidate-predict"
    assert payload["candidate_id"] == freeze.candidate_id
    assert payload["predicted_net_r"] == "0.05"
    assert payload["trade_eligible"] is True
    assert payload["reason_code"] == "prediction_meets_threshold"
    assert payload["paper_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
