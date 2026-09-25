from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.research.learning_clean_finalization import (
    build_learning_clean_finalization,
    write_learning_clean_finalization,
)
from cocomelon.research.learning_clean_review_dossier import (
    PROMOTION_GATE_STATUS,
    LearningCleanReviewDossierError,
    build_learning_clean_review_dossier,
    load_learning_clean_review_dossier,
    verify_learning_clean_review_dossier,
    write_learning_clean_review_dossier,
)
from tests.test_learning_clean_finalization import _complete_score


def _eligible_inputs(tmp_path):
    package_root, spec, spec_path, evidence_root, score, score_path = _complete_score(
        tmp_path,
        values=[Decimal("0.1")] * 20,
    )
    finalization = build_learning_clean_finalization(
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        evidence_root=evidence_root,
        finalized_at_ms=score.as_of_ms + 1,
    )
    finalization_path = write_learning_clean_finalization(
        tmp_path / "final",
        finalization,
    )
    return (
        package_root,
        spec,
        spec_path,
        evidence_root,
        score,
        score_path,
        finalization,
        finalization_path,
    )


def test_review_dossier_binds_terminal_clean_economics_without_authority(
    tmp_path,
) -> None:
    (
        package_root,
        spec,
        spec_path,
        evidence_root,
        score,
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

    assert dossier.candidate_id == finalization.candidate_id
    assert dossier.validation_spec_id == spec.spec_id
    assert dossier.validation_score_id == score.score_id
    assert dossier.finalization_id == finalization.finalization_id
    assert dossier.settled_trade_count == 20
    assert len(dossier.outcomes) == 20
    assert tuple(item.outcome_id for item in dossier.outcomes) == score.selected_outcome_ids
    assert dossier.overall_mean_net_r == Decimal("0.1")
    assert dossier.block_mean_net_r == (Decimal("0.1"),) * 4
    assert all(item.status == PROMOTION_GATE_STATUS for item in dossier.promotion_gates)
    assert len(dossier.promotion_gates) == 12
    assert dossier.human_review_required is True
    assert dossier.promotion_eligible is False
    assert dossier.execution_ready is False

    path = write_learning_clean_review_dossier(tmp_path / "dossier", dossier)
    assert load_learning_clean_review_dossier(path) == dossier
    assert verify_learning_clean_review_dossier(
        path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    ) == dossier


def test_review_dossier_rejects_failed_clean_validation(tmp_path) -> None:
    values = [Decimal("-0.1")] * 5 + [Decimal("0.1")] * 15
    package_root, _spec, spec_path, evidence_root, score, score_path = _complete_score(
        tmp_path,
        values=values,
    )
    finalization = build_learning_clean_finalization(
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        evidence_root=evidence_root,
        finalized_at_ms=score.as_of_ms,
    )
    finalization_path = write_learning_clean_finalization(
        tmp_path / "final",
        finalization,
    )

    with pytest.raises(
        LearningCleanReviewDossierError,
        match="NOT_REVIEW_ELIGIBLE",
    ):
        build_learning_clean_review_dossier(
            package_root=package_root,
            validation_spec_path=spec_path,
            validation_score_path=score_path,
            finalization_path=finalization_path,
            evidence_root=evidence_root,
        )


def test_review_dossier_detects_tampering(tmp_path) -> None:
    (
        package_root,
        _spec,
        spec_path,
        evidence_root,
        _score,
        score_path,
        _finalization,
        finalization_path,
    ) = _eligible_inputs(tmp_path)
    dossier = build_learning_clean_review_dossier(
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )
    path = write_learning_clean_review_dossier(tmp_path / "dossier", dossier)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["promotion_eligible"] = True
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(LearningCleanReviewDossierError):
        load_learning_clean_review_dossier(path)


def test_review_dossier_write_is_conflict_safe(tmp_path) -> None:
    (
        package_root,
        _spec,
        spec_path,
        evidence_root,
        _score,
        score_path,
        _finalization,
        finalization_path,
    ) = _eligible_inputs(tmp_path)
    dossier = build_learning_clean_review_dossier(
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )
    output = tmp_path / "dossier"

    first = write_learning_clean_review_dossier(output, dossier)
    second = write_learning_clean_review_dossier(output, dossier)
    assert first == second

    first.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(
        LearningCleanReviewDossierError,
        match="CONFLICT",
    ):
        write_learning_clean_review_dossier(output, dossier)
