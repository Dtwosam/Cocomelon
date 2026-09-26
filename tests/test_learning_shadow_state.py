from __future__ import annotations

import json

import pytest

from cocomelon.research.learning_shadow_evidence import (
    LearningShadowEvidenceStore,
)
from cocomelon.research.learning_shadow_state import (
    LearningShadowStateError,
    build_learning_shadow_state,
    load_learning_shadow_state,
    verify_learning_shadow_state,
    write_learning_shadow_state,
)
from tests.test_learning_shadow_evidence import _record, _shadow_inputs


def _kwargs(tmp_path):
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
    evidence_root = tmp_path / "shadow-evidence"
    return admission, evidence_root, {
        "shadow_evidence_root": evidence_root,
        "shadow_admission_path": admission_path,
        "review_decision_path": decision_path,
        "review_dossier_path": dossier_path,
        "package_root": package_root,
        "validation_spec_path": spec_path,
        "validation_score_path": score_path,
        "finalization_path": finalization_path,
        "clean_evidence_root": clean_evidence_root,
    }


def test_shadow_state_is_empty_and_non_economic_before_start(tmp_path) -> None:
    admission, _evidence_root, kwargs = _kwargs(tmp_path)

    state = build_learning_shadow_state(
        **kwargs,
        as_of_ms=admission.shadow_start_ms - 1,
    )

    assert state.status == "waiting_for_shadow_start"
    assert state.closed_paper_trade_count == 0
    assert state.campaign_count == 0
    assert state.first_opened_at_ms is None
    assert state.latest_closed_at_ms is None
    assert state.minimum_closed_mainnet_paper_trades == 500
    assert state.minimum_shadow_calendar_days == 45
    assert state.paper_only is True
    assert state.research_only is True
    assert state.promotion_eligible is False
    assert state.execution_ready is False
    assert state.live_promotion_authorized is False


def test_shadow_state_counts_post_review_evidence_without_economics(tmp_path) -> None:
    admission, evidence_root, kwargs = _kwargs(tmp_path)
    store = LearningShadowEvidenceStore(evidence_root, admission=admission)
    first = _record(admission=admission, index=1)
    second = _record(admission=admission, index=2)
    store.record_execution(first)
    store.record_execution(second)

    state = build_learning_shadow_state(
        **kwargs,
        as_of_ms=second.research_eligible_at_ms,
    )

    assert state.status == "collecting"
    assert state.closed_paper_trade_count == 2
    assert state.campaign_count == 1
    assert state.first_opened_at_ms == first.opened_at_ms
    assert state.latest_closed_at_ms == second.closed_at_ms
    assert state.shadow_evidence_state_digest == store.state_digest
    assert "net" not in state.to_dict()
    assert "pnl" not in state.to_dict()
    assert "profit_factor" not in state.to_dict()


def test_shadow_state_rejects_future_evidence(tmp_path) -> None:
    admission, evidence_root, kwargs = _kwargs(tmp_path)
    store = LearningShadowEvidenceStore(evidence_root, admission=admission)
    record = _record(admission=admission, index=1)
    store.record_execution(record)

    with pytest.raises(
        LearningShadowStateError,
        match="LEARNING_SHADOW_STATE_FUTURE_EVIDENCE",
    ):
        build_learning_shadow_state(
            **kwargs,
            as_of_ms=record.closed_at_ms - 1,
        )


def test_shadow_state_receipt_reverifies_and_rejects_tampering(tmp_path) -> None:
    admission, evidence_root, kwargs = _kwargs(tmp_path)
    store = LearningShadowEvidenceStore(evidence_root, admission=admission)
    record = _record(admission=admission, index=1)
    store.record_execution(record)
    state = build_learning_shadow_state(
        **kwargs,
        as_of_ms=record.research_eligible_at_ms,
    )
    path = write_learning_shadow_state(tmp_path / "state", state)

    assert load_learning_shadow_state(path) == state
    assert verify_learning_shadow_state(path, **kwargs) == state

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["closed_paper_trade_count"] = 0
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LearningShadowStateError,
        match="LEARNING_SHADOW_STATE_ID_MISMATCH",
    ):
        load_learning_shadow_state(path)
