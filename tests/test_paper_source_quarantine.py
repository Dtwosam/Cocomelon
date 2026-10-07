from __future__ import annotations

import pytest

from cocomelon.research.paper_source_quarantine import (
    PAPER_SOURCE_QUARANTINE,
    assert_paper_source_not_quarantined,
    is_paper_source_quarantined,
    paper_source_quarantine_entry,
)


def test_known_duplicate_trader_runs_are_quarantined() -> None:
    expected = {
        37_605_830_245,
        37_607_372_643,
        37_610_648_495,
        37_610_718_254,
    }

    assert {item.run_id for item in PAPER_SOURCE_QUARANTINE} == expected
    for run_id in expected:
        entry = paper_source_quarantine_entry(run_id)
        assert entry is not None
        assert entry.incident_id == "duplicate-paper-trader-overlap-2026-10-07"
        assert "overlapped another active trader" in entry.reason
        assert is_paper_source_quarantined(run_id) is True


def test_clean_run_is_not_quarantined() -> None:
    assert paper_source_quarantine_entry(37_604_965_812) is None
    assert is_paper_source_quarantined(37_604_965_812) is False
    assert_paper_source_not_quarantined(37_604_965_812)


def test_quarantined_run_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="PAPER_SOURCE_QUARANTINED"):
        assert_paper_source_not_quarantined(37_605_830_245)


@pytest.mark.parametrize("run_id", [0, -1, True])
def test_invalid_run_identity_is_rejected(run_id: int) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        paper_source_quarantine_entry(run_id)
