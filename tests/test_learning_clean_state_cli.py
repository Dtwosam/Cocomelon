from __future__ import annotations

import json

from cocomelon.learning_clean_state_cli import main
from tests.test_learning_clean_validation_score import _setup


def test_learning_clean_state_cli_materializes_verified_state(
    tmp_path,
    capsys,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    output_root = tmp_path / "state"

    status = main(
        [
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--evidence-root",
            str(evidence_root),
            "--output-root",
            str(output_root),
            "--as-of-ms",
            str(spec.validation_start_ms),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-clean-state"
    assert payload["candidate_id"] == spec.candidate_id
    assert payload["status"] == "collecting"
    assert payload["prediction_count"] == 0
    assert payload["settled_outcome_count"] == 0
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert (output_root / "state.json").is_file()
