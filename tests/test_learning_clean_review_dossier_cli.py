from __future__ import annotations

import json

from cocomelon.learning_clean_review_dossier_cli import main
from tests.test_learning_clean_review_dossier import _eligible_inputs


def test_learning_clean_review_dossier_cli_materializes_verified_dossier(
    tmp_path,
    capsys,
) -> None:
    (
        package_root,
        _spec,
        spec_path,
        evidence_root,
        _score,
        score_path,
        finalization,
        finalization_path,
    ) = _eligible_inputs(tmp_path)
    output_root = tmp_path / "dossier"

    status = main(
        [
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
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-clean-review-dossier"
    assert payload["candidate_id"] == finalization.candidate_id
    assert payload["settled_trade_count"] == 20
    assert payload["human_review_required"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert all(
        item["status"] == "not_asserted_by_review_dossier"
        for item in payload["promotion_gates"]
    )
    assert (output_root / "candidate-review-dossier.json").is_file()
