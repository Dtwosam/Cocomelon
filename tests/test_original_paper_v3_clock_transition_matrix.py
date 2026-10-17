"""Original immediately-adjacent clock family edges, never repaired source."""
from __future__ import annotations

import asyncio
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

BASE = 1_792_257_800_000
RUN = "390555001"
HEAD = "d" * 40


def _record(ms: int, kind: str, *, source: str = "fixture") -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=ms,
        source=source,
        schema_version=1,
        market="TEST",
        exchange_time_ms=ms,
        event_key=f"{kind}:{ms}",
        event_kind=kind,
        payload_json="{}",
    )


def test_true_adjacent_original_misorders_distinguished_from_paper_knockon(
    tmp_path: Path,
) -> None:
    async def run() -> tuple[dict[str, object], dict[str, object]]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "original", run_id=RUN, run_attempt="1",
            head_sha=HEAD, selected_markets=("TEST",),
            first_observed_ms=BASE - 1_000,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(_record(BASE + 100, "market_snapshot"))
        recorder.offer(
            _record(BASE + 50, "l2_book"),
            paper_previous_at_ms=BASE + 100,
        )
        # A later PAPER highwater may reject the next original event even
        # when it was correctly AFTER the preceding original input.
        recorder.offer(
            _record(BASE + 200, "funding_rate"),
            paper_previous_at_ms=BASE + 300,
        )
        recorder.offer(
            _record(BASE + 190, "candle"),
            paper_previous_at_ms=BASE + 300,
        )
        return recorder.live_diagnostic_snapshot(), await recorder.close()

    live, terminal = asyncio.run(run())
    expected = {
        "market_snapshot -> l2_book": 1,
        "funding_rate -> candle": 1,
    }
    assert live["first_regression_prior_family"] == "market_snapshot"
    assert live["first_regression_source_family"] == "l2_book"
    assert live["regressions_vs_prior_offered"] == 2
    assert live["regressions_vs_paper_clock"] == 3
    assert live["received_clock_regressions"] == 3
    assert live["max_adjacent_original_backward_ms"] == 50
    assert live["prior_offered_regression_edges"] == expected
    assert live["prior_offered_edge_counts_reconcile"] is True
    assert terminal["prior_offered_regression_edges"] == expected
    assert terminal["original_received_clock_regressions"] == 3
    assert terminal["complete"] is False
    assert terminal["promotion_authority"] is False

    status = "\n".join(_v3_live_capture_lines(live))
    assert "market_snapshot / 50" in status
    assert "original adjacent family edge counts / prior-clock reconciled: 2 / true" in status
    assert "funding_rate -> candle=1" in status
    assert "market_snapshot -> l2_book=1" in status
    assert "source and after-cost profit certification: FALSE" in status
    diagnostic = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original", diagnostic_root=tmp_path,
        run_id=RUN, run_attempt="1", head_sha=HEAD,
    )
    assert diagnostic["original_first_regression_prior_family"] == "market_snapshot"
    assert diagnostic["original_adjacent_family_edges"] == expected
    assert diagnostic["original_max_adjacent_backward_ms"] == 50
    assert diagnostic["source_integrity_certified"] is False
    mismatch = diagnose_original_paper_v3_capture(
        capture_root=tmp_path / "original", diagnostic_root=tmp_path,
        run_id="390555002", run_attempt="1", head_sha=HEAD,
    )
    assert mismatch["original_adjacent_family_edges"] is None
    assert mismatch["original_first_regression_prior_family"] is None


def test_opaque_source_families_never_reflected_in_public_regression_edges(
    tmp_path: Path,
) -> None:
    async def run() -> dict[str, object]:
        recorder = OriginalPaperMicrostructureCapture(
            tmp_path / "unsafe", run_id=RUN, run_attempt="1",
            head_sha=HEAD, selected_markets=("TEST",),
            first_observed_ms=BASE - 1_000,
            replay_config=BaselineReplayConfig(),
        )
        recorder.offer(_record(BASE + 100, "private_secret_type"))
        recorder.offer(_record(BASE + 50, "l2_book", source="private_source_id"))
        snapshot = recorder.live_diagnostic_snapshot()
        await recorder.close()
        return snapshot

    snapshot = asyncio.run(run())
    assert snapshot["prior_offered_regression_edges"] == {
        "other -> l2_book": 1
    }
    status = "\n".join(_v3_live_capture_lines(snapshot))
    assert "other -> l2_book=1" in status
    assert "private_secret_type" not in status
    assert "private_source_id" not in status
    # Even a forged diagnostic payload is rejected by the renderer.
    snapshot["prior_offered_regression_edges"] = {
        "private_source -> l2_book": 12, "other -> l2_book": 1
    }
    assert "private_source" not in "\n".join(_v3_live_capture_lines(snapshot))
