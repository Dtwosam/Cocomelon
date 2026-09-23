from __future__ import annotations

import json
from pathlib import Path

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveCampaignManifest,
)

WORKFLOW = Path(".github/workflows/prospective-hype-v2-audit.yml")
PINNED_REVISION = "d15971eb22cec7b6fb2025bbb338c9d6d677eb63"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v2_audit_has_independent_run_and_heartbeat_triggers() -> None:
    source = _source()

    assert 'workflows:' in source
    assert '"Prospective HYPE V2 Clean Observer"' in source
    assert 'cron: "29 * * * *"' in source
    assert "workflow_dispatch:" in source
    assert "github.event_name != 'pull_request'" in source


def test_v2_audit_is_read_only_and_source_pinned() -> None:
    source = _source()

    assert "contents: read" in source
    assert "actions: read" in source
    assert f"ref: {PINNED_REVISION}" in source
    assert f"PINNED_SOURCE_REVISION: {PINNED_REVISION}" in source
    assert "persist-credentials: false" in source
    assert "testnet" not in source.lower()


def test_v2_audit_verifies_exact_campaign_and_control_plane_identity() -> None:
    source = _source()

    assert "HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2" in source
    assert "HYPE_PROSPECTIVE_VALIDATION_V2" in source
    assert '"kind": "prospective-hype-v2-clean-control-plane"' in source
    assert '"schedule_cron": "43,48,53 * * * *"' in source
    assert '"schedule_minutes_utc": [43, 48, 53]' in source
    assert '"protected_attempt_minute_utc": 3' in source
    assert '"capture_transport": "off_peak_redundant_prewarm_v2"' in source
    assert '"job_timeout_minutes": 30' in source
    assert "prospective-hype-v2-clean-state" in source
    assert "artifacts/prospective-hype-v2-clean" in source


def test_v2_audit_detects_missing_or_stale_capture_without_economic_reveal() -> None:
    source = _source()

    assert "UPSTREAM_OBSERVER_NOT_SUCCESSFUL" in source
    assert "STATE_ARTIFACT_MISSING" in source
    assert "STATE_ARTIFACT_STALE" in source
    assert "MAX_STATE_AGE_MS = 2 * 60 * 60 * 1_000" in source
    assert '"interim_economics_redacted": True' in source
    assert "remaining_missed_anchor_budget" in source


def test_v2_audit_preserves_failure_receipt_before_failing_red() -> None:
    source = _source()

    upload = source.index("Upload V2 independent audit receipt")
    preserve = source.index("Preserve V2 audit failure status")
    assert upload < preserve
    assert "prospective-hype-v2-independent-audit-failure" in source
    assert "if-no-files-found: error" in source
    assert 'if: ${{ always() }}' in source
    assert 'if [[ -f "$AUDIT_ROOT/audit.json" ]]; then' in source
    assert 'rm -f "$AUDIT_ROOT/audit.json"' in source
    assert 'rm -f "$AUDIT_ROOT/failure.json"' in source


def test_v2_manifest_comparison_uses_json_normalized_shape() -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V2
    manifest = ProspectiveCampaignManifest(
        candidate_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        validation_not_before_ms=spec.validation_not_before_ms,
    )
    expected = json.loads(
        json.dumps(
            {
                **manifest.identity_payload(),
                "campaign_id": manifest.campaign_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

    assert expected["basket_markets"] == ["BTC", "ETH", "HYPE", "SOL"]
    assert isinstance(expected["basket_markets"], list)
    assert 'expected_manifest_payload = json.loads(' in _source()


def test_v2_audit_compares_latest_state_with_authenticated_predecessor() -> None:
    source = _source()

    assert "previous_state_id" in source
    assert "previous_producer_run_id" in source
    assert "PREVIOUS_STATE_ARTIFACT_METADATA_FAILED" in source
    assert "PREVIOUS_PRODUCER_RUN_METADATA_FAILED" in source
    assert "PREVIOUS_STATE_DOWNLOAD_FAILED" in source
    assert "PREVIOUS_STATE_UNPACK_FAILED" in source
    assert 'Path(os.environ["AUDIT_ROOT"]) / "previous-state"' in source


def test_v2_audit_enforces_append_only_evidence_lineage() -> None:
    source = _source()

    assert "CAMPAIGN_MANIFEST_DRIFT" in source
    assert "RUNTIME_ATTESTATION_DRIFT" in source
    assert "CONTROL_PLANE_DRIFT" in source
    assert "PREVIOUS_OBSERVATION_REWRITTEN_OR_REMOVED" in source
    assert "PREVIOUS_OUTCOME_REWRITTEN_OR_REMOVED" in source
    assert "HISTORICAL_OBSERVATION_BACKFILL_FORBIDDEN" in source
    assert '"lineage_status": lineage_status' in source
    assert '"appended_observation_count": appended_observation_count' in source
    assert '"appended_outcome_count": appended_outcome_count' in source
