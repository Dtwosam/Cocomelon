from __future__ import annotations

from cocomelon.prospective_hype_report_cli import prospective_hype_report_payload
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
    ProspectiveValidationStatus,
)


def test_empty_campaign_report_is_collecting_and_promotion_ineligible(tmp_path) -> None:
    plan = HYPE_PROSPECTIVE_VALIDATION_V1

    payload = prospective_hype_report_payload(
        root=tmp_path,
        as_of_ms=plan.validation_start_ms,
    )

    assert payload["command"] == "prospective-hype-report"
    assert payload["status"] == ProspectiveValidationStatus.COLLECTING.value
    assert payload["observation_count"] == 0
    assert payload["settled_trade_count"] == 0
    assert payload["capture_coverage"] == "0"
    assert payload["promotion_eligible"] is False
    assert payload["plan_id"] == plan.plan_id
    assert len(payload["report_id"]) == 64
    assert len(payload["state_digest"]) == 64
