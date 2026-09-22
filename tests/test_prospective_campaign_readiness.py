from __future__ import annotations

from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_campaign_readiness import (
    FROZEN_OBSERVER_SOURCE_REVISION,
    ProspectiveCampaignReadinessError,
    verify_prospective_hype_campaign_readiness,
    verify_prospective_hype_campaign_readiness_file,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "prospective-hype-clean.yml"
PLAN = HYPE_PROSPECTIVE_VALIDATION_V1
SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_current_frozen_workflow_is_ready_before_cutover() -> None:
    receipt = verify_prospective_hype_campaign_readiness_file(
        WORKFLOW,
        audited_at_ms=PLAN.validation_start_ms - 1,
    )

    assert receipt.readiness_status == "ready_pre_cutover"
    assert receipt.candidate_spec_id == SPEC.spec_id
    assert receipt.validation_plan_id == PLAN.plan_id
    assert receipt.observer_source_revision == FROZEN_OBSERVER_SOURCE_REVISION
    assert receipt.validation_start_ms == PLAN.validation_start_ms
    assert receipt.first_expected_anchor_ms == PLAN.first_expected_anchor_ms
    assert receipt.validation_end_ms == PLAN.validation_end_ms
    assert receipt.finalization_not_before_ms == PLAN.finalization_not_before_ms
    assert receipt.expected_anchor_count == 1080
    assert len(receipt.observer_workflow_sha256) == 64
    assert len(receipt.readiness_id) == 64


def test_same_contract_remains_auditable_after_cutover() -> None:
    receipt = verify_prospective_hype_campaign_readiness(
        _workflow(),
        audited_at_ms=PLAN.validation_start_ms,
    )

    assert receipt.readiness_status == "post_cutover_contract_valid"
    assert receipt.readiness_id


@pytest.mark.parametrize(
    ("old", "new", "code"),
    (
        (
            'cron: "3,8,13 * * * *"',
            'cron: "4,9,14 * * * *"',
            "FROZEN_CRON_MISSING",
        ),
        (
            "COCOMELON_EXECUTION_MODE: paper",
            "COCOMELON_EXECUTION_MODE: live",
            "PAPER_MODE_MISSING",
        ),
        (
            f"ref: {FROZEN_OBSERVER_SOURCE_REVISION}",
            "ref: main",
            "FROZEN_OBSERVER_CHECKOUT_REVISION_MISSING",
        ),
        (
            "STATE_ARTIFACT_NAME: prospective-hype-clean-state",
            "STATE_ARTIFACT_NAME: reset-state",
            "FROZEN_STATE_ARTIFACT_MISSING",
        ),
    ),
)
def test_material_control_plane_drift_fails_readiness(
    old: str,
    new: str,
    code: str,
) -> None:
    source = _workflow().replace(old, new, 1)

    with pytest.raises(ProspectiveCampaignReadinessError, match=code):
        verify_prospective_hype_campaign_readiness(
            source,
            audited_at_ms=PLAN.validation_start_ms - 1,
        )


def test_testnet_reference_is_forbidden() -> None:
    source = _workflow() + "\n# https://api.hyperliquid-testnet.xyz\n"

    with pytest.raises(
        ProspectiveCampaignReadinessError,
        match="TESTNET_REFERENCE_FORBIDDEN",
    ):
        verify_prospective_hype_campaign_readiness(
            source,
            audited_at_ms=PLAN.validation_start_ms - 1,
        )


def test_state_must_be_preserved_before_irrecoverable_gate() -> None:
    source = _workflow()
    upload = "Upload cumulative clean evidence state"
    gate = "Fail closed if frozen campaign is irrecoverable"
    source = source.replace(upload, "TEMP_UPLOAD_NAME", 1)
    source = source.replace(gate, upload, 1)
    source = source.replace("TEMP_UPLOAD_NAME", gate, 1)

    with pytest.raises(
        ProspectiveCampaignReadinessError,
        match="STATE_PRESERVATION_ORDER_INVALID",
    ):
        verify_prospective_hype_campaign_readiness(
            source,
            audited_at_ms=PLAN.validation_start_ms - 1,
        )


def test_missing_workflow_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(
        ProspectiveCampaignReadinessError,
        match="OBSERVER_WORKFLOW_MISSING",
    ):
        verify_prospective_hype_campaign_readiness_file(
            tmp_path / "missing.yml",
            audited_at_ms=PLAN.validation_start_ms - 1,
        )
