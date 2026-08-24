from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _module() -> ModuleType:
    try:
        return importlib.import_module("cocomelon.ops.gap_watch")
    except ModuleNotFoundError as exc:
        pytest.fail(f"gap watcher implementation is missing: {exc}")


def _write_gap(root: Path) -> Path:
    path = root / "gaps" / "2026-08-24" / "segment-000001.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "record_type": "data_gap",
                "stream_id": "l2Book:ENA",
                "started_ms": 1,
                "ended_ms": 2,
                "reason": "disconnect",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_find_first_gap_ignores_empty_segment(tmp_path: Path) -> None:
    module = _module()
    gap = tmp_path / "recording" / "gaps" / "2026-08-24" / "segment-000001.jsonl"
    gap.parent.mkdir(parents=True)
    gap.touch()

    assert module.find_first_gap(tmp_path / "recording") is None

    gap.write_text('{"record_type":"data_gap"}\n', encoding="utf-8")
    assert module.find_first_gap(tmp_path / "recording") == gap


def test_abort_on_gap_sends_sigterm_to_recorder(tmp_path: Path) -> None:
    module = _module()
    recording = tmp_path / "recording"
    gap = _write_gap(recording)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        result = module.abort_on_first_gap(
            recording,
            child.pid,
            poll_seconds=0.01,
        )
        assert result.gap_detected is True
        assert result.gap_path == gap
        assert result.signal_sent is True
        assert result.signal_name == "SIGTERM"
        assert child.wait(timeout=2) != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)


def test_abort_on_gap_handles_process_exit_race(tmp_path: Path) -> None:
    module = _module()
    recording = tmp_path / "recording"
    gap = _write_gap(recording)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=2)

    result = module.abort_on_first_gap(
        recording,
        child.pid,
        poll_seconds=0.01,
    )

    assert result.gap_detected is True
    assert result.gap_path == gap
    assert result.signal_sent is False
    assert result.signal_name is None


def test_gap_watch_cli_reports_abort_and_uses_dedicated_exit_code(tmp_path: Path) -> None:
    _module()
    recording = tmp_path / "recording"
    gap = _write_gap(recording)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "cocomelon.ops.gap_watch",
                "--root",
                str(recording),
                "--pid",
                str(child.pid),
                "--poll-seconds",
                "0.01",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        assert completed.returncode == 20
        payload = json.loads(completed.stdout)
        assert payload == {
            "gap_detected": True,
            "gap_path": str(gap),
            "signal_name": "SIGTERM",
            "signal_sent": True,
        }
        assert child.wait(timeout=2) != 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
