from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_campaign_readiness import (
    FROZEN_OBSERVER_SOURCE_REVISION,
)
from cocomelon.research.prospective_context_evidence import (
    MAX_ENTRY_CANDLE_AGE_MS,
    ProspectiveEvidenceStore,
)
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
    control = {
        "kind": "prospective-hype-clean-control-plane",
        "candidate_spec_id": SPEC.spec_id,
        "validation_plan_id": PLAN.plan_id,
        "observer_source_revision": FROZEN_OBSERVER_SOURCE_REVISION,
        "schedule_cron": "3,8,13 * * * *",
        "attempt_minutes_utc": [3, 8, 13],
        "max_entry_candle_age_ms": MAX_ENTRY_CANDLE_AGE_MS,
        "state_artifact_name": "prospective-hype-clean-state",
        "evidence_root": "artifacts/prospective-hype-clean",
        "concurrency_group": "prospective-hype-clean-observer",
        "cancel_in_progress": False,
        "job_timeout_minutes": 10,
        "execution_mode": "paper",
        "api_url": "https://api.hyperliquid.xyz",
        "ws_url": "wss://api.hyperliquid.xyz/ws",
        "contents_permission": "read",
        "actions_permission": "read",
        "artifact_retention_days": 90,
        "schema_version": 1,
    }
    control["control_plane_id"] = hashlib.sha256(
        _canonical(control).encode("utf-8")
    ).hexdigest()
    (root / "control-plane.json").write_text(
        _canonical(control) + "\n",
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
    payload["schedule_cron"] = "4,9,14 * * * *"
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
