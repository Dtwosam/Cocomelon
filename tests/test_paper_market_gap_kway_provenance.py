"""Exact trade-close gap debt must survive faster sorted k-way union."""
from __future__ import annotations

from random import Random

from cocomelon.domain.market import MarketId
from cocomelon.evidence.lifecycle import (
    BaselineReplayPipeline,
    _compact_gap_intervals,
    _compact_sorted_gap_sources,
)


def test_kway_gap_union_equals_legacy_full_sort_on_randomized_sources() -> None:
    rng = Random(20261016)
    for _ in range(900):
        sources = []
        for _ in range(rng.randrange(1, 13)):
            records: list[tuple[int, int | None]] = []
            for _ in range(rng.randrange(0, 25)):
                start = rng.randrange(0, 400)
                end = (
                    start + rng.randrange(0, 60)
                    if rng.random() > 0.35 else None
                )
                records.append((start, end))
            sources.append(_compact_gap_intervals(records))
        expected = tuple(_compact_gap_intervals([
            row for source in sources for row in source
        ]))
        assert _compact_sorted_gap_sources(sources) == expected


def _bare_pipeline(
    legacy: list[tuple[int, int | None]],
    scoped: dict[str, list[tuple[int, int | None]]],
    global_gaps: dict[str, list[tuple[int, int | None]]],
    unordered: set[str],
) -> BaselineReplayPipeline:
    # Exact provenance union reads only the four explicit gap stores,
    # without mutating execution, positions, the journal or any trade.
    pipeline = object.__new__(BaselineReplayPipeline)
    pipeline._gap_intervals = legacy
    pipeline._gap_intervals_by_stream = scoped
    pipeline._global_gap_intervals_by_stream = global_gaps
    pipeline._gap_unordered_stream_ids = unordered
    return pipeline


def test_actual_trade_close_market_gap_union_retains_shared_and_scoped_debt() -> None:
    legacy = _compact_gap_intervals([(0, 5), (100, None)])
    global_gaps = {
        "allMids": _compact_gap_intervals([(10, 40), (80, None)]),
        "mystery:unknown": _compact_gap_intervals([(41, 43)]),
    }
    scoped = {
        "l2Book:BTC": _compact_gap_intervals([(5, 18), (45, None)]),
        "trades:BTC": _compact_gap_intervals([(18, 32), (45, 60)]),
        "l2Book:ETH": _compact_gap_intervals([(250, 255)]),
    }
    pipeline = _bare_pipeline(legacy, scoped, global_gaps, set())
    sources = [
        legacy, *global_gaps.values(), scoped["l2Book:BTC"], scoped["trades:BTC"],
    ]
    expected = tuple(_compact_gap_intervals([
        item for source in sources for item in source
    ]))
    got = pipeline.known_gap_intervals_for_market(MarketId("", "BTC"))
    assert got == expected
    assert (250, 255) not in got
    assert (80, None) in got
    assert (100, None) in got
    assert _compact_sorted_gap_sources(sources) == expected
    assert pipeline.known_gap_intervals_for_market(MarketId("", "BTC")) == got


def test_out_of_order_open_gap_uses_historical_full_sort_fallback() -> None:
    legacy = [(4, 12)]
    global_gaps = {"allMids": [(61, None), (13, None)]}
    scoped = {
        "l2Book:BTC": [(30, None), (15, None), (7, 20)],
        "l2Book:ETH": [(1, 3)],
    }
    pipeline = _bare_pipeline(
        legacy, scoped, global_gaps,
        {"allMids", "l2Book:BTC"},
    )
    expected = tuple(_compact_gap_intervals(
        legacy + global_gaps["allMids"] + scoped["l2Book:BTC"]
    ))
    assert pipeline.known_gap_intervals_for_market(MarketId("", "BTC")) == expected
    # Shared data debt remains; the unsorted fallback never silently heals it.
    assert (13, None) in expected
    assert (15, None) in expected
    assert (61, None) in expected
    assert scoped["l2Book:BTC"] == [
        (30, None), (15, None), (7, 20),
    ]


def test_many_sorted_gap_streams_preserve_complete_negative_provenance() -> None:
    legacy = [(1, 3)]
    scoped: dict[str, list[tuple[int, int | None]]] = {}
    global_gaps = {"allMids": _compact_gap_intervals([
        (start, start + 2) for start in range(20, 10_020, 5)
    ])}
    for market in ("BTC", "ETH", "ARB", "SOL", "DOGE", "HYPE"):
        scoped[f"l2Book:{market}"] = _compact_gap_intervals([
            (start + 1, start + 2) for start in range(20, 10_020, 5)
        ])
        scoped[f"trades:{market}"] = _compact_gap_intervals([
            (start + 3, None) for start in range(20, 10_020, 5)
        ])
    pipeline = _bare_pipeline(legacy, scoped, global_gaps, set())
    sources = [
        legacy, *global_gaps.values(),
        scoped["l2Book:BTC"], scoped["trades:BTC"],
    ]
    expected = tuple(_compact_gap_intervals([
        value for group in sources for value in group
    ]))
    assert pipeline.known_gap_intervals_for_market(MarketId("", "BTC")) == expected
    assert pipeline.known_gap_intervals_for_market(MarketId("", "BTC")) == expected
    assert len(expected) > 1_000
