from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research import deferred_correlation_bucket_priority as deferred


def test_deferred_priority_requires_upgrade_handoff(tmp_path: Path) -> None:
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "duration_elapsed"}),
        encoding="utf-8",
    )

    with pytest.raises(
        deferred.DeferredCorrelationBucketPriorityError,
        match="upgrade-requested handoff",
    ):
        deferred.rebuild_deferred_correlation_bucket_priority(tmp_path)


def test_deferred_priority_requires_rebuilt_markouts(tmp_path: Path) -> None:
    (tmp_path / "session-summary.json").write_text(
        json.dumps({"exit_reason": "upgrade_requested"}),
        encoding="utf-8",
    )
    (tmp_path / deferred.FORWARD_MARKOUT_FILENAME).write_text(
        json.dumps(
            {
                "execution_authority": False,
                "risk_rejected_rows": [],
                "deferred_post_handoff_rebuild": False,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        deferred.DeferredCorrelationBucketPriorityError,
        match="rebuilt post-handoff markouts",
    ):
        deferred.rebuild_deferred_correlation_bucket_priority(tmp_path)


def test_deferred_priority_write_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        deferred,
        "rebuild_deferred_correlation_bucket_priority",
        lambda _root: {
            "research_only": True,
            "execution_authority": False,
            "changes_risk_limits": False,
            "changes_entry_priority": False,
            "stack_admitted_correlation_rejections": 2,
        },
    )

    output = deferred.write_deferred_correlation_bucket_priority(tmp_path)

    assert output == tmp_path / deferred.OUTPUT_FILENAME
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["execution_authority"] is False
    assert payload["changes_risk_limits"] is False
    assert not (tmp_path / f".{deferred.OUTPUT_FILENAME}.tmp").exists()
