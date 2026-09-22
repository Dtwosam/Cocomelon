from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_capture_transport import (
    FROZEN_OBSERVER_SOURCE_REVISION,
    build_control_plane_supersession,
    build_legacy_prospective_hype_control_plane,
    build_prospective_hype_control_plane,
)
from cocomelon.research.prospective_context_evidence import ProspectiveEvidenceStore
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_runtime_attestation import (
    ensure_prospective_runtime_attestation,
)
from cocomelon.research.prospective_state_readiness import (
    ProspectiveStateReadinessError,
    verify_prospective_hype_state_readiness,
)

SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
PLAN = HYPE_PROSPECTIVE_VALIDATION_V1


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _write_valid_state(root: Path) -> None:
    ProspectiveEvidenceStore(root, spec=SPEC)
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




def test_clean_pre_cutover_state_is_ready(tmp_path: Path) -> None:
    _write_valid_state(tmp_path)

    receipt = verify_prospective_hype_state_readiness(
        tmp_path,
        artifact_id="12345",
        audited_at_ms=PLAN.validation_start_ms - 1,
    )

    assert receipt.readiness_status == "ready_pre_cutover_state"
    assert receipt.observation_count == 0
    assert receipt.outcome_count == 0
    assert len(receipt.campaign_id) == 64
    assert len(receipt.state_digest) == 64
    assert len(receipt.runtime_attestation_id) == 64
    assert len(receipt.control_plane_id) == 64
    assert len(receipt.receipt_id) == 64


def test_control_plane_drift_fails_state_readiness(tmp_path: Path) -> None:
    _write_valid_state(tmp_path)
    path = tmp_path / "control-plane.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schedule_cron"] = "46 * * * *"
    path.write_text(_canonical(payload) + "\n", encoding="utf-8")

    with pytest.raises(
        ProspectiveStateReadinessError,
        match="CONTROL_PLANE_MISMATCH",
    ):
        verify_prospective_hype_state_readiness(
            tmp_path,
            artifact_id="12345",
            audited_at_ms=PLAN.validation_start_ms - 1,
        )


def test_runtime_source_drift_fails_state_readiness(tmp_path: Path) -> None:
    _write_valid_state(tmp_path)
    path = tmp_path / "runtime.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["observer_source_revision"] = "b" * 40
    identity = {
        "candidate_spec_id": payload["candidate_spec_id"],
        "validation_plan_id": payload["validation_plan_id"],
        "observer_source_revision": payload["observer_source_revision"],
        "schema_version": payload["schema_version"],
    }
    payload["attestation_id"] = hashlib.sha256(
        _canonical(identity).encode("utf-8")
    ).hexdigest()
    path.write_text(_canonical(payload) + "\n", encoding="utf-8")

    with pytest.raises(
        ProspectiveStateReadinessError,
        match="RUNTIME_SOURCE_REVISION_MISMATCH",
    ):
        verify_prospective_hype_state_readiness(
            tmp_path,
            artifact_id="12345",
            audited_at_ms=PLAN.validation_start_ms - 1,
        )


def test_missing_manifest_fails_state_readiness(tmp_path: Path) -> None:
    with pytest.raises(
        ProspectiveStateReadinessError,
        match="CAMPAIGN_MANIFEST_MISSING",
    ):
        verify_prospective_hype_state_readiness(
            tmp_path,
            artifact_id="12345",
            audited_at_ms=PLAN.validation_start_ms - 1,
        )


def test_legacy_control_plane_is_only_valid_for_empty_pre_cutover_state(
    tmp_path: Path,
) -> None:
    ProspectiveEvidenceStore(tmp_path, spec=SPEC)
    ensure_prospective_runtime_attestation(
        tmp_path,
        observer_source_revision=FROZEN_OBSERVER_SOURCE_REVISION,
        as_of_ms=PLAN.validation_start_ms - 2,
    )
    legacy = build_legacy_prospective_hype_control_plane()
    (tmp_path / "control-plane.json").write_text(
        _canonical(legacy) + "\n",
        encoding="utf-8",
    )

    receipt = verify_prospective_hype_state_readiness(
        tmp_path,
        artifact_id="101",
        audited_at_ms=PLAN.validation_start_ms - 1,
    )
    assert receipt.control_plane_id == legacy["control_plane_id"]

    with pytest.raises(
        ProspectiveStateReadinessError,
        match="LEGACY_CONTROL_PLANE_NOT_PRE_CUTOVER_EMPTY",
    ):
        verify_prospective_hype_state_readiness(
            tmp_path,
            artifact_id="101",
            audited_at_ms=PLAN.validation_start_ms,
        )


def test_current_control_plane_requires_immutable_supersession_receipt(
    tmp_path: Path,
) -> None:
    _write_valid_state(tmp_path)
    path = tmp_path / "control-plane-supersession.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["reason_code"] = "tampered"
    path.write_text(_canonical(payload) + "\n", encoding="utf-8")

    with pytest.raises(
        ProspectiveStateReadinessError,
        match="CONTROL_PLANE_SUPERSESSION",
    ):
        verify_prospective_hype_state_readiness(
            tmp_path,
            artifact_id="102",
            audited_at_ms=PLAN.validation_start_ms - 1,
        )
