from __future__ import annotations

import json

from cocomelon.learning_shadow_state_cli import main
from tests.test_learning_shadow_state import _kwargs


def test_shadow_state_cli_materializes_verified_non_economic_state(
    tmp_path,
    capsys,
) -> None:
    admission, _evidence_root, kwargs = _kwargs(tmp_path)
    output_root = tmp_path / "state"

    status = main(
        [
            "--shadow-evidence-root",
            str(kwargs["shadow_evidence_root"]),
            "--shadow-admission",
            str(kwargs["shadow_admission_path"]),
            "--review-decision",
            str(kwargs["review_decision_path"]),
            "--review-dossier",
            str(kwargs["review_dossier_path"]),
            "--package-root",
            str(kwargs["package_root"]),
            "--validation-spec",
            str(kwargs["validation_spec_path"]),
            "--validation-score",
            str(kwargs["validation_score_path"]),
            "--finalization",
            str(kwargs["finalization_path"]),
            "--clean-evidence-root",
            str(kwargs["clean_evidence_root"]),
            "--output-root",
            str(output_root),
            "--as-of-ms",
            str(admission.shadow_start_ms),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-shadow-state"
    assert payload["candidate_id"] == admission.candidate_id
    assert payload["shadow_admission_id"] == admission.shadow_admission_id
    assert payload["status"] == "collecting"
    assert payload["closed_paper_trade_count"] == 0
    assert payload["campaign_count"] == 0
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert payload["live_promotion_authorized"] is False
    assert (output_root / "shadow-state.json").is_file()
