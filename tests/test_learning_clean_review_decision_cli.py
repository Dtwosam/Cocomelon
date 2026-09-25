from __future__ import annotations

import json

from cocomelon.learning_clean_review_decision_cli import main
from cocomelon.research.learning_clean_review_decision import DECISION_ADVANCE
from tests.test_learning_clean_review_decision import _review_inputs


def test_learning_clean_review_decision_cli_records_shadow_only_advance(
    tmp_path,
    capsys,
) -> None:
    (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization,
        finalization_path,
        _dossier,
        dossier_path,
    ) = _review_inputs(tmp_path)
    output_root = tmp_path / "decision"

    status = main(
        [
            "--review-dossier",
            str(dossier_path),
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--validation-score",
            str(score_path),
            "--finalization",
            str(finalization_path),
            "--evidence-root",
            str(evidence_root),
            "--output-root",
            str(output_root),
            "--reviewer",
            "reviewer@example",
            "--reviewed-at-ms",
            str(finalization.finalized_at_ms + 1),
            "--decision",
            DECISION_ADVANCE,
            "--rationale",
            "Advance to paper shadow evaluation only.",
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-clean-review-decision"
    assert payload["decision"] == DECISION_ADVANCE
    assert payload["shadow_evaluation_authorized"] is True
    assert payload["human_review_completed"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["live_promotion_authorized"] is False
    assert (output_root / "candidate-review-decision.json").is_file()
