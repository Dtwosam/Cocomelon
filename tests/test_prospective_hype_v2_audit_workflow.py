from __future__ import annotations

from pathlib import Path

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
