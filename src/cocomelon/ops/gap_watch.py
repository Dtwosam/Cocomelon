from __future__ import annotations

import argparse
import json
import os
import signal
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

GAP_ABORT_EXIT_CODE = 20
Sleep = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class GapAbortResult:
    gap_detected: bool
    gap_path: Path | None
    signal_sent: bool
    signal_name: str | None

    def payload(self) -> dict[str, object]:
        return {
            "gap_detected": self.gap_detected,
            "gap_path": None if self.gap_path is None else str(self.gap_path),
            "signal_name": self.signal_name,
            "signal_sent": self.signal_sent,
        }


def find_first_gap(recording_root: str | Path) -> Path | None:
    gap_root = Path(recording_root) / "gaps"
    if not gap_root.is_dir():
        return None
    for path in sorted(gap_root.rglob("segment-*.jsonl")):
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except FileNotFoundError:
            continue
    return None


def abort_on_first_gap(
    recording_root: str | Path,
    recorder_pid: int,
    *,
    poll_seconds: float = 0.5,
    sleep: Sleep = time.sleep,
) -> GapAbortResult:
    if recorder_pid <= 0:
        raise ValueError("recorder_pid must be positive")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")

    while True:
        gap_path = find_first_gap(recording_root)
        if gap_path is None:
            sleep(poll_seconds)
            continue

        signal_sent = True
        try:
            os.kill(recorder_pid, signal.SIGTERM)
        except ProcessLookupError:
            signal_sent = False
        return GapAbortResult(
            gap_detected=True,
            gap_path=gap_path,
            signal_sent=signal_sent,
            signal_name="SIGTERM" if signal_sent else None,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-gap-watch")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = abort_on_first_gap(
        args.root,
        args.pid,
        poll_seconds=args.poll_seconds,
    )
    print(json.dumps(result.payload(), sort_keys=True))
    raise SystemExit(GAP_ABORT_EXIT_CODE)


if __name__ == "__main__":
    main()
