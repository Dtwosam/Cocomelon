from __future__ import annotations

import pytest

from cocomelon.evidence.epochs import DECISION_INTERVAL_MS
from cocomelon.research.capture_timing import (
    RESEARCH_CAPTURE_DECISION_LEAD_MS,
    research_capture_wait_ms,
)


def _evaluation_after_aligned_start(start_ms: int) -> int:
    grace_ms = 30_000
    floor = start_ms // DECISION_INTERVAL_MS * DECISION_INTERVAL_MS
    boundary_ms = floor
    if start_ms > floor + grace_ms:
        boundary_ms += DECISION_INTERVAL_MS
    return boundary_ms + grace_ms


def test_alignment_targets_fixed_clock_phase_before_decision_epoch() -> None:
    assert RESEARCH_CAPTURE_DECISION_LEAD_MS == 180_000

    now_ms = 10 * DECISION_INTERVAL_MS
    wait_ms = research_capture_wait_ms(now_ms)
    start_ms = now_ms + wait_ms
    evaluation_ms = _evaluation_after_aligned_start(start_ms)

    assert evaluation_ms - start_ms == RESEARCH_CAPTURE_DECISION_LEAD_MS
    assert 0 <= wait_ms < DECISION_INTERVAL_MS


def test_alignment_skips_missed_phase_instead_of_starting_late() -> None:
    evaluation_ms = 12 * DECISION_INTERVAL_MS + 30_000
    target_ms = evaluation_ms - RESEARCH_CAPTURE_DECISION_LEAD_MS

    assert research_capture_wait_ms(target_ms) == 0
    assert research_capture_wait_ms(target_ms - 1_000) == 1_000
    assert research_capture_wait_ms(target_ms + 1_000) == DECISION_INTERVAL_MS - 1_000


def test_aligned_decision_remains_inside_existing_five_minute_entry_window() -> None:
    entry_window_ms = 300_000
    for now_ms in (
        0,
        1,
        30_000,
        123_456,
        DECISION_INTERVAL_MS - 1,
        17 * DECISION_INTERVAL_MS + 777_777,
    ):
        start_ms = now_ms + research_capture_wait_ms(now_ms)
        evaluation_ms = _evaluation_after_aligned_start(start_ms)
        assert 0 < evaluation_ms - start_ms < entry_window_ms


def test_alignment_rejects_negative_clock_values() -> None:
    with pytest.raises(ValueError, match="now_ms"):
        research_capture_wait_ms(-1)
