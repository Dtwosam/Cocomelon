from __future__ import annotations

import json

from cocomelon.learning_shadow_admission_cli import main
from tests.test_learning_shadow_admission import _approved_review


def test_learning_shadow_admission_cli_materializes_verified_admission(
    tmp_path,
    capsys,
) -> None:
    (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization_path,
        _dossier,
        dossier_path,
        decision,
        decision_path,
    ) = _approved_review(tmp_path)
    output_root = tmp_path / "shadow"

    status = main(
        [
            "--review-decision",
            str(decision_path),
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
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-shadow-admission"
    assert payload["review_decision_id"] == decision.review_decision_id
    assert payload["shadow_start_ms"] == decision.reviewed_at_ms
    assert payload["minimum_closed_mainnet_paper_trades"] == 500
    assert payload["minimum_shadow_calendar_days"] == 45
    assert payload["minimum_profit_factor"] == "1.20"
    assert payload["maximum_paper_drawdown_fraction"] == "0.08"
    assert payload["shadow_evaluation_authorized"] is True
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["live_promotion_authorized"] is False
    assert (output_root / "shadow-admission.json").is_file()
