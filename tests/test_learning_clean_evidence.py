from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.research.learning_candidate_predictor import (
    build_learning_candidate_predictor,
)
from cocomelon.research.learning_clean_evidence import (
    LearningCleanEvidenceError,
    LearningCleanEvidenceStore,
    LearningCleanTradeOutcome,
)
from tests.test_learning_candidate_predictor import _package_from_experiment
from tests.test_learning_experiment import _run


def _runtime(tmp_path):
    _experiment, experiment_root = _run(tmp_path)
    _freeze, package_root, spec, spec_path = _package_from_experiment(
        tmp_path,
        experiment_root=experiment_root,
    )
    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=spec_path,
    )
    return spec, predictor


def _outcome(
    prediction,
    *,
    source_trade_id: str = "paper-trade-1",
    market: str = "HYPE",
    direction: str = "long",
    net_r: str = "0.10",
):
    return LearningCleanTradeOutcome(
        prediction_id=prediction.prediction_id,
        candidate_id=prediction.candidate_id,
        validation_spec_id=prediction.validation_spec_id,
        candidate_package_id=prediction.candidate_package_id,
        source_trade_id=source_trade_id,
        market=market,
        direction=direction,
        opened_at_ms=prediction.observed_at_ms + 1,
        closed_at_ms=prediction.observed_at_ms + 2,
        net_r=Decimal(net_r),
    )


def test_clean_evidence_store_persists_prediction_and_settled_outcome(tmp_path) -> None:
    spec, predictor = _runtime(tmp_path)
    store_root = tmp_path / "clean-evidence"
    store = LearningCleanEvidenceStore(store_root, spec=spec)
    prediction = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )

    prediction_path = store.record_prediction(prediction)
    outcome = _outcome(prediction)
    outcome_path = store.record_outcome(outcome)

    assert prediction_path.is_file()
    assert outcome_path.is_file()
    assert store.iter_predictions() == (prediction,)
    assert store.iter_outcomes() == (outcome,)
    assert store.unsettled_trade_prediction_ids == ()
    digest = store.state_digest
    assert len(digest) == 64
    store.verify()

    reopened = LearningCleanEvidenceStore(store_root, spec=spec)
    assert reopened.state_digest == digest
    assert reopened.iter_predictions() == (prediction,)
    assert reopened.iter_outcomes() == (outcome,)


def test_clean_evidence_store_tracks_unsettled_eligible_prediction(tmp_path) -> None:
    spec, predictor = _runtime(tmp_path)
    store = LearningCleanEvidenceStore(tmp_path / "clean-evidence", spec=spec)
    prediction = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )
    store.record_prediction(prediction)

    assert prediction.trade_eligible is True
    assert store.unsettled_trade_prediction_ids == (prediction.prediction_id,)


def test_clean_evidence_store_rejects_outcome_for_no_trade_prediction(tmp_path) -> None:
    spec, predictor = _runtime(tmp_path)
    store = LearningCleanEvidenceStore(tmp_path / "clean-evidence", spec=spec)
    prediction = predictor.score(
        feature_values=("BTC", "long"),
        observed_at_ms=spec.validation_start_ms,
    )
    store.record_prediction(prediction)
    assert prediction.trade_eligible is False

    with pytest.raises(
        LearningCleanEvidenceError,
        match="OUTCOME_FOR_NO_TRADE",
    ):
        store.record_outcome(_outcome(prediction, market="BTC"))


def test_clean_evidence_store_rejects_trade_identity_mismatch(tmp_path) -> None:
    spec, predictor = _runtime(tmp_path)
    store = LearningCleanEvidenceStore(tmp_path / "clean-evidence", spec=spec)
    prediction = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )
    store.record_prediction(prediction)

    with pytest.raises(
        LearningCleanEvidenceError,
        match="OUTCOME_MARKET_MISMATCH",
    ):
        store.record_outcome(_outcome(prediction, market="ETH"))

    with pytest.raises(
        LearningCleanEvidenceError,
        match="OUTCOME_DIRECTION_MISMATCH",
    ):
        store.record_outcome(_outcome(prediction, direction="short"))


def test_clean_evidence_store_detects_prediction_tampering(tmp_path) -> None:
    spec, predictor = _runtime(tmp_path)
    store = LearningCleanEvidenceStore(tmp_path / "clean-evidence", spec=spec)
    prediction = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )
    path = store.record_prediction(prediction)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["trade_eligible"] = False
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError):
        store.verify()


def test_clean_evidence_store_write_is_conflict_safe(tmp_path) -> None:
    spec, predictor = _runtime(tmp_path)
    store = LearningCleanEvidenceStore(tmp_path / "clean-evidence", spec=spec)
    prediction = predictor.score(
        feature_values=("HYPE", "long"),
        observed_at_ms=spec.validation_start_ms,
    )
    path = store.record_prediction(prediction)
    path.write_text('{"tampered":true}\n', encoding="utf-8")

    with pytest.raises(
        LearningCleanEvidenceError,
        match="LEARNING_CLEAN_EVIDENCE_CONFLICT",
    ):
        store.record_prediction(prediction)
