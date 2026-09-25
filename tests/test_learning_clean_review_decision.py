from __future__ import annotations

import json

import pytest

from cocomelon.research.learning_clean_review_decision import (
    DECISION_ADVANCE,
    DECISION_REJECT,
    LearningCleanReviewDecisionError,
    build_learning_clean_review_decision,
    load_learning_clean_review_decision,
    verify_learning_clean_review_decision,
    write_learning_clean_review_decision,
)
from cocomelon.research.learning_clean_review_dossier import (
    build_learning_clean_review_dossier,
    write_learning_clean_review_dossier,
)
from tests.test_learning_clean_review_dossier import _eligible_inputs


def _review_inputs(tmp_path):
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
    dossier = build_learning_clean_review_dossier(
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )
    dossier_path = write_learning_clean_review_dossier(
        tmp_path / "dossier",
        dossier,
    )
    return (
        package_root,
        spec_path,
        evidence_root,
        score_path,
        finalization,
        finalization_path,
        dossier,
        dossier_path,
    )


def test_review_decision_can_advance_only_to_shadow_evaluation(tmp_path) -> None:
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
        reviewed_at_ms=finalization.finalized_at_ms + 1,
        decision=DECISION_ADVANCE,
        rationale="Advance the frozen clean candidate to larger paper shadow evaluation.",
    )

    assert decision.candidate_id == dossier.candidate_id
    assert decision.review_dossier_id == dossier.dossier_id
    assert decision.shadow_evaluation_authorized is True
    assert decision.human_review_completed is True
    assert decision.paper_only is True
    assert decision.research_only is True
    assert decision.promotion_eligible is False
    assert decision.execution_ready is False
    assert decision.live_promotion_authorized is False


def test_review_decision_can_reject_without_shadow_authority(tmp_path) -> None:
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
        reviewed_at_ms=finalization.finalized_at_ms,
        decision=DECISION_REJECT,
        rationale="Reject after terminal clean review.",
    )

    assert decision.shadow_evaluation_authorized is False
    assert decision.live_promotion_authorized is False


def test_review_decision_rejects_premature_review(tmp_path) -> None:
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

    with pytest.raises(
        LearningCleanReviewDecisionError,
        match="PREMATURE",
    ):
        build_learning_clean_review_decision(
            review_dossier_path=dossier_path,
            package_root=package_root,
            validation_spec_path=spec_path,
            validation_score_path=score_path,
            finalization_path=finalization_path,
            evidence_root=evidence_root,
            reviewer="reviewer@example",
            reviewed_at_ms=finalization.finalized_at_ms - 1,
            decision=DECISION_ADVANCE,
            rationale="Premature decision must fail.",
        )


def test_review_decision_write_verify_and_tamper_detection(tmp_path) -> None:
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
        reviewed_at_ms=finalization.finalized_at_ms,
        decision=DECISION_ADVANCE,
        rationale="Proceed to paper shadow evaluation only.",
    )
    path = write_learning_clean_review_decision(tmp_path / "decision", decision)

    assert load_learning_clean_review_decision(path) == decision
    assert verify_learning_clean_review_decision(
        path,
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    ) == decision
    assert write_learning_clean_review_decision(tmp_path / "decision", decision) == path

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["live_promotion_authorized"] = True
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LearningCleanReviewDecisionError):
        load_learning_clean_review_decision(path)


def test_review_decision_conflicting_rewrite_fails_closed(tmp_path) -> None:
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
    advance = build_learning_clean_review_decision(
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
        reviewer="reviewer@example",
        reviewed_at_ms=finalization.finalized_at_ms,
        decision=DECISION_ADVANCE,
        rationale="Advance to shadow evaluation.",
    )
    reject = build_learning_clean_review_decision(
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
        reviewer="reviewer@example",
        reviewed_at_ms=finalization.finalized_at_ms,
        decision=DECISION_REJECT,
        rationale="Reject candidate.",
    )
    output = tmp_path / "decision"
    write_learning_clean_review_decision(output, advance)

    with pytest.raises(
        LearningCleanReviewDecisionError,
        match="CONFLICT",
    ):
        write_learning_clean_review_decision(output, reject)
