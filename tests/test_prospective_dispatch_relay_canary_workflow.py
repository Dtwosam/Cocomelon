from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-dispatch-relay-canary.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_relay_canary_uses_push_bootstrap_and_workflow_dispatch_successors() -> None:
    source = _source()

    assert "workflow_dispatch:" in source
    assert "parent_run_id:" in source
    assert "hop:" in source
    assert "Dispatch successor relay hop" in source
    assert "gh workflow run prospective-dispatch-relay-canary.yml" in source
    assert '--ref main' in source


def test_relay_canary_has_exact_actions_write_scope_and_serial_concurrency() -> None:
    source = _source()

    assert "contents: read" in source
    assert "actions: write" in source
    assert "group: prospective-dispatch-relay-canary" in source
    assert "cancel-in-progress: false" in source
    assert "persist-credentials: false" in source


def test_relay_canary_is_bounded_and_fail_closed() -> None:
    source = _source()

    assert "hop < 0 or hop > 3" in source
    assert "RELAY_HOP_OUT_OF_RANGE" in source
    assert "DISPATCH_PARENT_RUN_ID_INVALID" in source
    assert "UNSUPPORTED_RELAY_EVENT" in source
    assert "env.INPUT_HOP != '3'" in source


def test_relay_canary_is_non_economic_and_state_isolated() -> None:
    source = _source().lower()

    assert '"economic_evidence": false' in source
    assert '"promotion_eligible": false' in source
    assert "hyperliquid" not in source
    assert "prospective-hype-v2-clean-state" not in source
    assert "prospective-hype-v3" not in source


def test_relay_canary_preserves_immutable_receipts() -> None:
    source = _source()

    assert "actions/upload-artifact@v7" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 14" in source
    assert "receipt_id" in source


def test_relay_canary_retries_transient_dispatch_failures_without_forking() -> None:
    source = _source()

    assert "Elect deterministic relay leader" in source
    assert "display_title == $title" in source
    assert "leader_id" in source
    assert "is_leader=false" in source
    assert "HTTP (500|502|503|504)" in source
    assert '"attempt" -ge 5' in source
    assert 'sleep "$((attempt * 2))"' in source
