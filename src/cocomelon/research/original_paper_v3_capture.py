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
from cocomelon.util.time import utc_now_ms

MAX_PENDING_RECORDS: Final = 16_384
# Bounded negative stream-clock attribution; never source data or evidence.
MAX_TRACKED_ORIGINAL_L2_STREAMS: Final = 512
BATCH_SIZE: Final = 256
# One shared limit with the closed original source ZIP sealer.
MAX_SOURCE_ROWS: Final = 5_000_000
MAX_SOURCE_BYTES: Final = 480 * 1024 * 1024
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


class OriginalCaptureBudgetExceeded(RuntimeError):
    """Original prospective source is irreversibly above its seal limit."""


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
        predecessor_run_id: str | None = None,
        predecessor_run_attempt: str | None = None,
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
        if (
            (predecessor_run_id is None) != (predecessor_run_attempt is None)
            or (
                predecessor_run_id is not None
                and (
                    not predecessor_run_id.isdecimal()
                    or not predecessor_run_attempt
                    or not predecessor_run_attempt.isdecimal()
                    or int(predecessor_run_id) <= 0
                    or int(predecessor_run_attempt) <= 0
                    or predecessor_run_id == run_id
                )
            )
        ):
            raise ValueError("original predecessor declaration invalid")
        self.predecessor_run_id = predecessor_run_id
        self.predecessor_run_attempt = predecessor_run_attempt
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
        self.record_bytes = 0
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
        # These separate cases diagnose source scheduling without changing
        # original input bytes, receipt order or PAPER's permissive clock.
        self.regressions_vs_prior_offered = 0
        self.regressions_vs_paper_clock = 0
        self.max_original_clock_backward_ms = 0
        self.first_regression_cause: str | None = None
        self.first_regression_event_kind: str | None = None
        self.first_received_clock_regression: dict[str, object] | None = None
        # Event source+market clock tracking distinguishes delayed interleaving
        # across streams from regressions within one original L2 stream.
        # Only bounded aggregate counts appear in diagnostics, never raw keys.
        self._last_l2_received_ms_by_stream: dict[
            tuple[str, str, str], int
        ] = {}
        self.l2_stream_clock_tracking_overflow = 0
        self.l2_within_stream_clock_regressions = 0
        self.l2_cross_stream_only_clock_regressions = 0
        self.l2_offer_age_observations = 0
        self.l2_offer_age_over_1s_count = 0
        self.l2_offer_age_over_5s_count = 0
        self.l2_offer_age_over_15s_count = 0
        self.l2_offer_timestamp_future_count = 0
        self.l2_max_offer_age_ms = 0
        # DATA_GAP.available_at_ms historically represents the gap's
        # start/end boundary, NOT necessarily the moment PAPER observed
        # the gap. These anonymous counters expose that distinction; no
        # source time or existing PAPER event is modified or qualified.
        self.gap_offered_count = 0
        self.gap_open_offered_count = 0
        self.gap_closed_offered_count = 0
        self.gap_boundary_age_over_1s_count = 0
        self.gap_boundary_age_over_15s_count = 0
        self.gap_boundary_timestamp_future_count = 0
        self.gap_max_boundary_age_ms = 0
        self.first_regression_gap_boundary_kind: str | None = None
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
        prior_offered = self.last_offered_available_at_ms
        prior_paper = paper_previous_at_ms
        gap_boundary_kind: str | None = None
        if record.record_kind.value == "data_gap":
            # Gap payload bounds are not immutable arrival receipts:
            # (start, end) may be established before the gap is emitted.
            # Record only bounded aggregate age and open/closed classes.
            self.gap_offered_count += 1
            try:
                gap_payload = json.loads(record.payload_json)
            except (ValueError, TypeError):
                gap_payload = None
            if isinstance(gap_payload, dict):
                raw_end = gap_payload.get("ended_ms")
                if raw_end is None:
                    gap_boundary_kind = "open"
                    self.gap_open_offered_count += 1
                elif type(raw_end) is int:
                    gap_boundary_kind = "closed"
                    self.gap_closed_offered_count += 1
            gap_age_ms = utc_now_ms() - record.available_at_ms
            self.gap_boundary_age_over_1s_count += int(gap_age_ms > 1_000)
            self.gap_boundary_age_over_15s_count += int(gap_age_ms > 15_000)
            self.gap_boundary_timestamp_future_count += int(gap_age_ms < 0)
            self.gap_max_boundary_age_ms = max(
                self.gap_max_boundary_age_ms, gap_age_ms
            )
        within_l2_stream_regression = False
        if (
            record.record_kind.value == "normalized_event"
            and record.event_kind == "l2_book"
            and record.market is not None
        ):
            # L2 receive timestamps are local observed times, not exchange
            # book times. The age at PAPER offer detects event-loop/backlog
            # delays without ever altering the recorded original timestamp.
            age_ms = utc_now_ms() - record.available_at_ms
            self.l2_offer_age_observations += 1
            self.l2_offer_age_over_1s_count += int(age_ms > 1_000)
            self.l2_offer_age_over_5s_count += int(age_ms > 5_000)
            self.l2_offer_age_over_15s_count += int(age_ms > 15_000)
            self.l2_offer_timestamp_future_count += int(age_ms < 0)
            self.l2_max_offer_age_ms = max(self.l2_max_offer_age_ms, age_ms)
            stream_id = (record.source, record.market, record.event_kind)
            prior_same_stream = self._last_l2_received_ms_by_stream.get(stream_id)
            within_l2_stream_regression = (
                prior_same_stream is not None
                and record.available_at_ms < prior_same_stream
            )
            if within_l2_stream_regression:
                self.l2_within_stream_clock_regressions += 1
            if (
                prior_same_stream is not None
                or len(self._last_l2_received_ms_by_stream)
                < MAX_TRACKED_ORIGINAL_L2_STREAMS
            ):
                self._last_l2_received_ms_by_stream[stream_id] = max(
                    prior_same_stream or 0, record.available_at_ms
                )
            else:
                self.l2_stream_clock_tracking_overflow += 1
        below_offered = (
            prior_offered is not None and record.available_at_ms < prior_offered
        )
        below_paper = (
            prior_paper is not None and record.available_at_ms < prior_paper
        )
        latest = max(prior_offered or 0, prior_paper or 0)
        if below_offered or below_paper:
            self.received_clock_regressions += 1
            if (
                record.record_kind.value == "normalized_event"
                and record.event_kind == "l2_book"
                and below_offered
                and not within_l2_stream_regression
            ):
                self.l2_cross_stream_only_clock_regressions += 1
            self.regressions_vs_prior_offered += int(below_offered)
            self.regressions_vs_paper_clock += int(below_paper)
            self.max_original_clock_backward_ms = max(
                self.max_original_clock_backward_ms,
                latest - record.available_at_ms,
            )
            if self.first_received_clock_regression is None:
                self.first_regression_gap_boundary_kind = gap_boundary_kind
                self.first_regression_cause = (
                    "both_prior_input_and_paper_clock"
                    if below_offered and below_paper
                    else "prior_input_clock"
                    if below_offered
                    else "paper_previous_clock"
                )
                # Fixed vocabulary avoids embedding opaque event keys, raw
                # source payloads, private paths or secrets in the heartbeat.
                self.first_regression_event_kind = (
                    record.event_kind
                    if record.event_kind in (
                        "l2_book", "trades", "candle", "active_asset_ctx"
                    )
                    else "data_gap"
                    if record.record_kind.value == "data_gap"
                    else "other"
                )
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

    def live_diagnostic_snapshot(self) -> dict[str, object]:
        """Memory-only capture counters; NEVER a source or profit certificate."""
        return {
            "schema": "v3-original-capture-live-negative-telemetry-v1",
            "enabled": True,
            "first_observed_ms": self.first_observed_ms,
            "original_selected_markets": len(self.selected_markets),
            "offered_count": self.offered_count,
            "written_count": self.record_count,
            # Pending/in-flight during a live heartbeat; an unacknowledged
            # batch on failure once the recorder is closed.
            "offered_not_written_or_dropped_count": max(
                0, self.offered_count - self.record_count - self.dropped_count
            ),
            "written_source_journal_bytes": self.record_bytes,
            "source_journal_byte_limit": MAX_SOURCE_BYTES,
            "remaining_persisted_byte_budget": max(0, MAX_SOURCE_BYTES - self.record_bytes),
            "source_journal_row_limit": MAX_SOURCE_ROWS,
            "remaining_persisted_row_budget": max(0, MAX_SOURCE_ROWS - self.record_count),
            "pending_queue_depth": self.queue.qsize(),
            "dropped_count": self.dropped_count,
            "received_clock_regressions": self.received_clock_regressions,
            "regressions_vs_prior_offered": self.regressions_vs_prior_offered,
            "regressions_vs_paper_clock": self.regressions_vs_paper_clock,
            "max_original_clock_backward_ms": self.max_original_clock_backward_ms,
            "first_regression_cause": self.first_regression_cause,
            "first_regression_event_kind": self.first_regression_event_kind,
            "l2_tracked_distinct_streams": len(
                self._last_l2_received_ms_by_stream
            ),
            "l2_stream_clock_tracking_overflow": (
                self.l2_stream_clock_tracking_overflow
            ),
            "l2_within_stream_clock_regressions": (
                self.l2_within_stream_clock_regressions
            ),
            "l2_cross_stream_only_clock_regressions": (
                self.l2_cross_stream_only_clock_regressions
            ),
            "l2_offer_age_observations": self.l2_offer_age_observations,
            "l2_offer_age_over_1s_count": self.l2_offer_age_over_1s_count,
            "l2_offer_age_over_5s_count": self.l2_offer_age_over_5s_count,
            "l2_offer_age_over_15s_count": self.l2_offer_age_over_15s_count,
            "l2_offer_timestamp_future_count": (
                self.l2_offer_timestamp_future_count
            ),
            "l2_max_offer_age_ms": self.l2_max_offer_age_ms,
            "gap_offered_count": self.gap_offered_count,
            "gap_open_offered_count": self.gap_open_offered_count,
            "gap_closed_offered_count": self.gap_closed_offered_count,
            "gap_boundary_age_over_1s_count": (
                self.gap_boundary_age_over_1s_count
            ),
            "gap_boundary_age_over_15s_count": (
                self.gap_boundary_age_over_15s_count
            ),
            "gap_boundary_timestamp_future_count": (
                self.gap_boundary_timestamp_future_count
            ),
            "gap_max_boundary_age_ms": self.gap_max_boundary_age_ms,
            "first_regression_gap_boundary_kind": (
                self.first_regression_gap_boundary_kind
            ),
            "last_written_available_at_ms": self.last_available_at_ms,
            "failure": self.failure,
            "closed": self.closed,
            "local_live_snapshot_not_terminal_proof": True,
            "capture_admissible_from_heartbeat": False,
            "source_integrity_certified": False,
            "original_venue_feed_complete": False,
            "after_cost_profitability_verified": False,
            "paper_only": True,
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }

    def _write_batch(self, rows: list[ReplayRecord]) -> int:
        # Check BEFORE durable writes, using the exact canonical bytes that
        # the post-handoff sealer will read. A worker must not spend hours
        # persisting an archive that can never pass the frozen ZIP budget.
        encoded_rows = [_canonical_json(_replay_payload(row)) for row in rows]
        batch_bytes = sum(len(encoded) for encoded in encoded_rows)
        if self.record_count + len(rows) > MAX_SOURCE_ROWS:
            raise OriginalCaptureBudgetExceeded(
                "original_capture_source_row_budget_exceeded"
            )
        if self.record_bytes + batch_bytes > MAX_SOURCE_BYTES:
            raise OriginalCaptureBudgetExceeded(
                "original_capture_source_byte_budget_exceeded"
            )
        with (self.root / RECORD_FILE).open("ab") as stream:
            for encoded in encoded_rows:
                written = stream.write(encoded)
                if written != len(encoded):
                    raise OSError("short original source journal write")
                self._original_journal_sha256.update(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return batch_bytes

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
                    written_bytes = await asyncio.to_thread(self._write_batch, batch)
                    # Both counters become visible together on the event loop,
                    # after the worker thread has durably fsynced its batch.
                    self.record_count += len(batch)
                    self.record_bytes += written_bytes
                    self.last_available_at_ms = batch[-1].available_at_ms
            except OriginalCaptureBudgetExceeded as exc:
                self.failure = self.failure or str(exc)
            except Exception as exc:
                self.failure = self.failure or f"write_failed:{type(exc).__name__}"
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
        status: dict[str, object] = {
            "schema": READY_SCHEMA,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "head_sha": self.head_sha,
            "declared_predecessor_run_id": self.predecessor_run_id,
            "declared_predecessor_run_attempt": self.predecessor_run_attempt,
            "predecessor_state_restore_independently_authenticated": False,
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
            # Pending/in-flight during a live heartbeat; an unacknowledged
            # batch on failure once the recorder is closed.
            "offered_not_written_or_dropped_count": max(
                0, self.offered_count - self.record_count - self.dropped_count
            ),
            "written_source_journal_bytes": self.record_bytes,
            "source_journal_byte_limit": MAX_SOURCE_BYTES,
            "source_journal_row_limit": MAX_SOURCE_ROWS,
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
            "regressions_vs_prior_offered": self.regressions_vs_prior_offered,
            "regressions_vs_paper_clock": self.regressions_vs_paper_clock,
            "max_original_clock_backward_ms": self.max_original_clock_backward_ms,
            "first_regression_cause": self.first_regression_cause,
            "first_regression_event_kind": self.first_regression_event_kind,
            "l2_tracked_distinct_streams": len(
                self._last_l2_received_ms_by_stream
            ),
            "l2_stream_clock_tracking_overflow": (
                self.l2_stream_clock_tracking_overflow
            ),
            "l2_within_stream_clock_regressions": (
                self.l2_within_stream_clock_regressions
            ),
            "l2_cross_stream_only_clock_regressions": (
                self.l2_cross_stream_only_clock_regressions
            ),
            "l2_offer_age_observations": self.l2_offer_age_observations,
            "l2_offer_age_over_1s_count": self.l2_offer_age_over_1s_count,
            "l2_offer_age_over_5s_count": self.l2_offer_age_over_5s_count,
            "l2_offer_age_over_15s_count": self.l2_offer_age_over_15s_count,
            "l2_offer_timestamp_future_count": (
                self.l2_offer_timestamp_future_count
            ),
            "l2_max_offer_age_ms": self.l2_max_offer_age_ms,
            "gap_offered_count": self.gap_offered_count,
            "gap_open_offered_count": self.gap_open_offered_count,
            "gap_closed_offered_count": self.gap_closed_offered_count,
            "gap_boundary_age_over_1s_count": (
                self.gap_boundary_age_over_1s_count
            ),
            "gap_boundary_age_over_15s_count": (
                self.gap_boundary_age_over_15s_count
            ),
            "gap_boundary_timestamp_future_count": (
                self.gap_boundary_timestamp_future_count
            ),
            "gap_max_boundary_age_ms": self.gap_max_boundary_age_ms,
            "first_regression_gap_boundary_kind": (
                self.first_regression_gap_boundary_kind
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
