from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.research.learning_clean_finalization import (
    VERDICT_ELIGIBLE,
    VERDICT_FAILED,
    LearningCleanFinalizationError,
    build_learning_clean_finalization,
    load_learning_clean_finalization,
    verify_learning_clean_finalization,
    write_learning_clean_finalization,
)
from cocomelon.research.learning_clean_validation_score import (
    score_learning_clean_validation,
    write_learning_clean_validation_score,
)
from tests.test_learning_clean_validation_score import _append, _setup


def _complete_score(tmp_path, *, values: list[Decimal]):
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    _append(evidence_root, spec=spec, values=values)
    score = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=spec_path,
        as_of_ms=spec.validation_start_ms + 100_000,
    )
    score_path = write_learning_clean_validation_score(tmp_path / "score", score)
    return package_root, spec, spec_path, evidence_root, score, score_path


def test_learning_clean_finalization_passes_only_verified_clean_gate(tmp_path) -> None:
    package_root, _spec, spec_path, evidence_root, score, score_path = _complete_score(
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

    assert finalization.validation_score_id == score.score_id
    assert finalization.verdict == VERDICT_ELIGIBLE
    assert finalization.eligible_for_candidate_review is True
    assert finalization.reason_codes == ()
    assert finalization.settled_trade_count == 20
    assert finalization.paper_only is True
    assert finalization.prospective_only is True
    assert finalization.research_only is True
    assert finalization.promotion_eligible is False
    assert finalization.execution_ready is False


def test_learning_clean_finalization_records_failed_clean_gate(tmp_path) -> None:
    values = [Decimal("-0.1")] * 5 + [Decimal("0.1")] * 15
    package_root, _spec, spec_path, evidence_root, score, score_path = _complete_score(
        tmp_path,
        values=values,
    )
    assert score.qualifies_clean_validation is False

    finalization = build_learning_clean_finalization(
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        evidence_root=evidence_root,
        finalized_at_ms=score.as_of_ms,
    )

    assert finalization.verdict == VERDICT_FAILED
    assert finalization.eligible_for_candidate_review is False
    assert finalization.reason_codes == ("clean_validation_gate_failed",)
    assert finalization.promotion_eligible is False
    assert finalization.execution_ready is False


def test_learning_clean_finalization_rejects_incomplete_score(tmp_path) -> None:
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
        as_of_ms=spec.validation_start_ms + 100_000,
    )
    score_path = write_learning_clean_validation_score(tmp_path / "score", score)

    with pytest.raises(
        LearningCleanFinalizationError,
        match="SCORE_INCOMPLETE",
    ):
        build_learning_clean_finalization(
            package_root=package_root,
            validation_spec_path=spec_path,
            validation_score_path=score_path,
            evidence_root=evidence_root,
            finalized_at_ms=score.as_of_ms,
        )


def test_learning_clean_finalization_rejects_premature_timestamp(tmp_path) -> None:
    package_root, _spec, spec_path, evidence_root, score, score_path = _complete_score(
        tmp_path,
        values=[Decimal("0.1")] * 20,
    )

    with pytest.raises(
        LearningCleanFinalizationError,
        match="PREMATURE",
    ):
        build_learning_clean_finalization(
            package_root=package_root,
            validation_spec_path=spec_path,
            validation_score_path=score_path,
            evidence_root=evidence_root,
            finalized_at_ms=score.as_of_ms - 1,
        )


def test_learning_clean_finalization_write_verify_and_tamper_detection(
    tmp_path,
) -> None:
    package_root, _spec, spec_path, evidence_root, score, score_path = _complete_score(
        tmp_path,
        values=[Decimal("0.1")] * 20,
    )
    finalization = build_learning_clean_finalization(
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        evidence_root=evidence_root,
        finalized_at_ms=score.as_of_ms,
    )
    path = write_learning_clean_finalization(tmp_path / "final", finalization)

    assert load_learning_clean_finalization(path) == finalization
    assert verify_learning_clean_finalization(
        path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        evidence_root=evidence_root,
    ) == finalization
    assert write_learning_clean_finalization(tmp_path / "final", finalization) == path

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["finalization_id"] = "0" * 64
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LearningCleanFinalizationError,
        match="ID_MISMATCH",
    ):
        load_learning_clean_finalization(path)
