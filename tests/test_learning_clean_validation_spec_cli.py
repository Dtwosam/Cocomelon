from __future__ import annotations

import json

from cocomelon.learning_clean_validation_spec_cli import main
from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from cocomelon.research.learning_candidate_package import (
    materialize_learning_candidate_package,
)
from tests.test_learning_experiment import _run


def test_learning_clean_validation_spec_cli_materializes_verified_spec(
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
    output_root = tmp_path / "spec"

    status = main(
        [
            "--package-root",
            str(package_root),
            "--output-root",
            str(output_root),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-clean-validation-spec"
    assert payload["candidate_id"] == freeze.candidate_id
    assert payload["validation_start_ms"] == freeze.validation_not_before_ms
    assert payload["target_settled_trades"] == 20
    assert payload["stability_blocks"] == 4
    assert payload["trades_per_block"] == 5
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert (output_root / "candidate-validation-spec.json").is_file()
