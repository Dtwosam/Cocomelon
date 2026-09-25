from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-v3-control-heartbeat.yml")


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_heartbeat_has_no_schedule_dependency() -> None:
    source = _source()
    header = source.split("permissions:", 1)[0]

    assert "workflow_dispatch:" in header
    assert "\n  schedule:" not in header
    assert "\n    - cron:" not in header
    assert "Prospective HYPE V3 heartbeat" in source


def test_heartbeat_precreates_four_future_targets_without_global_concurrency() -> None:
    source = _source()

    header = source.split("jobs:", 1)[0]
    assert "\nconcurrency:" not in header
    assert "group: prospective-hype-v3-control-heartbeat" not in source
    assert 'QUEUE_DEPTH: "4"' in source
    assert 'HEARTBEAT_MINUTE_UTC: "10"' in source
    assert "V3_HEARTBEAT_TARGET_PHASE_INVALID" in source
    assert "V3_HEARTBEAT_LEADER_NOT_FOUND" in source
    assert 'gh workflow run "$HEARTBEAT_WORKFLOW_FILE"' in source


def test_heartbeat_retries_only_transient_dispatch_failures() -> None:
    source = _source()

    assert "attempt=1" in source
    assert '"$attempt" -ge 5' in source
    assert "HTTP (500|502|503|504)" in source


def test_heartbeat_explicitly_runs_audit_then_cutover() -> None:
    source = _source()

    audit = source.index("Dispatch independent V3 audit")
    cutover = source.index("Dispatch V3 cutover acceptance")
    receipt = source.index("Build non-economic heartbeat receipt")

    assert audit < cutover < receipt
    assert 'gh workflow run "$AUDIT_WORKFLOW_FILE"' in source
    assert 'gh workflow run "$CUTOVER_WORKFLOW_FILE"' in source
    assert "V3_HEARTBEAT_AUDIT_NOT_SUCCESSFUL" in source
    assert "V3_HEARTBEAT_CUTOVER_NOT_SUCCESSFUL" in source
    assert "V3_HEARTBEAT_AUDIT_TIMEOUT" in source
    assert "V3_HEARTBEAT_CUTOVER_TIMEOUT" in source


def test_heartbeat_never_touches_economic_state() -> None:
    source = _source().lower()

    assert '"economic_evidence": false' in source
    assert '"promotion_eligible": false' in source
    assert "cocomelon-prospective-hype-observer" not in source
    assert "prospective-hype-v3-clean-state" not in source
    assert "api.hyperliquid.xyz" not in source


def test_heartbeat_has_minimal_permissions_and_bounded_runtime() -> None:
    source = _source()

    assert "contents: read" in source
    assert "actions: write" in source
    assert "timeout-minutes: 270" in source
    assert "persist-credentials: false" in source
