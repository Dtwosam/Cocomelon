from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.learning_clean_evidence_cli import main
from cocomelon.research.learning_clean_evidence import LearningCleanTradeOutcome
from tests.test_learning_clean_validation_score import _prediction, _setup


def _write_json(path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def test_clean_evidence_cli_records_prediction_outcome_and_verifies_blindly(
    tmp_path,
    capsys,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    prediction = _prediction(spec, index=1)
    prediction_path = tmp_path / "prediction.json"
    _write_json(
        prediction_path,
        {
            "command": "learning-candidate-predict",
            **prediction.to_dict(),
        },
    )

    prediction_status = main(
        [
            "record-prediction",
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--evidence-root",
            str(evidence_root),
            "--input-json",
            str(prediction_path),
        ]
    )

    assert prediction_status == 0
    prediction_payload = json.loads(capsys.readouterr().out)
    assert prediction_payload["action"] == "record-prediction"
    assert prediction_payload["candidate_id"] == spec.candidate_id
    assert prediction_payload["prediction_count"] == 1
    assert prediction_payload["settled_outcome_count"] == 0
    assert prediction_payload["unsettled_trade_prediction_count"] == 1
    assert prediction_payload["receipt_id"] == prediction.prediction_id
    assert prediction_payload["promotion_eligible"] is False
    assert prediction_payload["execution_ready"] is False
    prediction_output = json.dumps(prediction_payload, sort_keys=True).lower()
    assert "predicted_net_r" not in prediction_output
    assert "\"net_r\"" not in prediction_output
    assert "pnl" not in prediction_output

    outcome = LearningCleanTradeOutcome(
        prediction_id=prediction.prediction_id,
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        candidate_package_id=spec.candidate_package_id,
        source_trade_id="clean-cli-paper-1",
        market="HYPE",
        direction="long",
        opened_at_ms=prediction.observed_at_ms + 1,
        closed_at_ms=prediction.observed_at_ms + 101,
        net_r=Decimal("0.1"),
    )
    outcome_path = tmp_path / "outcome.json"
    _write_json(outcome_path, outcome.to_dict())

    outcome_status = main(
        [
            "record-outcome",
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--evidence-root",
            str(evidence_root),
            "--input-json",
            str(outcome_path),
        ]
    )

    assert outcome_status == 0
    outcome_payload = json.loads(capsys.readouterr().out)
    assert outcome_payload["action"] == "record-outcome"
    assert outcome_payload["prediction_count"] == 1
    assert outcome_payload["settled_outcome_count"] == 1
    assert outcome_payload["unsettled_trade_prediction_count"] == 0
    assert outcome_payload["receipt_id"] == outcome.outcome_id
    assert outcome_payload["promotion_eligible"] is False
    assert outcome_payload["execution_ready"] is False
    outcome_output = json.dumps(outcome_payload, sort_keys=True).lower()
    assert "predicted_net_r" not in outcome_output
    assert "\"net_r\"" not in outcome_output
    assert "pnl" not in outcome_output

    verify_status = main(
        [
            "verify",
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--evidence-root",
            str(evidence_root),
        ]
    )

    assert verify_status == 0
    verify_payload = json.loads(capsys.readouterr().out)
    assert verify_payload["action"] == "verify"
    assert verify_payload["prediction_count"] == 1
    assert verify_payload["settled_outcome_count"] == 1
    assert verify_payload["unsettled_trade_prediction_count"] == 0
    assert verify_payload["clean_evidence_state_digest"] == (
        outcome_payload["clean_evidence_state_digest"]
    )


def test_clean_evidence_cli_rejects_outcome_without_recorded_prediction(
    tmp_path,
    capsys,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    prediction = _prediction(spec, index=1)
    outcome = LearningCleanTradeOutcome(
        prediction_id=prediction.prediction_id,
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        candidate_package_id=spec.candidate_package_id,
        source_trade_id="clean-cli-paper-missing-prediction",
        market="HYPE",
        direction="long",
        opened_at_ms=prediction.observed_at_ms + 1,
        closed_at_ms=prediction.observed_at_ms + 101,
        net_r=Decimal("0.1"),
    )
    outcome_path = tmp_path / "orphan-outcome.json"
    _write_json(outcome_path, outcome.to_dict())

    status = main(
        [
            "record-outcome",
            "--package-root",
            str(package_root),
            "--validation-spec",
            str(spec_path),
            "--evidence-root",
            str(evidence_root),
            "--input-json",
            str(outcome_path),
        ]
    )

    assert status == 2
    error = json.loads(capsys.readouterr().err)
    assert "LEARNING_CLEAN_OUTCOME_PREDICTION_MISSING" in error["error"]
