from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.prospective_readiness_failure import (
    ProspectiveReadinessFailureError,
    build_prospective_readiness_failure,
    verify_prospective_readiness_failure,
)


def test_readiness_failure_receipt_is_redacted_deterministic_and_self_hashed(
    tmp_path: Path,
) -> None:
    workflow_sha = "a" * 64
    first = build_prospective_readiness_failure(
        audited_at_ms=1_790_068_200_000,
        stage="build",
        reason_code="READINESS_CONTRACT_VERIFY_FAILED",
        observer_workflow_sha256=workflow_sha,
    )
    second = build_prospective_readiness_failure(
        audited_at_ms=1_790_068_200_000,
        stage="build",
        reason_code="READINESS_CONTRACT_VERIFY_FAILED",
        observer_workflow_sha256=workflow_sha,
    )

    assert first == second
    assert first.interim_economics_redacted is True
    assert first.observer_workflow_sha256 == workflow_sha
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

    path = tmp_path / "readiness-failure.json"
    first.write(path)
    assert verify_prospective_readiness_failure(path) == first


def test_readiness_failure_receipt_allows_missing_workflow_sha() -> None:
    receipt = build_prospective_readiness_failure(
        audited_at_ms=100,
        stage="build",
        reason_code="READINESS_WORKFLOW_MISSING",
    )

    assert receipt.observer_workflow_sha256 is None


@pytest.mark.parametrize(
    ("stage", "reason_code"),
    (
        ("", "READINESS_CONTRACT_VERIFY_FAILED"),
        ("unknown", "READINESS_CONTRACT_VERIFY_FAILED"),
        ("build", "readiness failed"),
        ("build", ""),
        ("build", "A" * 97),
    ),
)
def test_readiness_failure_receipt_rejects_unbounded_metadata(
    stage: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError):
        build_prospective_readiness_failure(
            audited_at_ms=100,
            stage=stage,
            reason_code=reason_code,
        )


def test_readiness_failure_receipt_rejects_invalid_workflow_sha() -> None:
    with pytest.raises(ValueError, match="observer_workflow_sha256"):
        build_prospective_readiness_failure(
            audited_at_ms=100,
            stage="build",
            reason_code="READINESS_CONTRACT_VERIFY_FAILED",
            observer_workflow_sha256="bad",
        )


def test_readiness_failure_receipt_tampering_fails_identity_check(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_readiness_failure(
        audited_at_ms=100,
        stage="build",
        reason_code="READINESS_CONTRACT_VERIFY_FAILED",
        observer_workflow_sha256="b" * 64,
    )
    path = tmp_path / "readiness-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(
            "READINESS_CONTRACT_VERIFY_FAILED",
            "READINESS_RECEIPT_UPLOAD_FAILED",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveReadinessFailureError,
        match="READINESS_FAILURE_ID_MISMATCH",
    ):
        verify_prospective_readiness_failure(path)


def test_readiness_failure_receipt_rejects_cross_candidate_tampering(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_readiness_failure(
        audited_at_ms=100,
        stage="build",
        reason_code="READINESS_CONTRACT_VERIFY_FAILED",
    )
    path = tmp_path / "readiness-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(receipt.candidate_spec_id, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveReadinessFailureError,
        match="READINESS_FAILURE_RECEIPT_INVALID",
    ):
        verify_prospective_readiness_failure(path)
