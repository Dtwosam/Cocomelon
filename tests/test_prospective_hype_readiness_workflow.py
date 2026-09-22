from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-readiness.yml")


def test_readiness_audit_watches_frozen_observer_workflow_changes() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count('".github/workflows/prospective-hype-clean.yml"') >= 2
    assert 'cron: "15 */6 * * *"' in source


def test_readiness_audit_is_serialized_and_read_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in source
    assert "contents: write" not in source
    assert "group: prospective-hype-readiness-audit" in source
    assert "cancel-in-progress: false" in source


def test_readiness_audit_verifies_current_frozen_observer_contract() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-readiness" in source
    assert "--workflow .github/workflows/prospective-hype-clean.yml" in source
    assert 'payload["readiness_status"] in {' in source
    assert '"post_cutover_contract_valid"' in source
    assert 'payload["expected_anchor_count"] == 1080' in source
    assert 'len(payload["observer_workflow_sha256"]) == 64' in source
    assert 'len(payload["readiness_id"]) == 64' in source


def test_readiness_audit_never_invokes_or_mutates_observer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-observer" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source
    assert "actions: write" not in source
    assert "contents: write" not in source


def test_readiness_audit_preserves_receipts_for_campaign_audit() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "actions/upload-artifact@v7" in source
    assert "prospective-hype-readiness-${{ github.run_id }}-" in source
    assert "retention-days: 90" in source
    assert "if-no-files-found: error" in source


def test_readiness_audit_preserves_redacted_failure_receipt_before_failing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-readiness-failure" in source
    assert "READINESS_CONTRACT_VERIFY_FAILED" in source
    assert "READINESS_RECEIPT_UPLOAD_FAILED" in source
    assert "failure.json" in source
    assert "continue-on-error: true" in source
    assert "Upload readiness failure receipt" in source
    assert "Preserve readiness failure status" in source
    assert "if-no-files-found: error" in source


def test_readiness_failure_artifact_cannot_match_success_prefix() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: prospective-hype-readiness-${{ github.run_id }}-" in source
    assert "name: prospective-hype-failed-readiness-audit-${{ github.run_id }}-" in source
    assert "name: prospective-hype-readiness-failure-${{ github.run_id }}-" not in source


def test_readiness_audit_uses_one_clock_and_binds_workflow_sha() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count("time.time_ns() // 1_000_000") == 1
    assert "id: audit_identity" in source
    assert "hashlib.sha256(workflow.read_bytes()).hexdigest()" in source
    assert "steps.audit_identity.outputs.audited_at_ms" in source
    assert "steps.audit_identity.outputs.observer_workflow_sha256" in source
    assert '--as-of-ms "$AUDIT_MS"' in source
    assert '--observer-workflow-sha256 "$WORKFLOW_SHA"' in source


def test_readiness_failure_paths_remain_economics_redacted() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for token in (
        '"mean_net_return":',
        '"total_net_return":',
        '"positive_net_count":',
        '"non_positive_net_count":',
        '"gross_return":',
        '"net_return":',
        '"pnl":',
    ):
        assert token not in source
