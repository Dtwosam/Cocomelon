from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.research.learning_candidate_freeze import (
    build_learning_candidate_freeze,
    write_learning_candidate_freeze,
)
from cocomelon.research.learning_candidate_package import (
    materialize_learning_candidate_package,
)
from cocomelon.research.learning_candidate_predictor import (
    LearningCandidatePrediction,
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
from cocomelon.research.learning_clean_validation_spec import (
    build_learning_clean_validation_spec,
    write_learning_clean_validation_spec,
)
from tests.test_learning_experiment import _run


def _setup(tmp_path):
    _experiment, experiment_root = _run(tmp_path)
    freeze = build_learning_candidate_freeze(
        experiment_root=experiment_root,
        frozen_at_ms=200_000,
    )
    freeze_path = write_learning_candidate_freeze(tmp_path / "freeze", freeze)
    package_root = tmp_path / "package"
    materialize_learning_candidate_package(
        experiment_root=experiment_root,
        candidate_freeze_path=freeze_path,
        package_root=package_root,
    )
    spec = build_learning_clean_validation_spec(package_root)
    spec_path = write_learning_clean_validation_spec(tmp_path / "spec", spec)
    evidence_root = tmp_path / "clean-evidence"
    return freeze, package_root, spec, spec_path, evidence_root


def _prediction(spec, *, index: int) -> LearningCandidatePrediction:
    return LearningCandidatePrediction(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        candidate_package_id=spec.candidate_package_id,
        experiment_id=spec.experiment_id,
        model_family=spec.model_family,
        observed_at_ms=spec.validation_start_ms + index * 1_000,
        feature_registry=("market", "direction"),
        feature_values=("HYPE", "long"),
        predicted_net_r=Decimal("0.1"),
        prediction_threshold=Decimal("0"),
        trade_eligible=True,
        reason_code="prediction_meets_threshold",
    )


def _append(
    evidence_root,
    *,
    spec,
    values: list[Decimal],
    offset: int = 0,
) -> None:
    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    for index, value in enumerate(values, start=1 + offset):
        prediction = _prediction(spec, index=index)
        store.record_prediction(prediction)
        opened_at_ms = prediction.observed_at_ms + 1
        store.record_outcome(
            LearningCleanTradeOutcome(
                prediction_id=prediction.prediction_id,
                candidate_id=spec.candidate_id,
                validation_spec_id=spec.spec_id,
                candidate_package_id=spec.candidate_package_id,
                source_trade_id=f"clean-paper-{index}",
                market="HYPE",
                direction="long",
                opened_at_ms=opened_at_ms,
                closed_at_ms=opened_at_ms + 100,
                net_r=value,
            )
        )


def test_clean_validation_score_stays_economically_blind_until_complete(
    tmp_path,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    _append(
        evidence_root,
        spec=spec,
        values=[Decimal("0.1")] * 19,
    )

    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert score.status == "collecting"
    assert score.eligible_settled_trade_count == 19
    assert len(score.selected_outcome_ids) == 19
    assert score.overall_mean_net_r is None
    assert score.blocks == ()
    assert score.qualifies_clean_validation is None
    assert score.promotion_eligible is False
    assert score.execution_ready is False


def test_clean_validation_score_counts_only_settled_trade_predictions(
    tmp_path,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    _append(
        evidence_root,
        spec=spec,
        values=[Decimal("0.1")] * 19,
    )
    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    unsettled = _prediction(spec, index=20)
    store.record_prediction(unsettled)

    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert unsettled.prediction_id in store.unsettled_trade_prediction_ids
    assert score.status == "collecting"
    assert score.eligible_settled_trade_count == 19
    assert score.qualifies_clean_validation is None


def test_clean_validation_score_freezes_first_twenty_settled_trades(
    tmp_path,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    _append(
        evidence_root,
        spec=spec,
        values=[Decimal("0.1")] * 20,
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
    selected = first.selected_outcome_ids

    _append(
        evidence_root,
        spec=spec,
        values=[Decimal("-100")],
        offset=20,
    )
    later = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 100_000,
    )

    assert later.eligible_settled_trade_count == 21
    assert later.selected_outcome_ids == selected
    assert later.overall_mean_net_r == Decimal("0.1")
    assert later.qualifies_clean_validation is True


def test_clean_validation_requires_every_stability_block_to_clear_floor(
    tmp_path,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    values = [Decimal("-0.1")] * 5 + [Decimal("0.1")] * 15
    _append(
        evidence_root,
        spec=spec,
        values=values,
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


def test_clean_validation_score_receipt_reverifies_and_rejects_tampering(
    tmp_path,
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
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)

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
