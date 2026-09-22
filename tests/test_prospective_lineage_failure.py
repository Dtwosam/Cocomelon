from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.prospective_lineage_failure import (
    ProspectiveLineageFailureError,
    build_prospective_lineage_failure,
    verify_prospective_lineage_failure,
)


def test_lineage_failure_receipt_is_redacted_deterministic_and_self_hashed(
    tmp_path: Path,
) -> None:
    first = build_prospective_lineage_failure(
        audited_at_ms=1_790_068_100_000,
        stage="verify",
        reason_code="LINEAGE_APPEND_ONLY_VERIFY_FAILED",
        previous_artifact_id="101",
        current_artifact_id="202",
    )
    second = build_prospective_lineage_failure(
        audited_at_ms=1_790_068_100_000,
        stage="verify",
        reason_code="LINEAGE_APPEND_ONLY_VERIFY_FAILED",
        previous_artifact_id="101",
        current_artifact_id="202",
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

    path = tmp_path / "lineage-failure.json"
    first.write(path)
    assert verify_prospective_lineage_failure(path) == first


def test_lineage_failure_receipt_allows_missing_ids_before_discovery() -> None:
    receipt = build_prospective_lineage_failure(
        audited_at_ms=100,
        stage="discovery",
        reason_code="LINEAGE_ARTIFACT_DISCOVERY_FAILED",
    )

    assert receipt.previous_artifact_id is None
    assert receipt.current_artifact_id is None


@pytest.mark.parametrize(
    ("stage", "reason_code"),
    (
        ("", "LINEAGE_APPEND_ONLY_VERIFY_FAILED"),
        ("unknown", "LINEAGE_APPEND_ONLY_VERIFY_FAILED"),
        ("verify", "lineage failed"),
        ("verify", ""),
        ("verify", "A" * 97),
    ),
)
def test_lineage_failure_receipt_rejects_unbounded_metadata(
    stage: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError):
        build_prospective_lineage_failure(
            audited_at_ms=100,
            stage=stage,
            reason_code=reason_code,
        )


def test_lineage_failure_receipt_rejects_non_numeric_artifact_ids() -> None:
    with pytest.raises(ValueError, match="current_artifact_id"):
        build_prospective_lineage_failure(
            audited_at_ms=100,
            stage="verify",
            reason_code="LINEAGE_APPEND_ONLY_VERIFY_FAILED",
            current_artifact_id="bad",
        )


def test_lineage_failure_receipt_tampering_fails_identity_check(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_lineage_failure(
        audited_at_ms=100,
        stage="verify",
        reason_code="LINEAGE_APPEND_ONLY_VERIFY_FAILED",
        previous_artifact_id="101",
        current_artifact_id="202",
    )
    path = tmp_path / "lineage-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(
            "LINEAGE_APPEND_ONLY_VERIFY_FAILED",
            "LINEAGE_STATE_READINESS_FAILED",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveLineageFailureError,
        match="LINEAGE_FAILURE_ID_MISMATCH",
    ):
        verify_prospective_lineage_failure(path)


def test_lineage_failure_receipt_rejects_cross_campaign_tampering(
    tmp_path: Path,
) -> None:
    receipt = build_prospective_lineage_failure(
        audited_at_ms=100,
        stage="state",
        reason_code="LINEAGE_STATE_READINESS_FAILED",
    )
    path = tmp_path / "lineage-failure.json"
    receipt.write(path)
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(receipt.campaign_id, "0" * 64),
        encoding="utf-8",
    )

    with pytest.raises(
        ProspectiveLineageFailureError,
        match="LINEAGE_FAILURE_RECEIPT_INVALID",
    ):
        verify_prospective_lineage_failure(path)
