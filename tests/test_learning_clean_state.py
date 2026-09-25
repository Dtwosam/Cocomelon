from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cocomelon.research.learning_clean_evidence import LearningCleanEvidenceStore
from cocomelon.research.learning_clean_state import (
    LearningCleanStateError,
    build_learning_clean_state,
    load_learning_clean_state,
    verify_learning_clean_state,
    write_learning_clean_state,
)
from tests.test_learning_clean_validation_score import _append, _prediction, _setup


def test_clean_state_waits_before_validation_start(tmp_path) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)

    state = build_learning_clean_state(
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        as_of_ms=spec.validation_start_ms - 1,
    )

    assert state.status == "waiting_for_validation_start"
    assert state.prediction_count == 0
    assert state.settled_outcome_count == 0
    assert state.unsettled_trade_prediction_count == 0
    assert state.promotion_eligible is False
    assert state.execution_ready is False


def test_clean_state_collects_after_start_and_tracks_unsettled_predictions(
    tmp_path,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    store.record_prediction(_prediction(spec, index=1))

    state = build_learning_clean_state(
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        as_of_ms=spec.validation_start_ms + 5_000,
    )

    assert state.status == "collecting"
    assert state.prediction_count == 1
    assert state.settled_outcome_count == 0
    assert state.unsettled_trade_prediction_count == 1


def test_clean_state_becomes_ready_only_after_target_settled_outcomes(
    tmp_path,
) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    _append(
        evidence_root,
        spec=spec,
        values=[Decimal("0.1")] * 20,
    )

    state = build_learning_clean_state(
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        as_of_ms=spec.validation_start_ms + 50_000,
    )

    assert state.status == "ready_to_score"
    assert state.prediction_count == 20
    assert state.settled_outcome_count == 20
    assert state.unsettled_trade_prediction_count == 0
    payload = state.to_dict()
    assert "overall_mean_net_r" not in payload
    assert "qualifies_clean_validation" not in payload
    assert "net_r" not in payload
    assert "pnl" not in json.dumps(payload).lower()


def test_clean_state_rejects_evidence_from_the_future(tmp_path) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    future = _prediction(spec, index=10)
    store.record_prediction(future)

    with pytest.raises(
        LearningCleanStateError,
        match="FUTURE_PREDICTION",
    ):
        build_learning_clean_state(
            package_root=package_root,
            validation_spec_path=spec_path,
            evidence_root=evidence_root,
            as_of_ms=future.observed_at_ms - 1,
        )


def test_clean_state_receipt_reverifies_and_rejects_tampering(tmp_path) -> None:
    _freeze, package_root, spec, spec_path, evidence_root = _setup(tmp_path)
    state = build_learning_clean_state(
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
        as_of_ms=spec.validation_start_ms,
    )
    path = write_learning_clean_state(tmp_path / "state", state)

    assert load_learning_clean_state(path) == state
    assert verify_learning_clean_state(
        path,
        package_root=package_root,
        validation_spec_path=spec_path,
        evidence_root=evidence_root,
    ) == state

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "ready_to_score"
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        LearningCleanStateError,
        match="STATE_ID_MISMATCH",
    ):
        load_learning_clean_state(path)
