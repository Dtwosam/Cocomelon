"""Avoid per-gap Python list copies while preserving exact PAPER recovery JSON."""
from __future__ import annotations

import json
from types import SimpleNamespace

from cocomelon.continuous_paper import _checkpoint_payload
from cocomelon.domain.market import MarketId


def test_legacy_and_global_gap_fast_snapshot_is_byte_identical() -> None:
    legacy = ((10, None), (15, 20), (30, 32), (40, None))
    scoped = {
        "activeAssetCtx:BTC": ((4, 5), (7, None)),
        "l2Book:BTC": ((11, 17),),
    }
    globals_ = {
        "allMids": ((100, None), (200, 201)),
        "unknown-global-topic": ((111, 140),),
    }
    pipeline = SimpleNamespace(
        open_lifecycle_checkpoints=(),
        unscoped_gap_intervals=legacy,
        known_gap_intervals_by_stream=scoped,
        known_global_gap_intervals_by_stream=globals_,
    )
    phases: dict[str, int] = {}
    payload = _checkpoint_payload(
        pipeline,  # type: ignore[arg-type]
        last_available_at_ms=300,
        selected_markets=(MarketId("", "BTC"),),
        stage_timings_ms=phases,
    )
    assert payload["known_gap_intervals"] is legacy
    assert payload["known_gap_intervals_by_stream"] is scoped
    assert payload["known_global_gap_intervals_by_stream"] is globals_

    # Reconstruct the exact previous list-per-interval representation.
    previous = dict(payload)
    previous["known_gap_intervals"] = [
        [start, end] for start, end in legacy
    ]
    previous["known_gap_intervals_by_stream"] = {
        stream: [[start, end] for start, end in intervals]
        for stream, intervals in scoped.items()
    }
    previous["known_global_gap_intervals_by_stream"] = {
        stream: [[start, end] for start, end in intervals]
        for stream, intervals in globals_.items()
    }
    original_bytes = json.dumps(
        previous, sort_keys=False, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    optimized_bytes = json.dumps(
        payload, sort_keys=False, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    assert optimized_bytes == original_bytes
    assert all(v >= 0 for v in phases.values())
    assert payload["schema_version"] == 3
    assert payload["execution_mode"] == "paper"
    assert payload["live_orders"] is False


def test_large_original_gap_history_is_not_materialized_into_nested_lists() -> None:
    legacy = tuple((1000 + i * 2, 1001 + i * 2) for i in range(5000))
    shared = {"allMids": legacy, "unknown": ((20000, None),)}
    pipeline = SimpleNamespace(
        open_lifecycle_checkpoints=(),
        unscoped_gap_intervals=legacy,
        known_gap_intervals_by_stream={},
        known_global_gap_intervals_by_stream=shared,
    )
    payload = _checkpoint_payload(
        pipeline,  # type: ignore[arg-type]
        last_available_at_ms=20_001,
        selected_markets=(MarketId("", "BTC"),),
    )
    assert payload["known_gap_intervals"] is legacy
    assert payload["known_global_gap_intervals_by_stream"] is shared
    decoded = json.loads(json.dumps(payload))
    assert decoded["known_gap_intervals"][0] == [1000, 1001]
    assert decoded["known_gap_intervals"][-1] == [10998, 10999]
    assert decoded["known_global_gap_intervals_by_stream"]["unknown"] == [
        [20000, None]
    ]
    assert len(decoded["known_global_gap_intervals_by_stream"]["allMids"]) == 5000
    assert decoded["execution_mode"] == "paper"
    assert decoded["live_orders"] is False
