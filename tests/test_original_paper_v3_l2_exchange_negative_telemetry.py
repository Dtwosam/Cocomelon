"""Original venue L2 clock diagnostics are negative-only and never rewrite source."""
from __future__ import annotations

import asyncio
from pathlib import Path

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.fresh_long_trend_source_integrity import (
    MAX_ORIGINAL_L2_EXCHANGE_AGE_MS,
    MAX_ORIGINAL_L2_EXCHANGE_FUTURE_SKEW_MS,
)
from cocomelon.research.original_paper_v3_capture import (
    V3_L2_EXCHANGE_FUTURE_NEGATIVE_SCREEN_MS,
    V3_L2_EXCHANGE_LAG_NEGATIVE_SCREEN_MS,
    OriginalPaperMicrostructureCapture,
)
from scripts.diagnose_original_paper_v3_capture import (
    diagnose_original_paper_v3_capture,
)
from scripts.render_continuous_paper_live_status import (
    _v3_live_capture_lines,
)

T = 1_792_400_000_000
RUN = "1357913"
HEAD = "b" * 40


def _book(at: int, exchange: int | None, key: str, market: str = "TEST") -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source="fixture-original-venue-book",
        schema_version=1,
        market=market,
        exchange_time_ms=exchange,
        event_key=key,
        event_kind="l2_book",
        payload_json='{"bids":[],"asks":[]}',
    )


def test_live_screen_thresholds_match_independent_source_admission() -> None:
    assert V3_L2_EXCHANGE_LAG_NEGATIVE_SCREEN_MS == MAX_ORIGINAL_L2_EXCHANGE_AGE_MS
    assert (
        V3_L2_EXCHANGE_FUTURE_NEGATIVE_SCREEN_MS
        == MAX_ORIGINAL_L2_EXCHANGE_FUTURE_SKEW_MS
    )


def test_original_exchange_clock_health_is_distinct_from_paper_callback_age(
    tmp_path: Path,
) -> None:
    async def run() -> tuple[dict[str, object], dict[str, object]]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "original",
            run_id=RUN, run_attempt="1", head_sha=HEAD,
            selected_markets=("TEST",),
            first_observed_ms=T - 1000,
            replay_config=BaselineReplayConfig(),
        )
        # Exact cutoffs are acceptable, but venue regressions and old
        # exchange depth must remain visible on the original input stream.
        recorder.offer(_book(T, T - 15_000, "exact-lag"))
        recorder.offer(_book(T + 500, T + 1500, "exact-future"))
        recorder.offer(_book(T + 1000, T - 14_001, "stale-and-regressed"))
        recorder.offer(_book(T + 1500, T + 2501, "future-too-far"))
        recorder.offer(_book(T + 2000, None, "missing-exchange-time"))
        recorder.offer(_book(T + 2500, T + 2501, "equal-venue-clock"))
        recorder.offer(_book(T + 3000, 0, "other-stream", market="OTHER"))
        live = recorder.live_diagnostic_snapshot()
        return live, await recorder.close()

    live, terminal = asyncio.run(run())
    assert live["l2_exchange_selected_book_observations"] == 6
    assert live["l2_exchange_unselected_book_observations"] == 1
    assert live["l2_exchange_missing_timestamp_count"] == 1
    assert live["l2_exchange_lag_over_15s_count"] == 1
    assert live["l2_exchange_future_over_1s_count"] == 1
    assert live["l2_exchange_within_market_regressions"] == 1
    assert live["l2_exchange_max_lag_ms"] == 15_001
    assert live["l2_exchange_max_future_skew_ms"] == 1001
    assert live["l2_exchange_tracked_selected_markets"] == 1
    assert live["l2_exchange_diagnostics_not_source_admission"] is True
    assert live["received_clock_regressions"] == 0
    assert terminal["l2_exchange_within_market_regressions"] == 1
    assert terminal["l2_exchange_lag_over_15s_count"] == 1
    assert terminal["l2_exchange_future_over_1s_count"] == 1
    assert terminal["complete"] is True
    assert terminal["external_market_completeness_authenticated"] is False
    assert terminal["promotion_authority"] is False

    lines = "\n".join(_v3_live_capture_lines(live))
    assert "exchange-clock selected / unselected books / missing time: 6 / 1 / 1" in lines
    assert "venue lag >15s / future >1s / market clock regressions: 1 / 1 / 1" in lines
    assert "max exchange lag / future skew ms / tracked markets: 15001 / 1001 / 1" in lines
    assert "source and after-cost profit certification: FALSE" in lines

    diagnostic = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id=RUN, run_attempt="1", head_sha=HEAD,
    )
    assert diagnostic["original_l2_exchange_selected_book_observations"] == 6
    assert diagnostic["original_l2_exchange_missing_timestamp_count"] == 1
    assert diagnostic["original_l2_exchange_lag_over_15s_count"] == 1
    assert diagnostic["original_l2_exchange_future_over_1s_count"] == 1
    assert diagnostic["original_l2_exchange_within_market_regressions"] == 1
    assert diagnostic["original_l2_exchange_max_lag_ms"] == 15_001
    assert diagnostic["source_integrity_certified"] is False
    mismatch = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id="1357914", run_attempt="1", head_sha=HEAD,
    )
    assert mismatch["original_l2_exchange_lag_over_15s_count"] is None
    assert mismatch["original_l2_exchange_within_market_regressions"] is None


def test_exchange_clock_diagnostics_continue_after_raw_receive_failure(
    tmp_path: Path,
) -> None:
    async def run() -> tuple[dict[str, object], dict[str, object]]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "failed",
            run_id=RUN, run_attempt="1", head_sha=HEAD,
            selected_markets=("TEST",),
            first_observed_ms=T - 1000,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(_book(T + 100, T + 99, "good-first"))
        recorder.offer(_book(T, T - 16_000, "old-receipt-and-old-venue"))
        recorder.offer(_book(T + 200, T + 1201, "future-venue"))
        live = recorder.live_diagnostic_snapshot()
        return live, await recorder.close()

    live, terminal = asyncio.run(run())
    assert live["failure"] == "original_received_clock_regression"
    assert live["received_clock_regressions"] == 1
    assert live["l2_exchange_selected_book_observations"] == 3
    assert live["l2_exchange_lag_over_15s_count"] == 1
    assert live["l2_exchange_future_over_1s_count"] == 1
    assert live["l2_exchange_within_market_regressions"] == 1
    assert terminal["complete"] is False
    assert terminal["dropped_count"] >= 2
    assert terminal["promotion_authority"] is False
