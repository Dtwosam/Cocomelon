"""A resumed PAPER worker cannot inherit a predecessor's terminal receipt."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import cocomelon.continuous_paper as paper
from cocomelon.config import ExecutionMode, Settings


def test_successor_retires_old_summary_before_restored_checkpoint_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "restored-worker-state"
    root.mkdir()
    predecessor_summary = root / paper.SUMMARY_FILENAME
    predecessor_summary.write_text(
        json.dumps({
            "exit_reason": "duration_elapsed",
            "ended_at_ms": 1792162846242,
            "open_positions": 0,
        }),
        encoding="utf-8",
    )
    checkpoint = root / paper.CHECKPOINT_FILENAME
    checkpoint.write_bytes(b"immutable-exact-paper-account-checkpoint")

    def observe_checkpoint_load(path: Path) -> None:
        assert path == checkpoint
        assert path.read_bytes() == b"immutable-exact-paper-account-checkpoint"
        assert not predecessor_summary.exists()
        raise RuntimeError("controlled checkpoint-load stop")

    monkeypatch.setattr(paper, "_load_checkpoint", observe_checkpoint_load)
    with pytest.raises(RuntimeError, match="controlled checkpoint-load stop"):
        asyncio.run(paper.run_continuous_paper_session(
            root,
            paper.ContinuousPaperConfig(duration_seconds=1),
            settings=cast(
                Settings,
                SimpleNamespace(execution_mode=ExecutionMode.PAPER),
            ),
        ))

    assert not predecessor_summary.exists()
    assert checkpoint.read_bytes() == b"immutable-exact-paper-account-checkpoint"


def test_stale_session_summary_retirement_is_idempotent_and_fail_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path
    checkpoint = root / paper.CHECKPOINT_FILENAME
    checkpoint.write_bytes(b"do-not-modify-account")
    previous = root / paper.SUMMARY_FILENAME
    previous.write_text('{"exit_reason":"upgrade_requested"}', encoding="utf-8")
    paper._retire_previous_session_handoff(root)
    paper._retire_previous_session_handoff(root)
    assert not previous.exists()
    assert checkpoint.read_bytes() == b"do-not-modify-account"

    # If a suspicious directory occupies the supposed receipt path,
    # startup may not continue with stale/misidentified terminal evidence.
    previous.mkdir()
    with pytest.raises(IsADirectoryError):
        paper._retire_previous_session_handoff(root)
