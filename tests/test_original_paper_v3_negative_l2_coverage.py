"""Negative original L2 coverage cannot be confused with healthy source."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    OriginalPaperMicrostructureCapture,
)
from scripts.diagnose_original_paper_v3_capture import (
    diagnose_original_paper_v3_capture,
)

HEAD = "a" * 40
RUN = "99998888"
ATTEMPT = "1"
BASE = 1_792_162_800_000


def _row(market: str, kind: str, at: int, key: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=market,
        exchange_time_ms=at,
        event_key=key,
        event_kind=kind,
        payload_json=json.dumps({}),
    )


async def _record(tmp_path: Path, rows: tuple[ReplayRecord, ...]):
    capture = OriginalPaperMicrostructureCapture(
        tmp_path / "capture",
        run_id=RUN,
        run_attempt=ATTEMPT,
        head_sha=HEAD,
        selected_markets=("ALT", "TEST"),
        first_observed_ms=BASE,
        replay_config=BaselineReplayConfig(),
    )
    snapshots = []
    for row in rows:
        capture.offer(row)
        snapshots.append(capture.live_diagnostic_snapshot())
    return snapshots, await capture.close()


def _diagnostic(tmp_path: Path) -> dict[str, object]:
    return diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "capture",
        diagnostic_root=tmp_path,
        run_id=RUN,
        run_attempt=ATTEMPT,
        head_sha=HEAD,
    )


def test_clean_writer_still_exposes_missing_market_and_trailing_l2_drought(
    tmp_path: Path,
) -> None:
    snapshots, terminal = asyncio.run(_record(tmp_path, (
        _row("TEST", "l2_book", BASE, "initial-book"),
        _row("TEST", "candle", BASE + 360_000, "still-running"),
    )))
    assert terminal["complete"] is True
    assert terminal["dropped_count"] == 0
    assert terminal["original_received_clock_regressions"] == 0
    assert snapshots[0]["l2_selected_market_zero_book_count"] == 1
    assert snapshots[-1]["source_offered_elapsed_ms"] == 360_000
    assert terminal["source_offered_elapsed_ms"] == 360_000
    assert terminal["l2_selected_market_offered_book_count"] == 1
    assert terminal["l2_selected_market_zero_book_count"] == 1
    assert terminal["l2_selected_market_min_offered_books"] == 0
    assert terminal["l2_selected_market_max_observed_gap_ms"] == 360_000
    assert terminal["l2_selected_market_over_5min_drought_count"] == 2
    report = _diagnostic(tmp_path)
    assert report["diagnostic_reason"] == (
        "local_capture_terminal_complete_needs_external_audit"
    )
    assert report["original_l2_selected_market_over_5min_drought_count"] == 2
    assert report["original_l2_selected_market_zero_book_count"] == 1
    assert report["original_source_offered_elapsed_ms"] == 360_000
    assert report["source_integrity_certified"] is False
    assert report["independent_venue_feed_complete"] is False
    assert report["execution_authority"] is False


def test_per_market_interior_gap_counts_even_when_books_resume(
    tmp_path: Path,
) -> None:
    _, terminal = asyncio.run(_record(tmp_path, (
        _row("TEST", "l2_book", BASE, "t1"),
        _row("ALT", "l2_book", BASE + 1, "a1"),
        _row("TEST", "l2_book", BASE + 301_000, "t2"),
        _row("ALT", "l2_book", BASE + 301_001, "a2"),
    )))
    assert terminal["complete"] is True
    assert terminal["l2_selected_market_offered_book_count"] == 4
    assert terminal["l2_selected_market_min_offered_books"] == 2
    assert terminal["l2_selected_market_zero_book_count"] == 0
    assert terminal["l2_selected_market_max_observed_gap_ms"] == 301_000
    assert terminal["l2_selected_market_over_5min_drought_count"] == 2


def test_foreign_worker_diagnostic_never_exposes_coverage(
    tmp_path: Path,
) -> None:
    asyncio.run(_record(tmp_path, (
        _row("TEST", "l2_book", BASE, "initial"),
    )))
    foreign = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "capture",
        diagnostic_root=tmp_path,
        run_id="99998889",
        run_attempt=ATTEMPT,
        head_sha=HEAD,
    )
    assert foreign["diagnostic_reason"] == "terminal_identity_mismatch"
    for field in (
        "original_source_offered_elapsed_ms",
        "original_l2_selected_market_offered_book_count",
        "original_l2_selected_market_zero_book_count",
        "original_l2_selected_market_min_offered_books",
        "original_l2_selected_market_max_observed_gap_ms",
        "original_l2_selected_market_over_5min_drought_count",
    ):
        assert foreign[field] is None
