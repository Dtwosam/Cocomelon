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
from cocomelon.evidence.contracts import BaselineReplayConfig

MAX_PENDING_RECORDS: Final = 16_384
BATCH_SIZE: Final = 256
RECORD_FILE: Final = "original-received-rows.jsonl"
TERMINAL_FILE: Final = "original-capture-terminal.json"
READY_SCHEMA: Final = "fresh-v3-original-paper-async-receipt-v1"
STARTUP_FAILURE_FILE: Final = "v3-original-capture-init-failure.json"


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


def persist_original_capture_startup_failure(
    diagnostic_root: Path, *,
    run_id: str, run_attempt: str, head_sha: str, error: Exception,
) -> None:
    """Best-effort, local, nonqualifying cause of recorder startup denial.

    Only preserve the exception class, never private paths, API secrets,
    original source content or a fabricated terminal recording.
    """
    _atomic_json(diagnostic_root / STARTUP_FAILURE_FILE, {
        "schema": "v3-original-paper-recorder-init-failed-v1",
        "run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "exception_class": type(error).__name__,
        "original_capture_started": False,
        "source_admissible": False,
        "paper_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    })


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
        replay_config: BaselineReplayConfig,
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
        # Capture the *actual effective* PAPER strategy/risk/cost contract.
        # A later offline replay may never substitute cheaper fees, a
        # different fill model or a looser risk configuration and call it
        # a matched original-source forward account.
        self.replay_config_digest = replay_config.config_digest
        self.execution_config_version = replay_config.execution.config_version
        self.fee_schedule_id = replay_config.execution.fee_schedule_id
        self.feature_version = replay_config.feature_version
        self.strategy_version = replay_config.strategy_version
        self.risk_version = replay_config.risk_version
        self.replay_engine_version = replay_config.replay_engine_version
        self.root.mkdir(parents=True, exist_ok=False)
        self.queue: asyncio.Queue[ReplayRecord] = asyncio.Queue(
            maxsize=MAX_PENDING_RECORDS
        )
        self.record_count = 0
        self.offered_count = 0
        self.dropped_count = 0
        self.last_available_at_ms: int | None = None
        # Digest the original ordered bytes IN THE writer thread so the
        # terminal receipt binds the actual append-only source journal,
        # not an order assigned later by the post-worker ZIP sealer.
        self._original_journal_sha256 = hashlib.sha256()
        # The PAPER pipeline is allowed to clamp regressing receive clocks;
        # the original research copy is NOT. Preserve the unmodified first-
        # received timestamp, and permanently disqualify a clamped input.
        self.last_offered_available_at_ms: int | None = None
        self.received_clock_regressions = 0
        self.first_received_clock_regression: dict[str, object] | None = None
        self.failure: str | None = None
        self.closed = False
        self._task = asyncio.create_task(self._writer())

    def offer(
        self, record: ReplayRecord, *,
        paper_previous_at_ms: int | None = None,
    ) -> None:
        if self.closed:
            self.dropped_count += 1
            self.failure = self.failure or "offer_after_close"
            return
        self.offered_count += 1
        # The caller MUST pass the PAPER pipeline's previous timestamp,
        # including a restored previous-worker checkpoint. Comparing only
        # local offered rows would overlook a first-record regression.
        latest = max(
            self.last_offered_available_at_ms or 0,
            paper_previous_at_ms or 0,
        )
        if record.available_at_ms < latest:
            self.received_clock_regressions += 1
            if self.first_received_clock_regression is None:
                self.first_received_clock_regression = {
                    "original_available_at_ms": record.available_at_ms,
                    "prior_original_or_paper_available_at_ms": latest,
                    "original_event_key": record.event_key,
                    "original_market": record.market,
                }
            self.failure = self.failure or "original_received_clock_regression"
        self.last_offered_available_at_ms = record.available_at_ms
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
                encoded = _canonical_json(_replay_payload(row))
                written = stream.write(encoded)
                if written != len(encoded):
                    raise OSError("short original source journal write")
                self._original_journal_sha256.update(encoded)
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
            "original_effective_replay_config_digest": self.replay_config_digest,
            "original_effective_execution_config_version": (
                self.execution_config_version
            ),
            "original_effective_fee_schedule_id": self.fee_schedule_id,
            "original_effective_feature_version": self.feature_version,
            "original_effective_strategy_version": self.strategy_version,
            "original_effective_risk_version": self.risk_version,
            "original_effective_replay_engine_version": (
                self.replay_engine_version
            ),
            "offered_count": self.offered_count,
            "written_count": self.record_count,
            "original_received_journal_sha256": (
                self._original_journal_sha256.hexdigest()
            ),
            "dropped_count": self.dropped_count,
            "last_written_available_at_ms": self.last_available_at_ms,
            "last_original_offered_available_at_ms": (
                self.last_offered_available_at_ms
            ),
            "original_received_clock_regressions": (
                self.received_clock_regressions
            ),
            "first_original_received_clock_regression": (
                self.first_received_clock_regression
            ),
            "paper_monotonic_clock_adjustment_not_used_as_source": True,
            "failure": self.failure,
            "complete": (
                self.failure is None
                and self.dropped_count == 0
                and self.received_clock_regressions == 0
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
