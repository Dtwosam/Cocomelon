from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.research.learning_candidate_predictor import (
    build_learning_candidate_predictor,
)
from cocomelon.research.learning_clean_evidence import (
    LearningCleanEvidenceStore,
    LearningCleanTradeOutcome,
)
from cocomelon.research.learning_clean_validation_score import (
    LearningCleanValidationScoreError,
    load_learning_clean_validation_score,
    score_learning_clean_validation,
    verify_learning_clean_validation_score,
    write_learning_clean_validation_score,
)
from tests.test_learning_candidate_predictor import _package_from_experiment
from tests.test_learning_experiment import _run


def _setup(tmp_path):
    _experiment, experiment_root = _run(tmp_path)
    _freeze, package_root, spec, spec_path = _package_from_experiment(
        tmp_path,
        experiment_root=experiment_root,
    )
    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=spec_path,
    )
    evidence_root = tmp_path / "clean-evidence"
    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    return package_root, spec, spec_path, predictor, store, evidence_root


def _append_outcomes(
    store,
    predictor,
    spec,
    values,
    *,
    offset: int = 0,
) -> None:
    for index, value in enumerate(values, start=1 + offset):
        observed = spec.validation_start_ms + index * 1_000
        prediction = predictor.score(
            feature_values=("HYPE", "long"),
            observed_at_ms=observed,
        )
        assert prediction.trade_eligible is True
        store.record_prediction(prediction)
        store.record_outcome(
            LearningCleanTradeOutcome(
                prediction_id=prediction.prediction_id,
                candidate_id=prediction.candidate_id,
                validation_spec_id=prediction.validation_spec_id,
                candidate_package_id=prediction.candidate_package_id,
                source_trade_id=f"clean-paper-{index}",
                market="HYPE",
                direction="long",
                opened_at_ms=observed + 1,
                closed_at_ms=observed + 2,
                net_r=value,
            )
        )


def test_clean_validation_score_is_blind_until_twenty_settle(tmp_path) -> None:
    package_root, spec, spec_path, predictor, store, evidence_root = _setup(tmp_path)
    _append_outcomes(
        store,
        predictor,
        spec,
        [Decimal("0.1")] * 19,
    )

    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert score.status == "collecting"
    assert score.eligible_settled_trade_count == 19
    assert len(score.selected_prediction_ids) == 19
    assert len(score.selected_outcome_ids) == 19
    assert score.overall_mean_net_r is None
    assert score.blocks == ()
    assert score.qualifies_clean_validation is None
    assert score.promotion_eligible is False
    assert score.execution_ready is False


def test_clean_validation_score_freezes_first_twenty_after_completion(tmp_path) -> None:
    package_root, spec, spec_path, predictor, store, evidence_root = _setup(tmp_path)
    _append_outcomes(
        store,
        predictor,
        spec,
        [Decimal("0.1")] * 20,
    )
    first = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert first.status == "complete"
    assert first.qualifies_clean_validation is True
    assert first.overall_mean_net_r == Decimal("0.1")
    assert [block.mean_net_r for block in first.blocks] == [Decimal("0.1")] * 4
    prediction_ids = first.selected_prediction_ids
    outcome_ids = first.selected_outcome_ids
    sample_digest = first.evidence_sample_digest

    _append_outcomes(
        store,
        predictor,
        spec,
        [Decimal("-100")],
        offset=20,
    )
    later = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 100_000,
    )

    assert later.eligible_settled_trade_count == 21
    assert later.selected_prediction_ids == prediction_ids
    assert later.selected_outcome_ids == outcome_ids
    assert later.evidence_sample_digest == sample_digest
    assert later.overall_mean_net_r == Decimal("0.1")
    assert later.qualifies_clean_validation is True


def test_clean_validation_score_requires_each_block_above_zero(tmp_path) -> None:
    package_root, spec, spec_path, predictor, store, evidence_root = _setup(tmp_path)
    _append_outcomes(
        store,
        predictor,
        spec,
        [Decimal("-0.1")] * 5 + [Decimal("0.1")] * 15,
    )

    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert score.status == "complete"
    assert score.overall_mean_net_r == Decimal("0.05")
    assert score.blocks[0].mean_net_r == Decimal("-0.1")
    assert score.qualifies_clean_validation is False


def test_clean_validation_score_uses_settlement_order(tmp_path) -> None:
    package_root, spec, spec_path, predictor, store, evidence_root = _setup(tmp_path)
    predictions = []
    for index in range(1, 22):
        observed = spec.validation_start_ms + index * 1_000
        prediction = predictor.score(
            feature_values=("HYPE", "long"),
            observed_at_ms=observed,
        )
        store.record_prediction(prediction)
        predictions.append(prediction)

    for index, prediction in enumerate(predictions, start=1):
        closed = spec.validation_start_ms + (22 - index) * 2_000
        store.record_outcome(
            LearningCleanTradeOutcome(
                prediction_id=prediction.prediction_id,
                candidate_id=prediction.candidate_id,
                validation_spec_id=prediction.validation_spec_id,
                candidate_package_id=prediction.candidate_package_id,
                source_trade_id=f"reverse-settle-{index}",
                market="HYPE",
                direction="long",
                opened_at_ms=prediction.observed_at_ms + 1,
                closed_at_ms=max(closed, prediction.observed_at_ms + 1),
                net_r=Decimal("0.1"),
            )
        )

    ordered = store.iter_outcomes()
    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 100_000,
    )

    assert score.selected_outcome_ids == tuple(
        item.outcome_id for item in ordered[:20]
    )
    assert score.selected_prediction_ids == tuple(
        item.prediction_id for item in ordered[:20]
    )


def test_clean_validation_score_receipt_reverifies_and_detects_tampering(
    tmp_path,
) -> None:
    package_root, spec, spec_path, predictor, store, evidence_root = _setup(tmp_path)
    _append_outcomes(
        store,
        predictor,
        spec,
        [Decimal("0.1")] * 20,
    )
    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )
    path = write_learning_clean_validation_score(tmp_path / "score", score)

    assert load_learning_clean_validation_score(path) == score
    assert verify_learning_clean_validation_score(
        path,
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
    ) == score

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["qualifies_clean_validation"] = False
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LearningCleanValidationScoreError,
        match="SCORE_ID_MISMATCH",
    ):
        load_learning_clean_validation_score(path)


def test_clean_validation_score_rejects_prestart_scoring(tmp_path) -> None:
    package_root, spec, spec_path, _predictor, _store, evidence_root = _setup(tmp_path)

    with pytest.raises(
        LearningCleanValidationScoreError,
        match="BEFORE_START",
    ):
        score_learning_clean_validation(
            evidence_root=evidence_root,
            package_root=package_root,
            validation_spec_path=spec_path,
            as_of_ms=spec.validation_start_ms - 1,
        )
