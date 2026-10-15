"""Nonblocking, ORIGINAL paper input capture for a future frozen v3 study.

The trader never waits for research disk I/O. Capture failures permanently
disqualify this run's artifact; no sample substitution or dropped-gap repair.
Only ordinary PAPER's actual ReplayRecord input, not fabricated venue data.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from cocomelon.domain.replay import ReplayRecord

MAX_PENDING_RECORDS: Final = 16_384
BATCH_SIZE: Final = 256
RECORD_FILE: Final = "original-received-rows.jsonl"
TERMINAL_FILE: Final = "original-capture-terminal.json"
READY_SCHEMA: Final = "fresh-v3-original-paper-async-receipt-v1"


def _canonical_json(data: object) -> bytes:
    return (json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ) + "\n").encode("utf-8")


def _atomic_json(path: Path, value: object) -> None:
    raw = _canonical_json(value)
    temporary = path.with_name("." + path.name + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _replay_payload(row: ReplayRecord) -> dict[str, object]:
    return {
        "record_kind": row.record_kind.value,
        "available_at_ms": row.available_at_ms,
        "source": row.source,
        "schema_version": row.schema_version,
        "market": row.market,
        "exchange_time_ms": row.exchange_time_ms,
        "event_key": row.event_key,
        "payload_json": row.payload_json,
        "event_kind": row.event_kind,
    }


class OriginalPaperMicrostructureCapture:
    """Bounded write-ahead journal, independent from the trading event loop."""

    def __init__(
        self,
        root: Path,
        *,
        run_id: str,
        run_attempt: str,
        head_sha: str,
        selected_markets: Sequence[str],
        first_observed_ms: int,
    ) -> None:
        if (
            not run_id.isdecimal() or not run_attempt.isdecimal()
            or len(head_sha) != 40
            or any(c not in "0123456789abcdef" for c in head_sha)
            or first_observed_ms <= 0
            or not selected_markets
            or not all(isinstance(x, str) and x for x in selected_markets)
        ):
            raise ValueError("original paper recording worker identity invalid")
        self.root = root
        self.run_id = run_id
        self.run_attempt = run_attempt
        self.head_sha = head_sha
        self.selected_markets = tuple(sorted(selected_markets))
        if len(set(self.selected_markets)) != len(self.selected_markets):
            raise ValueError("duplicate original selected markets")
        self.first_observed_ms = first_observed_ms
        self.root.mkdir(parents=True, exist_ok=False)
        self.queue: asyncio.Queue[ReplayRecord] = asyncio.Queue(
            maxsize=MAX_PENDING_RECORDS
        )
        self.record_count = 0
        self.offered_count = 0
        self.dropped_count = 0
        self.last_available_at_ms: int | None = None
        self.failure: str | None = None
        self.closed = False
        self._task = asyncio.create_task(self._writer())
        self._started = True

    def offer(self, record: ReplayRecord) -> None:
        if self.closed:
            self.dropped_count += 1
            self.failure = self.failure or "offer_after_close"
            return
        self.offered_count += 1
        if self.failure is not None:
            self.dropped_count += 1
            return
        try:
            self.queue.put_nowait(record)
        except asyncio.QueueFull:
            # PAPER continues. The future study must fail closed forever.
            self.dropped_count += 1
            self.failure = "original_capture_queue_overflow"

    def _write_batch(self, rows: list[ReplayRecord]) -> None:
        with (self.root / RECORD_FILE).open("ab") as stream:
            for row in rows:
                stream.write(_canonical_json(_replay_payload(row)))
            stream.flush()
            os.fsync(stream.fileno())

    async def _writer(self) -> None:
        while True:
            row = await self.queue.get()
            batch = [row]
            while len(batch) < BATCH_SIZE:
                try:
                    batch.append(self.queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                if self.failure is None:
                    await asyncio.to_thread(self._write_batch, batch)
                    self.record_count += len(batch)
                    self.last_available_at_ms = batch[-1].available_at_ms
            except Exception as exc:
                self.failure = f"write_failed:{type(exc).__name__}"
            finally:
                for _ in batch:
                    self.queue.task_done()

    async def close(self, *, timeout_seconds: float = 90.0) -> dict[str, object]:
        if not self.closed:
            self.closed = True
            try:
                await asyncio.wait_for(self.queue.join(), timeout=timeout_seconds)
            except (TimeoutError, asyncio.CancelledError):
                self.failure = self.failure or "drain_timeout"
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        status = {
            "schema": READY_SCHEMA,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "head_sha": self.head_sha,
            "first_observed_ms": self.first_observed_ms,
            "selected_markets_at_worker_start": list(self.selected_markets),
            "offered_count": self.offered_count,
            "written_count": self.record_count,
            "dropped_count": self.dropped_count,
            "last_written_available_at_ms": self.last_available_at_ms,
            "failure": self.failure,
            "complete": (
                self.failure is None
                and self.dropped_count == 0
                and self.record_count == self.offered_count
                and self.record_count > 0
            ),
            "no_inter_worker_continuity_attestation": True,
            "external_market_completeness_authenticated": False,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
        try:
            await asyncio.to_thread(
                _atomic_json, self.root / TERMINAL_FILE, status
            )
        except OSError:
            # Never affect genuine PAPER cleanup on evidence write failure.
            pass
        return status
