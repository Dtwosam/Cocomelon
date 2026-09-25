from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.learning_clean_validation_score_cli import main
from tests.test_learning_clean_validation_score import _append, _setup


def test_learning_clean_validation_score_cli_materializes_verified_score(
    tmp_path,
    capsys,
) -> None:
    freeze, package_root, spec, spec_path, ledger_root = _setup(tmp_path)
    _append(
        ledger_root,
        candidate_id=freeze.candidate_id,
        spec_id=spec.spec_id,
        validation_start_ms=spec.validation_start_ms,
        values=[Decimal("0.1")] * 20,
    )
    output_root = tmp_path / "score"

    status = main(
        [
            "--ledger-root",
            str(ledger_root),
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--output-root",
            str(output_root),
            "--as-of-ms",
            str(spec.validation_start_ms + 50_000),
        ]
    )

    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-clean-validation-score"
    assert payload["candidate_id"] == freeze.candidate_id
    assert payload["status"] == "complete"
    assert payload["qualifies_clean_validation"] is True
    assert payload["eligible_settled_trade_count"] == 20
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False
    assert (output_root / "candidate-validation-score.json").is_file()
