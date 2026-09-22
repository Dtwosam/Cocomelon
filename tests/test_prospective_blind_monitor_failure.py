from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.prospective_blind_monitor_failure import (
    ProspectiveBlindMonitorFailureError,
    build_prospective_blind_monitor_failure,
    verify_prospective_blind_monitor_failure,
)


def test_failure_receipt_is_redacted_deterministic_and_self_hashed(tmp_path: Path) -> None:
    first = build_prospective_blind_monitor_failure(
        audited_at_ms=1_790_067_900_000,
        stage="build",
        reason_code="HEALTH_ARTIFACT_STALE",
        health_artifact_id="101",
        lineage_artifact_id="202",
        state_artifact_id="303",
    )
    second = build_prospective_blind_monitor_failure(
        audited_at_ms=1_790_067_900_000,
        stage="build",
        reason_code="HEALTH_ARTIFACT_STALE",
        health_artifact_id="101",
        lineage_artifact_id="202",
        state_artifact_id="303",
    )

    assert first == second
    assert first.interim_economics_redacted is True
    assert len(first.campaign_id) == 64
    assert len(first.validation_plan_id) == 64
    assert len(first.failure_id) == 64
    payload = first.to_dict()
    for forbidden in (
        "mean_net_return",
        "total_net_return",
        "positive_net_count",
        "non_positive_net_count",
        "gross_return",
        "net_return",
    ):
        assert forbidden not in payload

    path = tmp_path / "failure.json"
    first.write(path)
    assert verify_prospective_blind_monitor_failure(path) == first


def test_failure_receipt_supports_missing_ids_before_discovery_finishes() -> None:
    receipt = build_prospective_blind_monitor_failure(
        audited_at_ms=100,
        stage="discovery",
        reason_code="HEALTH_ARTIFACT_MISSING",
    )

    assert receipt.health_artifact_id is None
    assert receipt.lineage_artifact_id is None
    assert receipt.state_artifact_id is None


@pytest.mark.parametrize(
    ("stage", "reason_code"),
    (
        ("", "HEALTH_ARTIFACT_STALE"),
        ("unknown", "HEALTH_ARTIFACT_STALE"),
        ("build", "health stale"),
        ("build", ""),
        ("build", "A" * 97),
    ),
)
def test_failure_receipt_rejects_unbounded_failure_metadata(
    stage: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError):
        build_prospective_blind_monitor_failure(
            audited_at_ms=100,
            stage=stage,
            reason_code=reason_code,
        )


def test_failure_receipt_tampering_fails_identity_check(tmp_path: Path) -> None:
    receipt = build_prospective_blind_monitor_failure(
        audited_at_ms=100,
        stage="build",
        reason_code="LINEAGE_ARTIFACT_STALE",
        state_artifact_id="303",
    )
    path = tmp_path / "failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace("LINEAGE_ARTIFACT_STALE", "HEALTH_ARTIFACT_STALE"),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveBlindMonitorFailureError,
        match="FAILURE_RECEIPT_ID_MISMATCH",
    ):
        verify_prospective_blind_monitor_failure(path)



def test_failure_receipt_rejects_cross_campaign_tampering(tmp_path: Path) -> None:
    receipt = build_prospective_blind_monitor_failure(
        audited_at_ms=100,
        stage="build",
        reason_code="HEALTH_ARTIFACT_STALE",
    )
    path = tmp_path / "failure.json"
    receipt.write(path)
    payload = path.read_text(encoding="utf-8")
    path.write_text(
        payload.replace(receipt.campaign_id, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveBlindMonitorFailureError,
        match="FAILURE_RECEIPT_INVALID",
    ):
        verify_prospective_blind_monitor_failure(path)
