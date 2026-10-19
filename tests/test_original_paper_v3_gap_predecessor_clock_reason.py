"""Negative-only exact gap reason at first-received clock reversals.

Never re-time, suppress, sort, or certify failed original evidence.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    OriginalPaperMicrostructureCapture,
)
from scripts.render_continuous_paper_live_status import _v3_live_capture_lines

BASE = 1_792_262_000_000


def _gap(
    at: int, reason: str, *, closed: bool = False, malformed: bool = False,
) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key=f"gap:{at}:{reason}",
        payload_json=json.dumps({
            "stream_id": "l2Book:BTC",
            "reason": reason,
            "started_ms": at - 100 if not malformed else "wrong",
            "ended_ms": at - 20 if closed else None,
        }),
        event_kind=None,
    )


def _trade(at: int, name: str) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="BTC",
        exchange_time_ms=at,
        event_key=name,
        event_kind="trade",
        payload_json="{}",
    )


def _run(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    async def run() -> tuple[dict[str, object], dict[str, object]]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "capture", run_id="392600005",
            run_attempt="1", head_sha="f" * 40,
            selected_markets=("BTC",),
            first_observed_ms=BASE - 1_000,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(_gap(BASE + 100, "redundant_disconnect"))
        recorder.offer(_trade(BASE + 50, "late-first-trade"))
        # These include a later independent gap receipt that is NOT a
        # clock regression against its subsequent market event.
        recorder.offer(_gap(BASE + 200, "recovered", closed=True))
        recorder.offer(_trade(BASE + 230, "after-recovered"))
        # Unknown original arbitrary gap reason is deliberately bucketed.
        recorder.offer(_gap(BASE + 400, "private-key-source-name"))
        recorder.offer(_trade(BASE + 250, "late-private-trade"))
        # Invalid historical bounds stay invalid, never quietly certified.
        recorder.offer(_gap(BASE + 500, "recovered", malformed=True))
        recorder.offer(_trade(BASE + 450, "late-after-malformed"))
        return recorder.live_diagnostic_snapshot(), await recorder.close()

    return asyncio.run(run())


def test_predecessor_reason_and_open_close_reconcile_without_healing(
    tmp_path: Path,
) -> None:
    snapshot, terminal = _run(tmp_path)
    assert snapshot["first_regression_prior_family"] == "data_gap"
    assert snapshot["first_regression_event_kind"] == "trade"
    assert snapshot["first_regression_prior_gap_reason"] == "redundant_disconnect"
    assert snapshot["first_regression_prior_gap_boundary"] == "open"
    assert snapshot["regressions_vs_prior_offered"] == 3
    assert snapshot["gap_predecessor_counts_reconcile"] is True
    counts = snapshot["gap_predecessor_regression_counts"]
    assert isinstance(counts, dict)
    assert counts["open:redundant_disconnect"] == 1
    assert counts["open:other"] == 1
    assert counts["open:recovered"] == 1
    assert sum(counts.values()) == 3
    assert snapshot["failure"] == "original_received_clock_regression"
    assert terminal["complete"] is False
    assert terminal["promotion_authority"] is False
    assert terminal["gap_predecessor_counts_reconcile"] is True
    assert terminal["gap_predecessor_regression_counts"] == counts

    status = "\n".join(_v3_live_capture_lines(snapshot))
    assert (
        "first preceding original gap reason / open-close: "
        "redundant_disconnect / open"
    ) in status
    assert (
        "original gap predecessor bucket counts / adjacent-edge reconcile: "
        "3 / true"
    ) in status
    assert "private-key-source-name" not in status
    assert "source and after-cost profit certification: FALSE" in status


def test_true_closed_gap_reason_and_paper_clock_only_regression(
    tmp_path: Path,
) -> None:
    async def run() -> dict[str, object]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "closed", run_id="392600006",
            run_attempt="1", head_sha="d" * 40,
            selected_markets=("BTC",),
            first_observed_ms=BASE - 1_000,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(_gap(BASE + 120, "recovered", closed=True))
        recorder.offer(_trade(BASE + 100, "inversion"))
        recorder.offer(_gap(BASE + 220, "recovered", closed=True))
        # Original source clock moves forward; only PAPER may reject it.
        recorder.offer(
            _trade(BASE + 230, "paper-high-water"),
            paper_previous_at_ms=BASE + 300,
        )
        snapshot = recorder.live_diagnostic_snapshot()
        await recorder.close()
        return snapshot

    snap = asyncio.run(run())
    assert snap["first_regression_prior_gap_reason"] == "recovered"
    assert snap["first_regression_prior_gap_boundary"] == "closed"
    assert snap["gap_predecessor_regression_counts"]["closed:recovered"] == 1
    assert snap["regressions_vs_prior_offered"] == 1
    assert snap["regressions_vs_paper_clock"] == 1
    assert snap["received_clock_regressions"] == 2
    assert snap["gap_predecessor_counts_reconcile"] is True


def test_raw_diagnostic_keys_cannot_leak_into_public_heartbeat(tmp_path: Path) -> None:
    snap, _ = _run(tmp_path)
    snap["first_regression_prior_gap_reason"] = ["private-secret"]
    snap["first_regression_prior_gap_boundary"] = {"unknown": 1}
    snap["gap_predecessor_regression_counts"] = {
        "open:private-stream": 9999,
        "open:redundant_disconnect": 1,
        "closed:recovered": -50,
        "open:other": True,
    }
    status = "\n".join(_v3_live_capture_lines(snap))
    assert "private-secret" not in status
    assert "private-stream" not in status
    assert "unknown" not in status
    assert (
        "first preceding original gap reason / open-close: "
        "none observed / none observed"
    ) in status
    assert "open:redundant_disconnect=1" in status
    assert "open:other=True" not in status
    assert "bucket counts / adjacent-edge reconcile: 1 / false" in status
