"""Selected-market L2 gap storm attribution is bounded and negative-only."""
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
RUN = "66778800"
HEAD = "c" * 40


def _gap(stream: str, index: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=BASE + 100 * index,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap-{index}",
        event_kind=None,
        payload_json=json.dumps({
            "stream_id": stream,
            "started_ms": BASE + 100 * index - 10,
            "ended_ms": BASE + 100 * index,
            "reason": "recovered",
        }),
    )


async def _record(root: Path, streams: tuple[str, ...]):
    capture = OriginalPaperMicrostructureCapture(
        root,
        run_id=RUN,
        run_attempt="1",
        head_sha=HEAD,
        selected_markets=("TEST", "ALT", "THIRD", "FOURTH"),
        first_observed_ms=BASE,
        replay_config=BaselineReplayConfig(),
    )
    for i, stream in enumerate(streams):
        capture.offer(_gap(stream, i))
    return capture.live_diagnostic_snapshot(), await capture.close()


def test_selected_l2_gap_concentration_and_unknown_stream_exclusion(
    tmp_path: Path,
) -> None:
    streams = (
        "l2Book:TEST", "l2Book:TEST", "l2Book:TEST",
        "l2Book:TEST", "l2Book:ALT", "l2Book:ALT",
        "l2Book:THIRD", "l2Book:UNSELECTED-SOURCE-KEY",
        "l2Book:", "trades:TEST",
    )
    snapshot, terminal = asyncio.run(_record(tmp_path / "original", streams))
    for result in (snapshot, terminal):
        assert result["l2_selected_gap_offered_notice_count"] == 7
        assert result["l2_unselected_gap_offered_notice_count"] == 2
        assert result["l2_selected_gap_affected_market_count"] == 3
        assert result["l2_selected_gap_peak_market_notice_count"] == 4
        assert result["l2_selected_gap_top3_share_bps"] == 10_000
        assert result["gap_l2_stream_offered_count"] == 9
        assert result["gap_non_l2_stream_offered_count"] == 1
        assert result["promotion_authority"] is False
    assert snapshot["source_integrity_certified"] is False
    assert terminal["external_market_completeness_authenticated"] is False
    # Never reflect an unselected or untrusted stream ID as a status key.
    assert "UNSELECTED-SOURCE-KEY" not in json.dumps(snapshot)
    assert "UNSELECTED-SOURCE-KEY" not in json.dumps(terminal)

    diag = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id=RUN,
        run_attempt="1",
        head_sha=HEAD,
    )
    assert diag["original_l2_selected_gap_offered_notice_count"] == 7
    assert diag["original_l2_unselected_gap_offered_notice_count"] == 2
    assert diag["original_l2_selected_gap_top3_share_bps"] == 10_000
    assert diag["source_integrity_certified"] is False
    status = "\n".join(_v3_live_capture_lines(snapshot))
    assert "original selected-market L2 gap notices / outside selection: 7 / 2" in status
    assert (
        "original selected-market L2 gap affected markets / peak notices: 3 / 4"
        in status
    )
    assert "original selected-market L2 gap top-three share (bps): 10000" in status
    assert "UNSELECTED-SOURCE-KEY" not in status


def test_selected_l2_gap_concentration_top_three_of_four(
    tmp_path: Path,
) -> None:
    snapshot, terminal = asyncio.run(_record(tmp_path / "original", (
        "l2Book:TEST", "l2Book:TEST", "l2Book:ALT",
        "l2Book:THIRD", "l2Book:FOURTH",
    )))
    assert snapshot["l2_selected_gap_offered_notice_count"] == 5
    assert snapshot["l2_selected_gap_affected_market_count"] == 4
    assert snapshot["l2_selected_gap_peak_market_notice_count"] == 2
    assert snapshot["l2_selected_gap_top3_share_bps"] == 8_000
    assert terminal["l2_selected_gap_top3_share_bps"] == 8_000
    assert terminal["external_market_completeness_authenticated"] is False


def test_empty_and_foreign_worker_l2_gap_diagnostics(tmp_path: Path) -> None:
    snapshot, terminal = asyncio.run(_record(tmp_path / "original", ()))
    for result in (snapshot, terminal):
        assert result["l2_selected_gap_offered_notice_count"] == 0
        assert result["l2_selected_gap_top3_share_bps"] == 0
        assert result["l2_selected_gap_affected_market_count"] == 0

    foreign = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id="66778801",
        run_attempt="1",
        head_sha=HEAD,
    )
    assert foreign["diagnostic_reason"] == "terminal_identity_mismatch"
    for key in (
        "original_l2_selected_gap_offered_notice_count",
        "original_l2_unselected_gap_offered_notice_count",
        "original_l2_selected_gap_affected_market_count",
        "original_l2_selected_gap_peak_market_notice_count",
        "original_l2_selected_gap_top3_share_bps",
    ):
        assert foreign[key] is None
