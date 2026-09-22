from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/prospective-hype-state-readiness.yml")


def test_state_readiness_audit_is_read_only_and_never_invokes_observer() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in source
    assert "actions: read" in source
    assert "actions: write" not in source
    assert "contents: write" not in source
    assert "cocomelon-prospective-hype-observer" not in source
    assert "COCOMELON_EXECUTION_MODE" not in source


def test_state_readiness_audit_preserves_redacted_failure_receipt_before_failing() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cocomelon-prospective-hype-state-readiness-failure" in source
    assert "STATE_ARTIFACT_DISCOVERY_FAILED" in source
    assert "STATE_ARTIFACT_DOWNLOAD_FAILED" in source
    assert "STATE_READINESS_VERIFY_FAILED" in source
    assert "STATE_READINESS_RECEIPT_UPLOAD_FAILED" in source
    assert "continue-on-error: true" in source
    assert "Upload state-readiness failure receipt" in source
    assert "Preserve state-readiness failure status" in source
    assert "if-no-files-found: error" in source


def test_state_readiness_failure_artifact_cannot_match_success_prefix() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "name: prospective-hype-state-readiness-${{ github.run_id }}-" in source
    assert (
        "name: prospective-hype-failed-state-readiness-audit-"
        "${{ github.run_id }}-"
    ) in source
    assert (
        "name: prospective-hype-state-readiness-failure-"
        "${{ github.run_id }}-"
    ) not in source


def test_state_readiness_audit_uses_one_clock_for_success_and_failure() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert source.count("time.time_ns() // 1_000_000") == 1
    assert "id: clock" in source
    assert "steps.clock.outputs.audited_at_ms" in source
    assert '--as-of-ms "$AUDIT_MS"' in source
    assert '--audited-at-ms "$AUDIT_MS"' in source


def test_state_readiness_failure_paths_remain_economics_redacted() -> None:
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
