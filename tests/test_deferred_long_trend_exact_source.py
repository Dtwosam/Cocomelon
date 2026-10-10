from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.rebuild_deferred_long_trend_exact_source import (
    DeferredLongTrendSourceError,
    rebuild_deferred_long_trend_source,
    write_deferred_long_trend_source,
)
from scripts.verify_compact_long_trend_exact_source import verify_source


def _populate(root: Path, *, exit_reason: str = "upgrade_requested") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "session-summary.json").write_text(
        json.dumps({"exit_reason": exit_reason}), encoding="utf-8"
    )
    (root / "prospective-full-stack-forward-markout-summary.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "error": None,
                "research_only": True,
                "execution_authority": False,
                "promotion_authority": False,
                "changes_readiness_gate": False,
                "changes_closed_trade_readiness_gate": False,
                "overlap_started_at_ms": 1,
                "risk_rejected_rows": [],
                "risk_rejected_stack_evaluated": 0,
                "risk_rejected_integrity_clean": True,
                "risk_rejected_missing_rank": 0,
                "deferred_post_handoff_rebuild": True,
                "source_exit_reason": "upgrade_requested",
            }
        ),
        encoding="utf-8",
    )
    for folder in (
        "opening-opportunities/records",
        "opening-opportunity-paths/records",
        "opening-opportunity-exit-books/records",
        "replacement-funding-boundaries/records",
    ):
        (root / folder).mkdir(parents=True, exist_ok=True)


def test_upgrade_source_preserves_authenticated_empty_cohort(tmp_path: Path) -> None:
    _populate(tmp_path)
    path = write_deferred_long_trend_source(tmp_path)
    source = json.loads(path.read_text(encoding="utf-8"))
    assert source["source_opportunity_count"] == 0
    assert source["opportunities"] == []
    assert source["enabled"] is True
    assert source["error"] is None
    assert source["execution_authority"] is False
    assert source["promotion_authority"] is False
    assert verify_source(tmp_path)["ready"] is True


def test_nonupgrade_cannot_rebuild_or_replace_signed_file(tmp_path: Path) -> None:
    _populate(tmp_path, exit_reason="duration_elapsed")
    target = tmp_path / "prospective-long-trend-execution-shadow-source.json"
    target.write_text("signed original", encoding="utf-8")
    with pytest.raises(DeferredLongTrendSourceError, match="upgrade-requested"):
        write_deferred_long_trend_source(tmp_path)
    assert target.read_text(encoding="utf-8") == "signed original"


def test_no_same_handoff_full_stack_rebuild_fails_closed(tmp_path: Path) -> None:
    _populate(tmp_path)
    path = tmp_path / "prospective-full-stack-forward-markout-summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_exit_reason"] = "duration_elapsed"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(DeferredLongTrendSourceError, match="same-handoff"):
        rebuild_deferred_long_trend_source(tmp_path)


def test_missing_or_invalid_full_stack_fails_closed(tmp_path: Path) -> None:
    _populate(tmp_path)
    path = tmp_path / "prospective-full-stack-forward-markout-summary.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(DeferredLongTrendSourceError, match="missing or invalid"):
        write_deferred_long_trend_source(tmp_path)
    assert not (tmp_path / "prospective-long-trend-execution-shadow-source.json").exists()


def test_dirty_full_stack_source_cannot_pass_compact_gate(tmp_path: Path) -> None:
    _populate(tmp_path)
    path = tmp_path / "prospective-full-stack-forward-markout-summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["risk_rejected_integrity_clean"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    write_deferred_long_trend_source(tmp_path)
    report = verify_source(tmp_path)
    assert report["ready"] is False
    assert report["inputs"][0]["reason"] == "risk_rejected_integrity_not_clean"
