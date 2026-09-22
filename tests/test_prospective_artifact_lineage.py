from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_artifact_lineage import (
    ProspectiveArtifactLineageError,
    verify_prospective_hype_artifact_lineage,
)
from cocomelon.research.prospective_capture_transport import (
    FROZEN_OBSERVER_SOURCE_REVISION,
    build_control_plane_supersession,
    build_legacy_prospective_hype_control_plane,
    build_prospective_hype_control_plane,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveEvidenceStore,
    ProspectiveObservation,
    ProspectiveOutcome,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_runtime_attestation import (
    ensure_prospective_runtime_attestation,
)

SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
PLAN = HYPE_PROSPECTIVE_VALIDATION_V1
HOUR = 3_600_000


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _write_valid_state(root: Path) -> ProspectiveEvidenceStore:
    store = ProspectiveEvidenceStore(root, spec=SPEC)
    ensure_prospective_runtime_attestation(
        root,
        observer_source_revision=FROZEN_OBSERVER_SOURCE_REVISION,
        as_of_ms=PLAN.validation_start_ms - 1,
    )
    control = build_prospective_hype_control_plane()
    (root / "control-plane.json").write_text(
        _canonical(control) + "\n",
        encoding="utf-8",
    )
    supersession = build_control_plane_supersession(
        superseded_at_ms=PLAN.validation_start_ms - 1,
    )
    (root / "control-plane-supersession.json").write_text(
        _canonical(supersession) + "\n",
        encoding="utf-8",
    )
    return store




def _observation(anchor_end_ms: int) -> ProspectiveObservation:
    target_end_ms = anchor_end_ms + SPEC.horizon_ms
    return ProspectiveObservation(
        candidate_spec_id=SPEC.spec_id,
        raw_decision_id=f"decision-{anchor_end_ms}",
        market=SPEC.market,
        decision_as_of_ms=anchor_end_ms + 1_000,
        source_received_at_ms=anchor_end_ms + 500,
        anchor_end_ms=anchor_end_ms,
        target_end_ms=target_end_ms,
        raw_direction=Direction.LONG,
        effective_direction=Direction.LONG,
        hold_until_ms=target_end_ms,
        context_state_1h=SPEC.context_state_1h,
        feature_snapshot_id=f"feature-{anchor_end_ms}",
        cross_market_snapshot_id=f"cross-{anchor_end_ms}",
        entry_candle_id=f"entry-{anchor_end_ms}",
        entry_px=Decimal("100"),
        modeled_cost_fraction=SPEC.costs.total_cost_fraction(SPEC.horizon_ms),
        reason_codes=("frozen_candidate_match",),
    )


def _outcome(observation: ProspectiveObservation) -> ProspectiveOutcome:
    gross_return = Decimal("0.01")
    return ProspectiveOutcome(
        candidate_spec_id=SPEC.spec_id,
        observation_id=observation.observation_id,
        market=observation.market,
        anchor_end_ms=observation.anchor_end_ms,
        target_end_ms=observation.target_end_ms,
        direction=observation.effective_direction,
        entry_px=observation.entry_px,
        exit_px=Decimal("101"),
        exit_candle_id=f"exit-{observation.target_end_ms}",
        exit_source_received_at_ms=observation.target_end_ms + 1_000,
        gross_return=gross_return,
        modeled_cost_fraction=observation.modeled_cost_fraction,
        net_return=gross_return - observation.modeled_cost_fraction,
    )


def _copy_state(previous: Path, current: Path) -> ProspectiveEvidenceStore:
    shutil.copytree(previous, current)
    return ProspectiveEvidenceStore(current, spec=SPEC)


def _audit(
    previous: Path,
    current: Path,
    *,
    previous_ms: int,
    current_ms: int,
):
    return verify_prospective_hype_artifact_lineage(
        previous,
        current,
        previous_artifact_id="1001",
        current_artifact_id="1002",
        previous_audited_at_ms=previous_ms,
        current_audited_at_ms=current_ms,
    )


def test_append_only_state_growth_produces_lineage_receipt(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    previous_store = _write_valid_state(previous)

    first = _observation(PLAN.first_expected_anchor_ms)
    previous_store.record_observation(first)
    previous_store.record_outcome(_outcome(first))

    current_store = _copy_state(previous, current)
    second = _observation(PLAN.first_expected_anchor_ms + 5 * HOUR)
    current_store.record_observation(second)
    current_store.record_outcome(_outcome(second))

    receipt = _audit(
        previous,
        current,
        previous_ms=PLAN.validation_start_ms + 8 * HOUR,
        current_ms=PLAN.validation_start_ms + 12 * HOUR,
    )

    assert receipt.lineage_status == "append_only_valid"
    assert receipt.previous_observation_count == 1
    assert receipt.current_observation_count == 2
    assert receipt.previous_outcome_count == 1
    assert receipt.current_outcome_count == 2
    assert receipt.appended_observation_ids == (second.observation_id,)
    assert receipt.appended_outcome_ids == (_outcome(second).outcome_id,)
    assert len(receipt.receipt_id) == 64


def test_outcome_only_settlement_is_valid_lineage_progression(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    previous_store = _write_valid_state(previous)

    observation = _observation(PLAN.first_expected_anchor_ms)
    previous_store.record_observation(observation)

    current_store = _copy_state(previous, current)
    outcome = _outcome(observation)
    current_store.record_outcome(outcome)

    receipt = _audit(
        previous,
        current,
        previous_ms=PLAN.validation_start_ms + 2 * HOUR,
        current_ms=PLAN.validation_start_ms + 6 * HOUR,
    )

    assert receipt.previous_observation_count == receipt.current_observation_count == 1
    assert receipt.previous_outcome_count == 0
    assert receipt.current_outcome_count == 1
    assert receipt.appended_observation_ids == ()
    assert receipt.appended_outcome_ids == (outcome.outcome_id,)
    assert receipt.previous_state_digest != receipt.current_state_digest


def test_deleted_prior_observation_fails_lineage(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    previous_store = _write_valid_state(previous)

    observation = _observation(PLAN.first_expected_anchor_ms)
    path = previous_store.record_observation(observation)

    _copy_state(previous, current)
    (current / path.relative_to(previous)).unlink()

    with pytest.raises(
        ProspectiveArtifactLineageError,
        match="CURRENT_OBSERVATION_REMOVED",
    ):
        _audit(
            previous,
            current,
            previous_ms=PLAN.validation_start_ms + 2 * HOUR,
            current_ms=PLAN.validation_start_ms + 3 * HOUR,
        )


def test_late_backfill_of_older_anchor_fails_lineage(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    previous_store = _write_valid_state(previous)

    later = _observation(PLAN.first_expected_anchor_ms + 5 * HOUR)
    previous_store.record_observation(later)

    current_store = _copy_state(previous, current)
    older = _observation(PLAN.first_expected_anchor_ms + 4 * HOUR)
    current_store.record_observation(older)

    with pytest.raises(
        ProspectiveArtifactLineageError,
        match="HISTORICAL_OBSERVATION_BACKFILL_FORBIDDEN",
    ):
        _audit(
            previous,
            current,
            previous_ms=PLAN.validation_start_ms + 7 * HOUR,
            current_ms=PLAN.validation_start_ms + 8 * HOUR,
        )


def test_orphan_outcome_fails_lineage(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_valid_state(previous)
    current_store = _copy_state(previous, current)

    missing = _observation(PLAN.first_expected_anchor_ms)
    current_store.record_outcome(_outcome(missing))

    with pytest.raises(
        ProspectiveArtifactLineageError,
        match="CURRENT_ORPHAN_OUTCOME",
    ):
        _audit(
            previous,
            current,
            previous_ms=PLAN.validation_start_ms + HOUR,
            current_ms=PLAN.validation_start_ms + 6 * HOUR,
        )


def test_same_record_set_requires_same_state_digest(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    previous_store = _write_valid_state(previous)

    observation = _observation(PLAN.first_expected_anchor_ms)
    previous_store.record_observation(observation)
    _copy_state(previous, current)

    receipt = _audit(
        previous,
        current,
        previous_ms=PLAN.validation_start_ms + 2 * HOUR,
        current_ms=PLAN.validation_start_ms + 3 * HOUR,
    )

    assert receipt.appended_observation_ids == ()
    assert receipt.appended_outcome_ids == ()
    assert receipt.previous_state_digest == receipt.current_state_digest



def test_off_grid_observation_fails_lineage(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_valid_state(previous)
    current_store = _copy_state(previous, current)

    current_store.record_observation(
        _observation(PLAN.first_expected_anchor_ms + 1)
    )

    with pytest.raises(
        ProspectiveArtifactLineageError,
        match="CURRENT_OBSERVATION_OFF_FROZEN_ANCHOR_GRID",
    ):
        _audit(
            previous,
            current,
            previous_ms=PLAN.validation_start_ms,
            current_ms=PLAN.validation_start_ms + 2 * HOUR,
        )


def test_future_dated_observation_fails_lineage(tmp_path: Path) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    _write_valid_state(previous)
    current_store = _copy_state(previous, current)

    current_store.record_observation(
        _observation(PLAN.first_expected_anchor_ms)
    )

    with pytest.raises(
        ProspectiveArtifactLineageError,
        match="CURRENT_FUTURE_DATED_OBSERVATION",
    ):
        _audit(
            previous,
            current,
            previous_ms=PLAN.validation_start_ms,
            current_ms=PLAN.first_expected_anchor_ms + 500,
        )


def test_pre_cutover_control_plane_supersession_preserves_lineage(
    tmp_path: Path,
) -> None:
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    ProspectiveEvidenceStore(previous, spec=SPEC)
    ensure_prospective_runtime_attestation(
        previous,
        observer_source_revision=FROZEN_OBSERVER_SOURCE_REVISION,
        as_of_ms=PLAN.validation_start_ms - 3,
    )
    legacy = build_legacy_prospective_hype_control_plane()
    (previous / "control-plane.json").write_text(
        _canonical(legacy) + "\n",
        encoding="utf-8",
    )
    shutil.copytree(previous, current)

    replacement = build_prospective_hype_control_plane()
    (current / "control-plane.json").write_text(
        _canonical(replacement) + "\n",
        encoding="utf-8",
    )
    supersession = build_control_plane_supersession(
        superseded_at_ms=PLAN.validation_start_ms - 2,
    )
    (current / "control-plane-supersession.json").write_text(
        _canonical(supersession) + "\n",
        encoding="utf-8",
    )

    receipt = _audit(
        previous,
        current,
        previous_ms=PLAN.validation_start_ms - 3,
        current_ms=PLAN.validation_start_ms - 1,
    )

    assert receipt.control_plane_id == replacement["control_plane_id"]
    assert receipt.appended_observation_ids == ()
    assert receipt.appended_outcome_ids == ()
