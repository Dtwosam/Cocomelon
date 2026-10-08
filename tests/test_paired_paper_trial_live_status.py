from __future__ import annotations

from pathlib import Path

from scripts.render_continuous_paper_live_status import (
    _paired_paper_trial_lines,
)


def test_paired_trial_heartbeat_shows_independent_runtime_health() -> None:
    lines = "\n".join(
        _paired_paper_trial_lines(
            {
                "enabled": True,
                "initialized": True,
                "failed": False,
                "error": None,
                "portfolio_shadow_candidate_id": "frozen-d087",
                "submitted_records": 120,
                "processed_records": 117,
                "queue_depth": 3,
                "queue_capacity": 16_384,
                "queue_overflows": 0,
                "checkpoint_count": 2,
            }
        )
    )
    assert "- state: `active`" in lines
    assert "frozen-d087" in lines
    assert "120 / 117 / 3" in lines
    assert "3 / 16384 / 0" in lines
    assert "verify durable ledger after checkpoint" in lines
    assert "profitable" not in lines.lower()
    assert "RESEARCH ONLY / NO EXECUTION" in lines


def test_paired_trial_fail_closed_errors_are_visible() -> None:
    for payload in (
        {"enabled": False, "error": "freeze tampered"},
        {
            "enabled": True,
            "initialized": True,
            "failed": True,
            "error": "queue overflow",
            "portfolio_shadow_candidate_id": "frozen-d087",
            "submitted_records": 7,
            "processed_records": 9,
            "queue_depth": -1,
            "queue_overflows": 1,
        },
        {
            "enabled": True,
            "initialized": True,
            "restore_error": "restored identity mismatch",
        },
    ):
        rendered = "\n".join(_paired_paper_trial_lines(payload))
        assert "- state: `failed`" in rendered
        assert "RESEARCH ONLY / NO EXECUTION" in rendered
    assert "queue overflow" in "\n".join(
        _paired_paper_trial_lines(
            {"enabled": False, "failed": True, "error": "queue overflow"}
        )
    )


def test_paired_trial_does_not_claim_missing_heartbeat_is_healthy() -> None:
    absent = "\n".join(_paired_paper_trial_lines(None))
    inactive = "\n".join(
        _paired_paper_trial_lines({"enabled": False, "error": None})
    )
    initializing = "\n".join(
        _paired_paper_trial_lines(
            {"portfolio_shadow_candidate_id": "new-frozen-id", "initialized": False}
        )
    )
    assert "- state: `not reported`" in absent
    assert "- state: `not activated`" in inactive
    assert "- state: `initializing`" in initializing


def test_operational_renderer_includes_frozen_paired_trial_status() -> None:
    source = Path("scripts/render_continuous_paper_live_status.py").read_text(
        encoding="utf-8"
    )
    runtime = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )
    assert 'payload.get("loss_context_paired_portfolio_shadow")' in source
    assert "_paired_paper_trial_lines(" in source
    assert '"loss_context_paired_portfolio_shadow": (' in runtime
    assert "pump.loss_context_paired_shadow_payload()" in runtime
