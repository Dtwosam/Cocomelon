from __future__ import annotations

import json

from cocomelon.learning_candidate_package_cli import main
from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from tests.test_learning_experiment import _run


def test_learning_candidate_package_cli_materializes_verified_package(
    tmp_path,
    capsys,
) -> None:
    experiment, experiment_root = _run(tmp_path)
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    freeze_path = write_learning_candidate_freeze(tmp_path / "freeze", freeze)
    package_root = tmp_path / "package"

    status = main(
        [
            "--experiment-root",
            str(experiment_root),
            "--candidate-freeze",
            str(freeze_path),
            "--package-root",
            str(package_root),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-candidate-package"
    assert payload["candidate_id"] == freeze.candidate_id
    assert payload["experiment_id"] == experiment.experiment_id
    assert payload["prospective_only"] is True
    assert payload["research_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert (package_root / "candidate-package.json").is_file()
