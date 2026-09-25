from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_shadow_admission import (
    build_learning_shadow_admission,
    write_learning_shadow_admission,
)
from cocomelon.research.learning_shadow_evidence import (
    LearningShadowEvidenceError,
    LearningShadowEvidenceStore,
    SHADOW_SOURCE_EVIDENCE_CLASS,
    open_verified_learning_shadow_evidence_store,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceRecord,
)
from tests.test_learning_shadow_admission import _approved_review


def _shadow_inputs(tmp_path):
    (
        package_root,
        spec_path,
        clean_evidence_root,
        score_path,
        finalization_path,
        _dossier,
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
        evidence_root=clean_evidence_root,
    )
    admission_path = write_learning_shadow_admission(
        tmp_path / "shadow-admission",
        admission,
    )
    return (
        package_root,
        spec_path,
        clean_evidence_root,
        score_path,
        finalization_path,
        dossier_path,
        decision,
        decision_path,
        admission,
        admission_path,
    )


def _record(
    *,
    admission,
    index: int,
    opened_at_ms: int | None = None,
    candidate_spec_id: str | None = None,
    source_class: str = SHADOW_SOURCE_EVIDENCE_CLASS,
) -> LearningEvidenceRecord:
    opened = (
        admission.shadow_start_ms + index * 1_000
        if opened_at_ms is None
        else opened_at_ms
    )
    closed = opened + 100
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=f"shadow-paper-{index}",
        source_evidence_class=source_class,
        candidate_id=admission.candidate_id,
        candidate_spec_id=(
            admission.shadow_admission_id
            if candidate_spec_id is None
            else candidate_spec_id
        ),
        campaign_id="shadow-campaign-1",
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=opened,
        closed_at_ms=closed,
        feature_snapshot_id=f"shadow-feature-{index}",
        research_eligible_at_ms=closed,
        gross_realized_pnl=Decimal("12"),
        entry_fees=Decimal("1"),
        exit_fees=Decimal("1"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.0001"),
        exit_slippage_fraction=Decimal("0.0001"),
        net_pnl=Decimal("10"),
        net_r=Decimal("0.10"),
    )


def test_shadow_evidence_store_accepts_only_post_review_bound_execution(
    tmp_path,
) -> None:
    (
        _package_root,
        _spec_path,
        _clean_evidence_root,
        _score_path,
        _finalization_path,
        _dossier_path,
        _decision,
        _decision_path,
        admission,
        _admission_path,
    ) = _shadow_inputs(tmp_path)
    store = LearningShadowEvidenceStore(
        tmp_path / "shadow-evidence",
        admission=admission,
    )
    record = _record(admission=admission, index=1)

    assert store.record_execution(record) is True
    assert store.record_execution(record) is False
    assert store.iter_records() == (record,)
    assert len(store.state_digest) == 64
    store.verify()


def test_shadow_evidence_rejects_pre_review_trade(tmp_path) -> None:
    *_, admission, _admission_path = _shadow_inputs(tmp_path)
    store = LearningShadowEvidenceStore(
        tmp_path / "shadow-evidence",
        admission=admission,
    )
    record = _record(
        admission=admission,
        index=1,
        opened_at_ms=admission.shadow_start_ms - 1,
    )

    with pytest.raises(
        LearningShadowEvidenceError,
        match="PRE_ADMISSION_TRADE",
    ):
        store.record_execution(record)


def test_shadow_evidence_rejects_clean_spec_identity(tmp_path) -> None:
    *_, admission, _admission_path = _shadow_inputs(tmp_path)
    store = LearningShadowEvidenceStore(
        tmp_path / "shadow-evidence",
        admission=admission,
    )
    record = _record(
        admission=admission,
        index=1,
        candidate_spec_id="f" * 64,
    )

    with pytest.raises(
        LearningShadowEvidenceError,
        match="ADMISSION_MISMATCH",
    ):
        store.record_execution(record)


def test_shadow_evidence_rejects_wrong_evidence_class(tmp_path) -> None:
    *_, admission, _admission_path = _shadow_inputs(tmp_path)
    store = LearningShadowEvidenceStore(
        tmp_path / "shadow-evidence",
        admission=admission,
    )
    record = _record(
        admission=admission,
        index=1,
        source_class="paper_execution",
    )

    with pytest.raises(
        LearningShadowEvidenceError,
        match="CLASS_INVALID",
    ):
        store.record_execution(record)


def test_shadow_evidence_open_reverifies_full_review_lineage(tmp_path) -> None:
    (
        package_root,
        spec_path,
        clean_evidence_root,
        score_path,
        finalization_path,
        dossier_path,
        _decision,
        decision_path,
        admission,
        admission_path,
    ) = _shadow_inputs(tmp_path)
    root = tmp_path / "shadow-evidence"
    store = open_verified_learning_shadow_evidence_store(
        root,
        shadow_admission_path=admission_path,
        review_decision_path=decision_path,
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
    )
    store.record_execution(_record(admission=admission, index=1))

    reopened = open_verified_learning_shadow_evidence_store(
        root,
        shadow_admission_path=admission_path,
        review_decision_path=decision_path,
        review_dossier_path=dossier_path,
        package_root=package_root,
        validation_spec_path=spec_path,
        validation_score_path=score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
    )
    assert len(reopened.iter_records()) == 1


def test_shadow_evidence_rejects_unexpected_file(tmp_path) -> None:
    *_, admission, _admission_path = _shadow_inputs(tmp_path)
    root = tmp_path / "shadow-evidence"
    store = LearningShadowEvidenceStore(root, admission=admission)
    store.record_execution(_record(admission=admission, index=1))
    (root / "notes.txt").write_text("unexpected\n", encoding="utf-8")

    with pytest.raises(
        LearningShadowEvidenceError,
        match="FILE_SET_INVALID",
    ):
        store.verify()
