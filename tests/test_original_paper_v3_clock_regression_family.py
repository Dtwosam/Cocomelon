"""Attribute real original receive-clock regressions, never legalize them."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.original_paper_v3_capture import (
    ORIGINAL_CLOCK_REGRESSION_FAMILIES,
    OriginalPaperMicrostructureCapture,
    _clock_regression_family,
)
from scripts.diagnose_original_paper_v3_capture import (
    diagnose_original_paper_v3_capture,
)
from scripts.render_continuous_paper_live_status import (
    _v3_live_capture_lines,
)

BASE = 1_792_162_800_000
RUN = "88996655"
HEAD = "a" * 40


def _row(at: int, kind: str, source: str = "hyperliquid-mainnet-info") -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=at,
        source=source,
        schema_version=1,
        market="TEST",
        exchange_time_ms=at,
        event_key=f"orig-{at}-{kind}",
        event_kind=kind,
        payload_json="{}",
    )


def test_original_regression_family_is_bounded_even_for_opaque_events() -> None:
    for kind in (
        "market_snapshot", "funding_rate", "candle", "l2_book",
        "trades", "active_asset_ctx",
    ):
        assert _clock_regression_family(_row(BASE, kind)) == kind
    assert _clock_regression_family(_row(BASE, "sensitive-external-event")) == "other"
    gap = ReplayRecord(
        record_kind=SourceRecordKind.DATA_GAP,
        available_at_ms=BASE,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market=None,
        exchange_time_ms=None,
        event_key="gap-closed",
        event_kind=None,
        payload_json=json.dumps({
            "stream_id": "l2Book:TEST",
            "started_ms": BASE - 20,
            "ended_ms": BASE,
            "reason": "recovered",
        }),
    )
    assert _clock_regression_family(gap) == "data_gap"


def test_first_rest_snapshot_regression_and_following_l2_stay_disqualified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    import cocomelon.research.original_paper_v3_capture as mod

    monkeypatch.setattr(mod, "utc_now_ms", lambda: BASE + 10_000)

    async def capture():
        sink = OriginalPaperMicrostructureCapture(
            tmp_path / "original",
            run_id=RUN, run_attempt="1", head_sha=HEAD,
            selected_markets=("TEST",),
            first_observed_ms=BASE, replay_config=BaselineReplayConfig(),
        )
        sink.offer(_row(BASE + 2_000, "market_snapshot"))
        sink.offer(
            _row(BASE + 1_000, "market_snapshot"),
            paper_previous_at_ms=BASE + 2_000,
        )
        sink.offer(
            _row(BASE + 900, "l2_book", "hyperliquid-mainnet-ws"),
            paper_previous_at_ms=BASE + 2_000,
        )
        return sink.live_diagnostic_snapshot(), await sink.close()

    live, terminal = asyncio.run(capture())
    expected = dict.fromkeys(ORIGINAL_CLOCK_REGRESSION_FAMILIES, 0)
    expected["market_snapshot"] = 1
    expected["l2_book"] = 1
    assert live["first_regression_source_family"] == "market_snapshot"
    assert live["first_regression_age_at_offer_ms"] == 9_000
    assert live["regression_source_family_counts"] == expected
    assert terminal["first_regression_source_family"] == "market_snapshot"
    assert terminal["first_regression_age_at_offer_ms"] == 9_000
    assert terminal["regression_source_family_counts"] == expected
    assert terminal["original_received_clock_regressions"] == 2
    assert terminal["complete"] is False
    assert terminal["promotion_authority"] is False
    assert terminal["external_market_completeness_authenticated"] is False
    status = "\n".join(_v3_live_capture_lines(live))
    assert (
        "first original regression source family / original age at offer ms: "
        "market_snapshot / 9000"
    ) in status
    assert "original regressions market-snapshot / funding / candle: 1 / 0 / 0" in status
    assert "original regressions L2 / trade / asset-ctx / gap / other: 1 / 0 / 0 / 0 / 0" in status
    assert "source and after-cost profit certification: FALSE" in status

    report = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id=RUN, run_attempt="1", head_sha=HEAD,
    )
    assert report["original_first_regression_source_family"] == "market_snapshot"
    assert report["original_regression_source_family_counts"] == expected
    assert report["original_first_regression_age_at_offer_ms"] == 9_000
    assert report["source_integrity_certified"] is False

    foreign = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original",
        diagnostic_root=tmp_path,
        run_id="88996656", run_attempt="1", head_sha=HEAD,
    )
    assert foreign["diagnostic_reason"] == "terminal_identity_mismatch"
    assert foreign["original_first_regression_source_family"] is None
    assert foreign["original_regression_source_family_counts"] is None
    assert foreign["original_first_regression_age_at_offer_ms"] is None
