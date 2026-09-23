from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-capture-transport-canary.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_transport_canary_uses_established_catchup_completion_event() -> None:
    source = _source()

    assert "workflow_run:" in source
    assert '"Research Dashboard Catch-up Dispatcher"' in source
    assert "types:" in source
    assert "- completed" in source
    assert "UPSTREAM_EVENT_NOT_SCHEDULED" in source
    assert "UPSTREAM_RUN_NOT_SUCCESSFUL" in source


def test_transport_canary_has_no_economic_or_write_capability() -> None:
    source = _source()

    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert "economic_evidence" in source
    assert '"promotion_eligible": False' in source
    assert "hyperliquid" not in source.lower()
    assert "prospective-hype-v2-clean-state" not in source


def test_transport_canary_records_trigger_latency_and_provenance() -> None:
    source = _source()

    assert "UPSTREAM_REPOSITORY_MISMATCH" in source
    assert "UPSTREAM_BRANCH_MISMATCH" in source
    assert "workflow_run_trigger_latency_ms" in source
    assert "upstream_runtime_ms" in source
    assert "upstream_run_id" in source
    assert "receipt_id" in source


def test_transport_canary_preserves_immutable_receipt() -> None:
    source = _source()

    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 14" in source
