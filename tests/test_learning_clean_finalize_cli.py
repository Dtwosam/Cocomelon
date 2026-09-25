from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.learning_clean_finalize_cli import main
from cocomelon.research.learning_clean_validation_score import (
    score_learning_clean_validation,
    write_learning_clean_validation_score,
)
from tests.test_learning_clean_validation_score import _append, _setup


def test_learning_clean_finalize_cli_materializes_verified_verdict(
    tmp_path,
    capsys,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    _append(
        evidence_root,
        spec=spec,
        values=[Decimal("0.1")] * 20,
    )
    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 100_000,
    )
    score_path = write_learning_clean_validation_score(tmp_path / "score", score)
    output_root = tmp_path / "final"

    status = main(
        [
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--validation-score",
            str(score_path),
            "--evidence-root",
            str(evidence_root),
            "--output-root",
            str(output_root),
            "--finalized-at-ms",
            str(score.as_of_ms + 1),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-clean-finalize"
    assert payload["verdict"] == "eligible_for_candidate_review"
    assert payload["eligible_for_candidate_review"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert (output_root / "candidate-finalization.json").is_file()
