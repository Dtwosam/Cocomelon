"""Immutable ordinary-PAPER entry policy; never a position-management switch."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ENTRY_SUSPENSION_FILENAME = "paper-entry-suspension.json"
_REASON = "unvalidated_strategy_no_new_allocation"


@dataclass(frozen=True, slots=True)
class PaperEntrySuspension:
    effective_at_ms: int
    origin_worker_run_id: int | None
    origin_worker_head_sha: str | None
    restore_status: str
    durable: bool

    @property
    def entries_suspended(self) -> Literal[True]:
        return True

    @property
    def new_exposure_cutoff_ms(self) -> Literal[0]:
        return 0

    def _record(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "scope": "ordinary_paper",
            "entries_suspended": True,
            "effective_at_ms": self.effective_at_ms,
            "reason": _REASON,
            "origin_worker_run_id": self.origin_worker_run_id,
            "origin_worker_head_sha": self.origin_worker_head_sha,
        }

    def payload(self) -> dict[str, object]:
        return {
            **self._record(),
            "restore_status": self.restore_status,
            "durable": self.durable,
            "live_orders": False,
        }


def load_entry_suspension(
    state_root: Path,
    *,
    timestamp_ms: int,
    worker_run_id: int | None = None,
    worker_head_sha: str | None = None,
) -> PaperEntrySuspension:
    """Keep entries blocked even if policy evidence is absent or unusable.

    This file is passive provenance, not an authority to resume. Its failure
    must not stop management or mark the execution/account state unhealthy.
    """
    if type(timestamp_ms) is not int or timestamp_ms < 0:
        raise ValueError("suspension timestamp must be non-negative")
    if worker_run_id is not None and (type(worker_run_id) is not int or worker_run_id <= 0):
        raise ValueError("worker run must be a positive integer")
    if worker_head_sha is not None and (
        not isinstance(worker_head_sha, str)
        or len(worker_head_sha) != 40
        or any(char not in "0123456789abcdef" for char in worker_head_sha)
    ):
        raise ValueError("worker head must be a lowercase commit SHA")
    path = state_root / ENTRY_SUSPENSION_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        return PaperEntrySuspension(
            timestamp_ms, worker_run_id, worker_head_sha, "invalid_preserved", False
        )
    else:
        if isinstance(raw, dict):
            effective = raw.get("effective_at_ms")
            origin_run = raw.get("origin_worker_run_id")
            origin_head = raw.get("origin_worker_head_sha")
            if (
                type(raw.get("schema_version")) is int
                and raw["schema_version"] == 1
                and raw.get("scope") == "ordinary_paper"
                and raw.get("entries_suspended") is True
                and raw.get("reason") == _REASON
                and type(effective) is int
                and 0 <= effective <= timestamp_ms
                and (origin_run is None or type(origin_run) is int and origin_run > 0)
                and (
                    origin_head is None
                    or isinstance(origin_head, str)
                    and len(origin_head) == 40
                    and all(char in "0123456789abcdef" for char in origin_head)
                )
            ):
                return PaperEntrySuspension(effective, origin_run, origin_head, "restored", True)
        return PaperEntrySuspension(
            timestamp_ms, worker_run_id, worker_head_sha, "invalid_preserved", False
        )

    policy = PaperEntrySuspension(timestamp_ms, worker_run_id, worker_head_sha, "created", True)
    temporary = path.with_suffix(".tmp")
    try:
        state_root.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(policy._record(), stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        return PaperEntrySuspension(
            timestamp_ms, worker_run_id, worker_head_sha, "write_failed", False
        )
    return policy
