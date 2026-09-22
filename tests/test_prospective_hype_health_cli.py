from __future__ import annotations

from cocomelon.prospective_hype_health_cli import prospective_hype_health_payload
from cocomelon.research.prospective_campaign_health import (
    ProspectiveCampaignHealthStatus,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)


def test_empty_campaign_health_is_prevalidation_and_recoverable(tmp_path) -> None:
    plan = HYPE_PROSPECTIVE_VALIDATION_V1

    payload = prospective_hype_health_payload(
        root=tmp_path,
        as_of_ms=plan.validation_start_ms,
    )

    assert payload["command"] == "prospective-hype-health"
    assert payload["status"] == ProspectiveCampaignHealthStatus.PRE_VALIDATION.value
    assert payload["expected_anchor_count"] == 1080
    assert payload["required_final_observation_count"] == 972
    assert payload["missed_anchor_budget"] == 108
    assert payload["remaining_missed_anchor_budget"] == 108
    assert payload["maximum_final_capture_coverage"] == "1"
    assert payload["irrecoverable_reasons"] == ()
    assert payload["evidence_class"] == "prospective_clean"
    assert payload["promotion_eligible"] is False
    assert len(payload["validation_report_id"]) == 64
    assert len(payload["health_id"]) == 64
    assert len(payload["state_digest"]) == 64
