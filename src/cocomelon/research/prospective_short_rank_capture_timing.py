"""Measure observed first-seen SHORT rank capture intervals without guessing gaps.

The completed-worker source can contain long intervals when the original
paper trader is handing off. Rank-source timing is a *diagnostic*, not proof
of missing exchange data, a market-data gap or a profitable filtered trade.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median_low
from typing import Final

from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)

SHORT_INTERVAL_DIAGNOSTIC_MS: Final = 60_000
RANK_WITNESS_MAX_AGE_MS: Final = 300_000
MAX_PUBLISHED_INTERVAL_DETAILS: Final = 128


class RankCaptureTimingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RankCaptureLongInterval:
    after_capture_ms: int
    next_capture_ms: int
    duration_ms: int

    def __post_init__(self) -> None:
        if (
            type(self.after_capture_ms) is not int
            or type(self.next_capture_ms) is not int
            or type(self.duration_ms) is not int
            or self.after_capture_ms < 0
            or self.next_capture_ms <= self.after_capture_ms
            or self.duration_ms != self.next_capture_ms - self.after_capture_ms
        ):
            raise RankCaptureTimingError("invalid rank capture interval")

    def to_dict(self) -> dict[str, int]:
        return {
            "after_capture_ms": self.after_capture_ms,
            "next_capture_ms": self.next_capture_ms,
            "duration_ms": self.duration_ms,
        }


def rank_capture_timing_census(
    snapshots: Sequence[FirstSeenRankSnapshot],
) -> dict[str, object]:
    """Immutable full-source capture timing, never fill or infer missing rows.

    The 60-second threshold is an observability diagnostic only. The frozen
    SHORT rule's existing 300-second rank age is NOT changed here.
    """
    if not snapshots:
        raise RankCaptureTimingError("rank capture source is empty")
    previous = snapshots[0]
    if (
        previous.observed_at_ms < 0
        or previous.captured_at_ms < previous.observed_at_ms
    ):
        raise RankCaptureTimingError("invalid first rank capture timestamp")
    intervals: list[int] = []
    long_intervals: list[RankCaptureLongInterval] = []
    for newer in snapshots[1:]:
        if (
            newer.observed_at_ms <= previous.observed_at_ms
            or newer.captured_at_ms < previous.captured_at_ms
            or newer.captured_at_ms < newer.observed_at_ms
        ):
            raise RankCaptureTimingError(
                "noncanonical rank capture timestamp progression"
            )
        delta = newer.captured_at_ms - previous.captured_at_ms
        intervals.append(delta)
        if delta > SHORT_INTERVAL_DIAGNOSTIC_MS:
            long_intervals.append(RankCaptureLongInterval(
                previous.captured_at_ms, newer.captured_at_ms, delta,
            ))
        previous = newer
    selected = sorted(
        long_intervals,
        key=lambda interval: (-interval.duration_ms, interval.after_capture_ms),
    )[:MAX_PUBLISHED_INTERVAL_DETAILS]
    return {
        "rank_capture_snapshot_count": len(snapshots),
        "rank_capture_interval_count": len(intervals),
        "rank_capture_first_ms": snapshots[0].captured_at_ms,
        "rank_capture_last_ms": snapshots[-1].captured_at_ms,
        "rank_capture_observed_span_ms": (
            snapshots[-1].captured_at_ms - snapshots[0].captured_at_ms
        ),
        "rank_capture_min_interval_ms": min(intervals, default=0),
        "rank_capture_median_low_interval_ms": (
            median_low(intervals) if intervals else 0
        ),
        "rank_capture_max_interval_ms": max(intervals, default=0),
        "rank_capture_over_60s_interval_count": len(long_intervals),
        "rank_capture_over_300s_interval_count": sum(
            interval > RANK_WITNESS_MAX_AGE_MS
            for interval in intervals
        ),
        "rank_capture_excess_over_60s_total_ms": sum(
            max(0, interval - SHORT_INTERVAL_DIAGNOSTIC_MS)
            for interval in intervals
        ),
        "longest_rank_capture_intervals": [
            interval.to_dict() for interval in selected
        ],
        "additional_long_intervals_not_in_detail": (
            len(long_intervals) - len(selected)
        ),
        "interval_60s_threshold_is_diagnostic_only": True,
        "rank_witness_frozen_300s_age_rule_unchanged": True,
        "original_mainnet_source_gap_coverage_certified": False,
        "market_rank_feature_lineage_certified": False,
        "entire_forward_rank_capture_continuity_certified": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "execution_authority": False,
        "promotion_authority": False,
        "research_only": True,
    }
