"""Forensic gap coverage remains negative and never invents received source."""
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
from scripts.render_continuous_paper_live_status import (
    _v3_live_capture_lines,
)

BASE = 1_792_162_800_000
RUN = "66778899"
HEAD = "a" * 40


def _row(at: int, event_kind: str, key: str, market: str = "TEST") -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=market,
        exchange_time_ms=at,
        event_key=key,
        event_kind=event_kind,
        payload_json="{}",
    )


def _gap(
    at: int, stream: str, start: int, end: int | None, key: str,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=key,
        event_kind=None,
        payload_json=json.dumps({
            "stream_id": stream, "started_ms": start,
            "ended_ms": end, "reason": "recovered" if end is not None else "stale",
        }),
    )


async def _capture(tmp_path: Path, rows: tuple[ReplayRecord, ...]):
    recorder = OriginalPaperMicrostructureCapture(
        tmp_path / "capture", run_id=RUN, run_attempt="1",
        head_sha=HEAD, selected_markets=("TEST", "ALT"),
        first_observed_ms=BASE, replay_config=BaselineReplayConfig(),
    )
    snapshots = []
    for row in rows:
        recorder.offer(row)
        snapshots.append(recorder.live_diagnostic_snapshot())
    return snapshots, await recorder.close()


def test_late_regression_cannot_shrink_negative_l2_coverage(
    tmp_path: Path,
) -> None:
    live, terminal = asyncio.run(_capture(tmp_path, (
        _row(BASE, "l2_book", "test-initial"),
        _row(BASE + 360_000, "candle", "six-minutes-later"),
        _row(BASE + 1, "candle", "late-backdated"),
    )))
    assert live[1]["source_offered_elapsed_ms"] == 360_000
    assert live[2]["source_offered_elapsed_ms"] == 360_000
    assert terminal["source_offered_elapsed_ms"] == 360_000
    assert terminal["l2_selected_market_max_observed_gap_ms"] == 360_000
    assert terminal["l2_selected_market_over_5min_drought_count"] == 2
    assert terminal["original_received_clock_regressions"] == 1
    assert terminal["complete"] is False
    assert terminal["external_market_completeness_authenticated"] is False
    assert terminal["promotion_authority"] is False


def test_closed_gap_duration_uses_original_bounds_not_observation_age(
    tmp_path: Path,
) -> None:
    snapshots, terminal = asyncio.run(_capture(tmp_path, (
        _gap(BASE + 10_000, "l2Book:TEST", BASE, BASE + 5_000, "l2-closed"),
        _gap(BASE + 11_000, "trades:ALT", BASE, BASE + 2_000, "other-closed"),
        _gap(BASE + 12_000, "l2Book:TEST", BASE, None, "l2-open"),
        _gap(BASE + 13_000, "l2Book:TEST", BASE + 8_000, BASE + 7_000, "bad"),
    )))
    assert terminal["gap_offered_count"] == 4
    assert terminal["gap_closed_offered_count"] == 3
    assert terminal["gap_closed_valid_l2_duration_ms_total"] == 5_000
    assert terminal["gap_closed_valid_non_l2_duration_ms_total"] == 2_000
    assert terminal["gap_closed_l2_max_duration_ms"] == 5_000
    assert terminal["gap_closed_non_l2_max_duration_ms"] == 2_000
    assert terminal["gap_closed_l2_ge_5s_count"] == 1
    assert terminal["gap_closed_non_l2_ge_5s_count"] == 0
    assert terminal["gap_closed_invalid_bounds_count"] == 1
    assert snapshots[-1]["gap_closed_valid_l2_duration_ms_total"] == 5_000
    assert terminal["complete"] is True
    assert terminal["external_market_completeness_authenticated"] is False
    assert terminal["promotion_authority"] is False

    diag = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "capture", diagnostic_root=tmp_path,
        run_id=RUN, run_attempt="1", head_sha=HEAD,
    )
    assert diag["original_gap_closed_valid_l2_duration_ms_total"] == 5_000
    assert diag["original_gap_closed_invalid_bounds_count"] == 1
    assert diag["source_integrity_certified"] is False
    lines = "\n".join(_v3_live_capture_lines(snapshots[-1]))
    assert "closed source-gap L2 / other total historical ms: 5000 / 2000" in lines
    assert "closed source-gap L2 / other maximum ms: 5000 / 2000" in lines
    assert "closed source-gap L2 / other >=5s / invalid bound notices: 1 / 0 / 1" in lines
    assert "source and after-cost profit certification: FALSE" in lines


def test_foreign_worker_cannot_export_duration_counts(tmp_path: Path) -> None:
    asyncio.run(_capture(tmp_path, (
        _gap(BASE + 8_000, "l2Book:TEST", BASE, BASE + 6_000, "l2"),
    )))
    diag = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "capture", diagnostic_root=tmp_path,
        run_id="66778898", run_attempt="1", head_sha=HEAD,
    )
    assert diag["diagnostic_reason"] == "terminal_identity_mismatch"
    for field in (
        "original_gap_closed_valid_l2_duration_ms_total",
        "original_gap_closed_valid_non_l2_duration_ms_total",
        "original_gap_closed_l2_max_duration_ms",
        "original_gap_closed_non_l2_max_duration_ms",
        "original_gap_closed_l2_ge_5s_count",
        "original_gap_closed_non_l2_ge_5s_count",
        "original_gap_closed_invalid_bounds_count",
    ):
        assert diag[field] is None
