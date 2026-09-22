from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.prospective_state_readiness_failure import (
    ProspectiveStateReadinessFailureError,
    build_prospective_state_readiness_failure,
    verify_prospective_state_readiness_failure,
)


def test_state_readiness_failure_receipt_is_redacted_deterministic_and_self_hashed(
    tmp_path: Path,
) -> None:
    first = build_prospective_state_readiness_failure(
        audited_at_ms=1_790_068_300_000,
        stage="verify",
        reason_code="STATE_READINESS_VERIFY_FAILED",
        state_artifact_id="123",
    )
    second = build_prospective_state_readiness_failure(
        audited_at_ms=1_790_068_300_000,
        stage="verify",
        reason_code="STATE_READINESS_VERIFY_FAILED",
        state_artifact_id="123",
    )

    assert first == second
    assert first.interim_economics_redacted is True
    assert first.state_artifact_id == "123"
    assert len(first.campaign_id) == 64
    assert len(first.candidate_spec_id) == 64
    assert len(first.validation_plan_id) == 64
    assert len(first.observer_source_revision) == 40
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

    path = tmp_path / "state-readiness-failure.json"
    first.write(path)
    assert verify_prospective_state_readiness_failure(path) == first


def test_state_readiness_failure_receipt_allows_missing_artifact_before_discovery() -> None:
    receipt = build_prospective_state_readiness_failure(
        audited_at_ms=100,
        stage="discovery",
        reason_code="STATE_ARTIFACT_DISCOVERY_FAILED",
    )

    assert receipt.state_artifact_id is None


@pytest.mark.parametrize(
    ("stage", "reason_code"),
    (
        ("", "STATE_READINESS_VERIFY_FAILED"),
        ("unknown", "STATE_READINESS_VERIFY_FAILED"),
        ("verify", "state readiness failed"),
        ("verify", ""),
        ("verify", "A" * 97),
    ),
)
def test_state_readiness_failure_receipt_rejects_unbounded_metadata(
    stage: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError):
        build_prospective_state_readiness_failure(
            audited_at_ms=100,
            stage=stage,
            reason_code=reason_code,
        )


def test_state_readiness_failure_receipt_rejects_non_numeric_artifact_id() -> None:
    with pytest.raises(ValueError, match="state_artifact_id"):
        build_prospective_state_readiness_failure(
            audited_at_ms=100,
            stage="verify",
            reason_code="STATE_READINESS_VERIFY_FAILED",
            state_artifact_id="bad",
        )


def test_state_readiness_failure_receipt_tampering_fails_identity_check(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_state_readiness_failure(
        audited_at_ms=100,
        stage="verify",
        reason_code="STATE_READINESS_VERIFY_FAILED",
        state_artifact_id="123",
    )
    path = tmp_path / "state-readiness-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(
            "STATE_READINESS_VERIFY_FAILED",
            "STATE_READINESS_UPLOAD_FAILED",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveStateReadinessFailureError,
        match="STATE_READINESS_FAILURE_ID_MISMATCH",
    ):
        verify_prospective_state_readiness_failure(path)


def test_state_readiness_failure_receipt_rejects_cross_campaign_tampering(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_state_readiness_failure(
        audited_at_ms=100,
        stage="download",
        reason_code="STATE_ARTIFACT_DOWNLOAD_FAILED",
    )
    path = tmp_path / "state-readiness-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(receipt.campaign_id, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveStateReadinessFailureError,
        match="STATE_READINESS_FAILURE_RECEIPT_INVALID",
    ):
        verify_prospective_state_readiness_failure(path)
