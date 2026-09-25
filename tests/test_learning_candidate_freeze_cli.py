from __future__ import annotations

import json

from cocomelon.learning_candidate_freeze_cli import main
from tests.test_learning_experiment import _run


def test_learning_candidate_freeze_cli_materializes_verified_candidate(
    tmp_path,
    capsys,
) -> None:
    experiment, experiment_root = _run(tmp_path)
    output_root = tmp_path / "candidate"

    status = main(
        [
            "--experiment-root",
            str(experiment_root),
            "--output-root",
            str(output_root),
            "--frozen-at-ms",
            "200000",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-candidate-freeze"
    assert payload["experiment_id"] == experiment.experiment_id
    assert payload["prospective_only"] is True
    assert payload["research_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert (output_root / "candidate-freeze.json").is_file()
