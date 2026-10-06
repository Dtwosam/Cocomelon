from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research import deferred_loss_streak_context_audit as deferred


def test_deferred_loss_streak_audit_requires_upgrade_handoff(
    tmp_path: Path,
) -> None:
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "duration_elapsed"}),
        encoding="utf-8",
    )

    with pytest.raises(
        deferred.DeferredLossStreakContextAuditError,
        match="upgrade-requested handoff",
    ):
        deferred.rebuild_deferred_loss_streak_context_audit(tmp_path)


def test_deferred_loss_streak_write_is_atomic_and_authority_negative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deferred,
        "rebuild_deferred_loss_streak_context_audit",
        lambda _root: {
            "research_only": True,
            "descriptive_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "trade_count": 10,
            "qualifying_loss_streak_count": 2,
            "current_consecutive_losses": 4,
            "recurring_dominant_patterns": [],
        },
    )

    output = deferred.write_deferred_loss_streak_context_audit(tmp_path)

    assert output == tmp_path / deferred.OUTPUT_FILENAME
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["execution_authority"] is False
    assert payload["changes_strategy"] is False
    assert payload["changes_risk_limits"] is False
    assert not (tmp_path / f".{deferred.OUTPUT_FILENAME}.tmp").exists()
