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
