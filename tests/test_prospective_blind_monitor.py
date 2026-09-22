from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_blind_monitor import (
    ProspectiveBlindMonitorError,
    build_prospective_hype_blind_monitor,
    verify_prospective_hype_blind_monitor_receipt,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveCampaignManifest,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
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


def _with_identity(payload: dict[str, object], field: str) -> dict[str, object]:
    resolved = dict(payload)
    resolved[field] = hashlib.sha256(
        _canonical(payload).encode("utf-8")
    ).hexdigest()
    return resolved


def _health_payload() -> dict[str, object]:
    blocks = [
        {
            "block_index": index,
            "settled_trade_count": 0,
            "effective_trade_count": 0,
            "remaining_expected_anchors": 270,
            "maximum_possible_settled_trades": 270,
            "required_settled_trades": PLAN.min_block_trades,
            "recoverable": True,
        }
        for index in range(1, 5)
    ]
    payload = {
        "validation_report_id": "d" * 64,
        "plan_id": PLAN.plan_id,
        "as_of_ms": PLAN.validation_start_ms - 1,
        "status": "pre_validation",
        "expected_anchor_count": PLAN.expected_anchor_count,
        "expected_anchor_count_to_date": 0,
        "observation_count_to_date": 0,
        "remaining_expected_anchors": PLAN.expected_anchor_count,
        "required_final_observation_count": 972,
        "missed_anchor_budget": 108,
        "missed_anchor_count_to_date": 0,
        "remaining_missed_anchor_budget": 108,
        "maximum_final_observation_count": PLAN.expected_anchor_count,
        "maximum_final_capture_coverage": "1",
        "effective_trade_count": 0,
        "settled_trade_count": 0,
        "remaining_trade_opportunities_upper_bound": PLAN.expected_anchor_count,
        "maximum_possible_settled_trades": PLAN.expected_anchor_count,
        "required_settled_trades": PLAN.min_settled_trades,
        "overdue_unsettled_count": 0,
        "block_recoverability": blocks,
        "irrecoverable_reasons": [],
        "schema_version": 1,
    }
    return _with_identity(payload, "health_id")


def _lineage_payload(*, state_artifact_id: str = "101") -> dict[str, object]:
    campaign_id = ProspectiveCampaignManifest(
        candidate_spec_id=SPEC.spec_id,
        candidate_id=SPEC.candidate_id,
        validation_not_before_ms=SPEC.validation_not_before_ms,
    ).campaign_id
    payload = {
        "previous_artifact_id": "100",
        "current_artifact_id": state_artifact_id,
        "current_audited_at_ms": PLAN.validation_start_ms - 1,
        "lineage_status": "waiting_for_second_frozen_format_state",
        "reason_code": "previous_artifact_predates_control_plane_freeze",
        "campaign_id": campaign_id,
        "runtime_attestation_id": "a" * 64,
        "control_plane_id": "b" * 64,
        "current_state_digest": "c" * 64,
        "current_observation_count": 0,
        "current_outcome_count": 0,
        "schema_version": 1,
    }
    return _with_identity(payload, "receipt_id")


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(_canonical(payload) + "\n", encoding="utf-8")


def test_blind_monitor_reports_only_operational_campaign_health(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    lineage = tmp_path / "lineage.json"
    _write(health, _health_payload())
    _write(lineage, _lineage_payload())

    monitor = build_prospective_hype_blind_monitor(
        health,
        lineage,
        expected_state_artifact_id="101",
    )
    payload = monitor.to_dict()

    assert payload["campaign_health_status"] == "pre_validation"
    assert payload["lineage_status"] == "waiting_for_second_frozen_format_state"
    assert payload["expected_anchor_count"] == 1080
    assert payload["required_final_observation_count"] == 972
    assert payload["missed_anchor_budget"] == 108
    assert payload["required_settled_trades"] == 80
    assert payload["interim_economics_redacted"] is True
    assert payload["capture_coverage_to_date"] is None
    assert "mean_net_return" not in payload
    assert "total_net_return" not in payload
    assert "positive_net_count" not in payload
    assert len(payload["monitor_id"]) == 64


def test_tampered_health_receipt_fails_blind_monitor(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    lineage = tmp_path / "lineage.json"
    payload = _health_payload()
    payload["observation_count_to_date"] = 1
    _write(health, payload)
    _write(lineage, _lineage_payload())

    with pytest.raises(
        ProspectiveBlindMonitorError,
        match="HEALTH_ID_MISMATCH",
    ):
        build_prospective_hype_blind_monitor(
            health,
            lineage,
            expected_state_artifact_id="101",
        )


def test_structurally_invalid_health_fails_even_with_valid_identity(
    tmp_path: Path,
) -> None:
    health = tmp_path / "health.json"
    lineage = tmp_path / "lineage.json"
    payload = _health_payload()
    payload.pop("health_id")
    payload["observation_count_to_date"] = 1
    _write(health, _with_identity(payload, "health_id"))
    _write(lineage, _lineage_payload())

    with pytest.raises(
        ProspectiveBlindMonitorError,
        match="CAPTURE_COUNT_RECONCILIATION_FAILED",
    ):
        build_prospective_hype_blind_monitor(
            health,
            lineage,
            expected_state_artifact_id="101",
        )


def test_lineage_must_match_state_artifact_from_latest_health_run(
    tmp_path: Path,
) -> None:
    health = tmp_path / "health.json"
    lineage = tmp_path / "lineage.json"
    _write(health, _health_payload())
    _write(lineage, _lineage_payload(state_artifact_id="999"))

    with pytest.raises(
        ProspectiveBlindMonitorError,
        match="LINEAGE_STATE_ARTIFACT_MISMATCH",
    ):
        build_prospective_hype_blind_monitor(
            health,
            lineage,
            expected_state_artifact_id="101",
        )


def test_tampered_lineage_receipt_fails_blind_monitor(tmp_path: Path) -> None:
    health = tmp_path / "health.json"
    lineage = tmp_path / "lineage.json"
    payload = _lineage_payload()
    payload["current_state_digest"] = "e" * 64
    _write(health, _health_payload())
    _write(lineage, payload)

    with pytest.raises(
        ProspectiveBlindMonitorError,
        match="LINEAGE_RECEIPT_ID_MISMATCH",
    ):
        build_prospective_hype_blind_monitor(
            health,
            lineage,
            expected_state_artifact_id="101",
        )



def test_blind_monitor_receipt_round_trips_through_structural_verifier(
    tmp_path: Path,
) -> None:
    health = tmp_path / "health.json"
    lineage = tmp_path / "lineage.json"
    receipt = tmp_path / "monitor.json"
    _write(health, _health_payload())
    _write(lineage, _lineage_payload())

    monitor = build_prospective_hype_blind_monitor(
        health,
        lineage,
        expected_state_artifact_id="101",
    )
    _write(receipt, monitor.to_dict())

    verified = verify_prospective_hype_blind_monitor_receipt(receipt)

    assert verified == monitor
    assert verified.monitor_id == monitor.monitor_id


def test_self_hashed_structurally_false_blind_monitor_is_rejected(
    tmp_path: Path,
) -> None:
    health = tmp_path / "health.json"
    lineage = tmp_path / "lineage.json"
    receipt = tmp_path / "monitor.json"
    _write(health, _health_payload())
    _write(lineage, _lineage_payload())

    payload = build_prospective_hype_blind_monitor(
        health,
        lineage,
        expected_state_artifact_id="101",
    ).to_dict()
    payload.pop("monitor_id")
    payload["required_final_observation_count"] = 971
    payload["monitor_id"] = hashlib.sha256(
        _canonical(payload).encode("utf-8")
    ).hexdigest()
    _write(receipt, payload)

    with pytest.raises(
        ProspectiveBlindMonitorError,
        match="FINAL_OBSERVATION_FLOOR_MISMATCH",
    ):
        verify_prospective_hype_blind_monitor_receipt(receipt)
