from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.research.learning_clean_review_decision import (
    DECISION_ADVANCE,
    DECISION_REJECT,
    build_learning_clean_review_decision,
    write_learning_clean_review_decision,
)
from cocomelon.research.learning_shadow_admission import (
    LearningShadowAdmissionError,
    build_learning_shadow_admission,
    load_learning_shadow_admission,
    verify_learning_shadow_admission,
    write_learning_shadow_admission,
)
from tests.test_learning_clean_review_decision import _review_inputs


def _approved_review(tmp_path):
    (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization,
        finalization_path,
        dossier,
        dossier_path,
    ) = _review_inputs(tmp_path)
    decision = build_learning_clean_review_decision(
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
        reviewer="reviewer@example",
        reviewed_at_ms=finalization.finalized_at_ms + 100,
        decision=DECISION_ADVANCE,
        rationale="Advance to the larger mainnet paper/shadow evaluation phase.",
    )
    decision_path = write_learning_clean_review_decision(
        tmp_path / "review-decision",
        decision,
    )
    return (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization_path,
        dossier,
        dossier_path,
        decision,
        decision_path,
    )


def test_shadow_admission_freezes_phase_11_floors_without_live_authority(
    tmp_path,
) -> None:
    (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization_path,
        dossier,
        dossier_path,
        decision,
        decision_path,
    ) = _approved_review(tmp_path)

    admission = build_learning_shadow_admission(
        review_decision_path=decision_path,
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )

    assert admission.candidate_id == dossier.candidate_id
    assert admission.review_decision_id == decision.review_decision_id
    assert admission.shadow_start_ms == decision.reviewed_at_ms
    assert admission.minimum_closed_mainnet_paper_trades == 500
    assert admission.minimum_shadow_calendar_days == 45
    assert admission.minimum_profit_factor == Decimal("1.20")
    assert admission.maximum_paper_drawdown_fraction == Decimal("0.08")
    assert admission.maximum_market_positive_pnl_fraction == Decimal("0.35")
    assert admission.maximum_seven_day_positive_pnl_fraction == Decimal("0.50")
    assert all(
        state == "not_yet_evaluated"
        for _requirement, state in admission.promotion_requirement_states
    )
    assert admission.shadow_evaluation_authorized is True
    assert admission.promotion_eligible is False
    assert admission.execution_ready is False
    assert admission.live_promotion_authorized is False


def test_shadow_admission_rejects_rejected_human_review(tmp_path) -> None:
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
    decision = build_learning_clean_review_decision(
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
        reviewer="reviewer@example",
        reviewed_at_ms=finalization.finalized_at_ms + 100,
        decision=DECISION_REJECT,
        rationale="Reject after clean review.",
    )
    decision_path = write_learning_clean_review_decision(
        tmp_path / "review-decision",
        decision,
    )

    with pytest.raises(
        LearningShadowAdmissionError,
        match="REVIEW_NOT_APPROVED",
    ):
        build_learning_shadow_admission(
            review_decision_path=decision_path,
            review_dossier_path=dossier_path,
            package_root=package_root,
            validation_spec_path=spec_path,
            validation_score_path=score_path,
            finalization_path=finalization_path,
            evidence_root=evidence_root,
        )


def test_shadow_admission_rejects_backfilled_start(tmp_path) -> None:
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

    with pytest.raises(
        LearningShadowAdmissionError,
        match="PRE_REVIEW_START",
    ):
        build_learning_shadow_admission(
            review_decision_path=decision_path,
            review_dossier_path=dossier_path,
            package_root=package_root,
            validation_spec_path=spec_path,
            validation_score_path=score_path,
            finalization_path=finalization_path,
            evidence_root=evidence_root,
            shadow_start_ms=decision.reviewed_at_ms - 1,
        )


def test_shadow_admission_write_verify_and_tamper_detection(tmp_path) -> None:
    (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization_path,
        _dossier,
        dossier_path,
        _decision,
        decision_path,
    ) = _approved_review(tmp_path)
    admission = build_learning_shadow_admission(
        review_decision_path=decision_path,
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )
    path = write_learning_shadow_admission(tmp_path / "shadow", admission)

    assert load_learning_shadow_admission(path) == admission
    assert verify_learning_shadow_admission(
        path,
        review_decision_path=decision_path,
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    ) == admission

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["promotion_eligible"] = True
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LearningShadowAdmissionError,
        match="INVALID",
    ):
        load_learning_shadow_admission(path)


def test_shadow_admission_dataclass_rejects_threshold_drift(tmp_path) -> None:
    (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization_path,
        _dossier,
        dossier_path,
        _decision,
        decision_path,
    ) = _approved_review(tmp_path)
    admission = build_learning_shadow_admission(
        review_decision_path=decision_path,
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )

    with pytest.raises(ValueError, match="paper-trade floor"):
        replace(admission, minimum_closed_mainnet_paper_trades=499)
    with pytest.raises(ValueError, match="profit-factor"):
        replace(admission, minimum_profit_factor=Decimal("1.10"))
    with pytest.raises(ValueError, match="live promotion"):
        replace(admission, promotion_eligible=True)
