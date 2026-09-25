from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/prospective-hype-v3-cutover-acceptance.yml"
)
PINNED_SOURCE = "298723c52d6a3b09839d05451d3d7db9753815bf"
AUDIT_BLOB = "db11fb4b99915625694a38f901e009afa16a0526"
OBSERVER_BLOB = "e00502dacb925d03bd90328f6ea39f6d195d0fa5"


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_v3_cutover_is_event_driven_and_read_only() -> None:
    source = _source()

    assert "Prospective HYPE V3 Independent Audit" in source
    assert "workflow_run:" in source
    assert "workflow_dispatch:" in source
    assert "\n  schedule:" not in source
    assert "cron:" not in source
    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert "cancel-in-progress: false" in source


def test_v3_cutover_uses_frozen_source_and_authenticated_workflow_bytes() -> None:
    source = _source()

    assert f"PINNED_SOURCE_REVISION: {PINNED_SOURCE}" in source
    assert f"ref: {PINNED_SOURCE}" in source
    assert f"AUDIT_WORKFLOW_BLOB_SHA: {AUDIT_BLOB}" in source
    assert f"OBSERVER_WORKFLOW_BLOB_SHA: {OBSERVER_BLOB}" in source
    assert "V3_CUTOVER_AUDIT_PROVENANCE_INVALID" in source
    assert "workflow_file.get(\"sha\") == os.environ[\"AUDIT_WORKFLOW_BLOB_SHA\"]" in source


def test_v3_cutover_reuses_exact_independent_audit_artifact() -> None:
    source = _source()

    assert "AUDIT_ARTIFACT_PREFIX: prospective-hype-v3-audit-" in source
    assert "/actions/runs/$UPSTREAM_RUN_ID/artifacts?per_page=100" in source
    assert "test -f \"$CUTOVER_ROOT/audit/audit.json\"" in source
    assert "test ! -f \"$CUTOVER_ROOT/audit/failure.json\"" in source
    assert "V3_CUTOVER_AUDIT_ID_MISMATCH" in source


def test_v3_cutover_requires_zero_prestart_evidence_and_exact_identities() -> None:
    source = _source()

    assert 'audit.get("observation_count") != 0' in source
    assert 'audit.get("outcome_count") != 0' in source
    assert 'audit.get("expected_anchor_count_to_date") != 0' in source
    assert 'audit.get("observation_count_to_date") != 0' in source
    assert 'audit.get("missed_anchor_count_to_date") != 0' in source
    assert 'audit.get("audit_status") != "pre_validation"' in source
    assert '"runtime_attestation_id": runtime.attestation_id' in source
    assert '"control_plane_id": control["control_plane_id"]' in source


def test_v3_cutover_waits_until_first_clean_capture_enters_queue() -> None:
    source = _source()

    assert "first_clean_capture_ms = (" in source
    assert "plan.first_expected_anchor_ms + 1 + 3 * MINUTE_MS" in source
    assert "acceptance_not_before_ms = first_clean_capture_ms - 4 * HOUR_MS" in source
    assert '"cutover_status": "waiting_for_queue_horizon"' in source
    assert "V3_CUTOVER_AUDIT_NOT_REFRESHED_IN_ACCEPTANCE_WINDOW" in source
    assert "V3_CUTOVER_FIRST_CLEAN_CAPTURE_NOT_QUEUED" in source
    assert "V3_CUTOVER_PRESTART_ACCEPTANCE_WINDOW_CLOSED" in source


def test_v3_cutover_canonical_receipt_is_prestart_redacted_and_non_promotional() -> None:
    source = _source()

    assert '"kind": "prospective-hype-v3-cutover-acceptance"' in source
    assert '"cutover_status": "ready_for_cutover"' in source
    assert '"first_clean_capture_queued": True' in source
    assert '"pre_cutover_observation_count": 0' in source
    assert '"pre_cutover_outcome_count": 0' in source
    assert '"interim_economics_redacted": True' in source
    assert '"promotion_eligible": False' in source
    assert "name: prospective-hype-v3-cutover-acceptance" in source
    assert "retention-days: 90" in source


def test_v3_cutover_reuses_one_canonical_receipt_and_rejects_duplicates() -> None:
    source = _source()

    assert "CANONICAL_CUTOVER_RECEIPT_DUPLICATED" in source
    assert "Verify existing canonical cutover receipt" in source
    assert "V3_CANONICAL_CUTOVER_RECEIPT_INVALID" in source
    assert 'receipt.get("receipt_id") != expected_id' in source
    assert "steps.discover.outputs.status == 'existing'" in source


def test_v3_cutover_preserves_redacted_failure_before_failing() -> None:
    source = _source()

    assert "prospective-hype-v3-cutover-failure-" in source
    assert '"interim_economics_redacted": True' in source
    assert '"promotion_eligible": False' in source
    assert "Upload V3 cutover failure receipt" in source
    assert "Preserve V3 cutover failure status" in source
    assert "continue-on-error: true" in source


def test_v3_cutover_ignores_skipped_or_failed_upstream_audits() -> None:
    source = _source()

    assert "github.event.workflow_run.conclusion == 'success'" in source
    assert "github.event.workflow_run.head_branch == 'main'" in source
    assert "github.event.workflow_run.event != 'pull_request'" in source
