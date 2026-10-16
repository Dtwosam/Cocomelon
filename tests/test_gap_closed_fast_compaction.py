"""Source gap fast path is EXACTLY the old compactor, never gap healing.

The test uses an independent replica of the historical update algorithm to
compare every in-memory state, including temporarily unsorted OPEN gaps.
"""
from __future__ import annotations

from random import Random

import cocomelon.evidence.lifecycle as lifecycle
from cocomelon.evidence.lifecycle import (
    _compact_gap_intervals,
    _record_gap_interval,
)


def _historical_update(
    intervals: list[tuple[int, int | None]],
    start: int,
    end: int | None,
) -> None:
    pair = (start, end)
    if end is None:
        if pair not in intervals:
            intervals.append(pair)
        return
    open_pair = (start, None)
    if open_pair in intervals:
        intervals[intervals.index(open_pair)] = pair
    elif pair not in intervals:
        intervals.append(pair)
    intervals[:] = _compact_gap_intervals(intervals)


def test_new_gap_fast_update_matches_historical_gaps_after_each_event() -> None:
    rng = Random(87326)
    for _case in range(60):
        before: list[tuple[int, int | None]] = []
        after: list[tuple[int, int | None]] = []
        sorted_so_far = True
        previously_open: list[int] = []
        time_ms = 1_792_150_000_000
        for _step in range(500):
            time_ms += rng.randrange(0, 3)
            mode = rng.randrange(10)
            if mode < 4:
                start, end = time_ms, None
                previously_open.append(start)
            elif mode < 7 and previously_open:
                start = rng.choice(previously_open)
                end = start + rng.randrange(0, 250)
            elif mode == 7:
                start = time_ms - rng.randrange(0, 1_000)
                end = start + rng.randrange(0, 200)
            else:
                start = time_ms
                end = time_ms + rng.randrange(0, 200)
            _historical_update(before, start, end)
            sorted_so_far = _record_gap_interval(
                after,
                started_ms=start,
                ended_ms=end,
                sorted_so_far=sorted_so_far,
            )
            assert after == before
            if sorted_so_far:
                assert after == sorted(
                    after,
                    key=lambda item: (
                        item[0], item[1] is None,
                        -1 if item[1] is None else item[1],
                    ),
                )


def test_chronological_close_with_large_history_does_not_recompact(
    monkeypatch,
) -> None:
    intervals: list[tuple[int, int | None]] = [
        (index * 100, index * 100 + 20)
        for index in range(250_000)
    ]
    def forbidden_compaction(_intervals: object) -> None:
        raise AssertionError("chronological closed gap scanned all history")

    monkeypatch.setattr(lifecycle, "_compact_gap_intervals", forbidden_compaction)
    start = 25_000_100
    assert _record_gap_interval(
        intervals, started_ms=start, ended_ms=start+50,
        sorted_so_far=True,
    )
    assert len(intervals) == 250_001
    assert intervals[-1] == (start, start+50)
    assert _record_gap_interval(
        intervals, started_ms=start+40, ended_ms=start+70,
        sorted_so_far=True,
    )
    assert len(intervals) == 250_001
    assert intervals[-1] == (start, start+70)


def test_open_tail_close_merges_or_preserves_exact_last_coverage(
    monkeypatch,
) -> None:
    def forbidden_compaction(_intervals: object) -> None:
        raise AssertionError("closing latest named gap rescanned all history")
    monkeypatch.setattr(lifecycle, "_compact_gap_intervals", forbidden_compaction)
    for end, expected in [
        (250, [(100, 250)]),
        (195, [(100, 200)]),
    ]:
        state: list[tuple[int, int | None]] = [(100, 200), (190, None)]
        assert _record_gap_interval(
            state, started_ms=190, ended_ms=end, sorted_so_far=True
        )
        assert state == expected


def test_out_of_order_open_stays_uncompacted_until_next_close() -> None:
    intervals: list[tuple[int, int | None]] = [(100, 200)]
    assert not _record_gap_interval(
        intervals, started_ms=80, ended_ms=None, sorted_so_far=True,
    )
    assert intervals == [(100, 200), (80, None)]
    assert _record_gap_interval(
        intervals, started_ms=80, ended_ms=180, sorted_so_far=False,
    )
    assert intervals == [(80, 200)]


def test_close_an_earlier_open_gap_keeps_independent_later_open() -> None:
    intervals: list[tuple[int, int | None]] = [
        (100, 150), (200, None), (300, None)
    ]
    assert _record_gap_interval(
        intervals, started_ms=200, ended_ms=350, sorted_so_far=True
    )
    assert intervals == [(100, 150), (200, 350), (300, None)]
    # The later open is still unverified; it must not be silently healed.


def test_chronological_open_with_large_history_skips_full_membership_scan() -> None:
    class NoMembershipScan(list[tuple[int, int | None]]):
        def __contains__(self, item: object) -> bool:
            raise AssertionError(
                "chronological fresh OPEN gap performed O(history) membership scan"
            )

    intervals = NoMembershipScan(
        (index * 100, index * 100 + 20)
        for index in range(250_000)
    )
    start = 25_000_100
    assert _record_gap_interval(
        intervals, started_ms=start, ended_ms=None, sorted_so_far=True,
    )
    assert len(intervals) == 250_001
    assert intervals[-1] == (start, None)


def test_open_duplicate_and_out_of_order_still_match_old_gap_membership() -> None:
    history: list[tuple[int, int | None]] = [
        (100, 150), (200, None), (300, None)
    ]
    actual = list(history)
    original = list(history)
    chronological = True
    for start in (300, 200, 250, 250, 350, 300, 400):
        _historical_update(original, start, None)
        chronological = _record_gap_interval(
            actual, started_ms=start, ended_ms=None,
            sorted_so_far=chronological,
        )
        assert actual == original
    assert chronological is False
    _historical_update(original, 200, 360)
    chronological = _record_gap_interval(
        actual, started_ms=200, ended_ms=360,
        sorted_so_far=chronological,
    )
    assert chronological is True
    assert actual == original
