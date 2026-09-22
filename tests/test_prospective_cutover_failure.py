from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.prospective_cutover_failure import (
    ProspectiveCutoverFailureError,
    build_prospective_cutover_failure,
    verify_prospective_cutover_failure,
)


def test_cutover_failure_receipt_is_redacted_deterministic_and_self_hashed(
    tmp_path: Path,
) -> None:
    first = build_prospective_cutover_failure(
        audited_at_ms=1_790_068_000_000,
        stage="monitor",
        reason_code="CUTOVER_MONITOR_RECEIPT_MISSING",
        monitor_artifact_id="101",
        state_artifact_id="202",
    )
    second = build_prospective_cutover_failure(
        audited_at_ms=1_790_068_000_000,
        stage="monitor",
        reason_code="CUTOVER_MONITOR_RECEIPT_MISSING",
        monitor_artifact_id="101",
        state_artifact_id="202",
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
        "pnl",
    ):
        assert forbidden not in payload

    path = tmp_path / "cutover-failure.json"
    first.write(path)
    assert verify_prospective_cutover_failure(path) == first


def test_cutover_failure_receipt_allows_missing_source_ids() -> None:
    receipt = build_prospective_cutover_failure(
        audited_at_ms=100,
        stage="discovery",
        reason_code="CUTOVER_ARTIFACT_DISCOVERY_FAILED",
    )

    assert receipt.monitor_artifact_id is None
    assert receipt.state_artifact_id is None
    assert receipt.receipt_artifact_id is None


@pytest.mark.parametrize(
    ("stage", "reason_code"),
    (
        ("", "CUTOVER_BUILD_FAILED"),
        ("unknown", "CUTOVER_BUILD_FAILED"),
        ("build", "cutover failed"),
        ("build", ""),
        ("build", "A" * 97),
    ),
)
def test_cutover_failure_receipt_rejects_unbounded_failure_metadata(
    stage: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError):
        build_prospective_cutover_failure(
            audited_at_ms=100,
            stage=stage,
            reason_code=reason_code,
        )


def test_cutover_failure_receipt_rejects_non_numeric_artifact_ids() -> None:
    with pytest.raises(ValueError, match="monitor_artifact_id"):
        build_prospective_cutover_failure(
            audited_at_ms=100,
            stage="monitor",
            reason_code="CUTOVER_MONITOR_RECEIPT_MISSING",
            monitor_artifact_id="abc",
        )


def test_cutover_failure_receipt_tampering_fails_identity_check(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_cutover_failure(
        audited_at_ms=100,
        stage="build",
        reason_code="CUTOVER_BUILD_FAILED",
        monitor_artifact_id="101",
    )
    path = tmp_path / "cutover-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace("CUTOVER_BUILD_FAILED", "CUTOVER_STATE_DOWNLOAD_FAILED"),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveCutoverFailureError,
        match="CUTOVER_FAILURE_ID_MISMATCH",
    ):
        verify_prospective_cutover_failure(path)


def test_cutover_failure_receipt_rejects_cross_campaign_tampering(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_cutover_failure(
        audited_at_ms=100,
        stage="build",
        reason_code="CUTOVER_BUILD_FAILED",
    )
    path = tmp_path / "cutover-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(receipt.campaign_id, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveCutoverFailureError,
        match="CUTOVER_FAILURE_RECEIPT_INVALID",
    ):
        verify_prospective_cutover_failure(path)
