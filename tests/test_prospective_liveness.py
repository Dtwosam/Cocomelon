from __future__ import annotations

import pytest

from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)
from cocomelon.research.prospective_liveness import (
    MAX_OBSERVER_ARTIFACT_AGE_MS,
    ProspectiveLivenessError,
    ProspectiveLivenessStatus,
    evaluate_prospective_observer_liveness,
)

PLAN = HYPE_PROSPECTIVE_VALIDATION_V1
MINUTE_MS = 60_000


def test_recent_artifact_is_healthy_before_cutover() -> None:
    receipt = evaluate_prospective_observer_liveness(
        artifact_id="123",
        artifact_created_at_ms=PLAN.validation_start_ms - 20 * MINUTE_MS,
        audited_at_ms=PLAN.validation_start_ms - 1,
    )

    assert receipt.status is ProspectiveLivenessStatus.HEALTHY_PRE_CUTOVER
    assert receipt.alert_required is False
    assert receipt.artifact_age_ms < MAX_OBSERVER_ARTIFACT_AGE_MS
    assert len(receipt.liveness_id) == 64


def test_recent_artifact_is_healthy_during_active_campaign() -> None:
    now = PLAN.first_expected_anchor_ms + 35 * MINUTE_MS
    receipt = evaluate_prospective_observer_liveness(
        artifact_id="123",
        artifact_created_at_ms=now - 25 * MINUTE_MS,
        audited_at_ms=now,
    )

    assert receipt.status is ProspectiveLivenessStatus.HEALTHY_ACTIVE
    assert receipt.alert_required is False


def test_stale_artifact_alerts_during_active_campaign() -> None:
    now = PLAN.first_expected_anchor_ms + 2 * MAX_OBSERVER_ARTIFACT_AGE_MS
    receipt = evaluate_prospective_observer_liveness(
        artifact_id="123",
        artifact_created_at_ms=now - MAX_OBSERVER_ARTIFACT_AGE_MS - 1,
        audited_at_ms=now,
    )

    assert receipt.status is ProspectiveLivenessStatus.STALE_ACTIVE
    assert receipt.alert_required is True


def test_stale_artifact_alerts_before_cutover() -> None:
    receipt = evaluate_prospective_observer_liveness(
        artifact_id="123",
        artifact_created_at_ms=PLAN.validation_start_ms - 2 * MAX_OBSERVER_ARTIFACT_AGE_MS,
        audited_at_ms=PLAN.validation_start_ms - 1,
    )

    assert receipt.status is ProspectiveLivenessStatus.STALE_PRE_CUTOVER
    assert receipt.alert_required is True


def test_future_artifact_fails_closed() -> None:
    with pytest.raises(
        ProspectiveLivenessError,
        match="OBSERVER_ARTIFACT_FROM_FUTURE",
    ):
        evaluate_prospective_observer_liveness(
            artifact_id="123",
            artifact_created_at_ms=PLAN.validation_start_ms + 1,
            audited_at_ms=PLAN.validation_start_ms,
        )


def test_liveness_watchdog_stops_alerting_after_campaign_grace() -> None:
    now = PLAN.finalization_not_before_ms + MAX_OBSERVER_ARTIFACT_AGE_MS + 1
    receipt = evaluate_prospective_observer_liveness(
        artifact_id="123",
        artifact_created_at_ms=PLAN.validation_start_ms,
        audited_at_ms=now,
    )

    assert receipt.status is ProspectiveLivenessStatus.POST_CAMPAIGN
    assert receipt.alert_required is False
