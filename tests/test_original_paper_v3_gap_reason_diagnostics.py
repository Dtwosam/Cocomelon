"""Genuine original gap debt is visible without changing or qualifying source."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    ORIGINAL_GAP_REASON_BUCKETS,
    OriginalPaperMicrostructureCapture,
)
from scripts.diagnose_original_paper_v3_capture import (
    diagnose_original_paper_v3_capture,
)
from scripts.render_continuous_paper_live_status import (
    _v3_live_capture_lines,
)

BASE = 1_792_162_800_000
RUN = "9988877"
HEAD = "a" * 40


def _gap(at: int, *, stream: str, reason: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap-{at}",
        event_kind=None,
        payload_json=json.dumps({
            "stream_id": stream,
            "started_ms": at - 1,
            "ended_ms": at,
            "reason": reason,
        }),
    )


async def _capture(tmp_path: Path):
    recorder = OriginalPaperMicrostructureCapture(
        tmp_path / "original",
        run_id=RUN,
        run_attempt="1",
        head_sha=HEAD,
        selected_markets=("TEST",),
        first_observed_ms=BASE,
        replay_config=BaselineReplayConfig(),
    )
    for row in (
        _gap(BASE + 1, stream="l2Book:TEST", reason="redundant_disconnect"),
        _gap(BASE + 2, stream="l2Book:TEST", reason="recovered"),
        _gap(BASE + 3, stream="candle:TEST", reason="secret-opaque-input"),
        _gap(
            BASE + 4, stream="fundingHistory:TEST",
            reason="MAINNET_FUNDING_HISTORY_INFO_UNAVAILABLE",
        ),
    ):
        recorder.offer(row)
    snapshot = recorder.live_diagnostic_snapshot()
    return snapshot, await recorder.close()


def test_bounded_gap_reason_and_l2_debt_from_actual_offers(
    tmp_path: Path,
) -> None:
    live, terminal = asyncio.run(_capture(tmp_path))
    assert live["gap_offered_count"] == 4
    assert live["gap_l2_stream_offered_count"] == 2
    assert live["gap_non_l2_stream_offered_count"] == 2
    expected = dict.fromkeys(ORIGINAL_GAP_REASON_BUCKETS, 0)
    expected.update({
        "redundant_disconnect": 1,
        "recovered": 1,
        "MAINNET_FUNDING_HISTORY_INFO_UNAVAILABLE": 1,
        "other": 1,
    })
    assert live["gap_reason_counts"] == expected
    assert terminal["gap_reason_counts"] == expected
    assert terminal["complete"] is True
    assert terminal["external_market_completeness_authenticated"] is False
    assert terminal["promotion_authority"] is False
    assert "secret-opaque-input" not in json.dumps(live)
    assert "secret-opaque-input" not in json.dumps(terminal)

    report = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id=RUN,
        run_attempt="1",
        head_sha=HEAD,
    )
    assert report["original_gap_reason_counts"] == expected
    assert report["original_gap_l2_stream_offered_count"] == 2
    assert report["original_gap_non_l2_stream_offered_count"] == 2
    assert report["source_integrity_certified"] is False

    visible = "\n".join(_v3_live_capture_lines(live))
    assert "source gap L2 / other stream notices: 2 / 2" in visible
    assert "source gap reasons disconnect / recovered / handoff / rotation:" in visible
    assert "source gap reasons funding / other: 1 / 1" in visible
    assert "secret-opaque-input" not in visible
    assert "source and after-cost profit certification: FALSE" in visible


def test_foreign_worker_cannot_claim_gap_reason_counts(
    tmp_path: Path,
) -> None:
    asyncio.run(_capture(tmp_path))
    report = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id="9988878",
        run_attempt="1",
        head_sha=HEAD,
    )
    assert report["diagnostic_reason"] == "terminal_identity_mismatch"
    assert report["original_gap_reason_counts"] is None
    assert report["original_gap_l2_stream_offered_count"] is None
    assert report["original_gap_non_l2_stream_offered_count"] is None
