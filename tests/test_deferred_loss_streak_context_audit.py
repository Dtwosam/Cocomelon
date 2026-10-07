from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research import deferred_loss_streak_context_audit as deferred


def test_deferred_loss_streak_audit_rejects_unknown_handoff(
    tmp_path: Path,
) -> None:
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "unexpected_failure"}),
        encoding="utf-8",
    )

    with pytest.raises(
        deferred.DeferredLossStreakContextAuditError,
        match="completed paper handoff",
    ):
        deferred.rebuild_deferred_loss_streak_context_audit(tmp_path)


def test_deferred_loss_streak_audit_accepts_duration_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "duration_elapsed"}),
        encoding="utf-8",
    )
    (tmp_path / "journal.sqlite3").write_bytes(b"journal")
    (tmp_path / "facts.sqlite3").write_bytes(b"facts")

    closed: list[str] = []

    class FakeJournal:
        def __init__(self, _path: Path) -> None:
            pass

        def iter_trades(self) -> tuple[object, ...]:
            return ()

        def close(self) -> None:
            closed.append("journal")

    class FakeFacts:
        def __init__(self, _path: Path) -> None:
            pass

        def close(self) -> None:
            closed.append("facts")

    monkeypatch.setattr(deferred, "JournalStore", FakeJournal)
    monkeypatch.setattr(deferred, "EvaluationFactStore", FakeFacts)
    monkeypatch.setattr(
        deferred,
        "LearningFeatureSnapshotStore",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        deferred,
        "ContinuousPaperOpeningRankStore",
        lambda _path: object(),
    )
    monkeypatch.setattr(
        deferred,
        "loss_streak_context_audit",
        lambda *_args: {
            "research_only": True,
            "descriptive_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "changes_strategy": False,
            "changes_risk_limits": False,
        },
    )

    payload = deferred.rebuild_deferred_loss_streak_context_audit(
        tmp_path
    )

    assert payload["source_exit_reason"] == "duration_elapsed"
    assert payload["deferred_post_handoff_rebuild"] is True
    assert payload["execution_authority"] is False
    assert sorted(closed) == ["facts", "journal"]


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
