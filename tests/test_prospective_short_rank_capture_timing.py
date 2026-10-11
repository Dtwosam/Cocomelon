from __future__ import annotations

from dataclasses import replace

import pytest

from cocomelon.research.prospective_short_rank_capture_timing import (
    RankCaptureTimingError,
    rank_capture_timing_census,
)
from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    VerifiedGithubShortRankEvidence,
)


def _snapshot(observed_at_ms: int) -> FirstSeenRankSnapshot:
    return FirstSeenRankSnapshot(
        observed_at_ms=observed_at_ms,
        captured_at_ms=observed_at_ms + 100,
        features=(),
        ranks=(),
    )


def test_long_rank_source_intervals_are_reported_without_claiming_market_gaps() -> None:
    snaps = tuple(_snapshot(when) for when in (
        1_000, 31_000, 101_000, 401_000, 802_000,
    ))
    payload = rank_capture_timing_census(snaps)
    assert payload["rank_capture_snapshot_count"] == 5
    assert payload["rank_capture_interval_count"] == 4
    assert payload["rank_capture_min_interval_ms"] == 30_000
    assert payload["rank_capture_median_low_interval_ms"] == 70_000
    assert payload["rank_capture_max_interval_ms"] == 401_000
    assert payload["rank_capture_over_60s_interval_count"] == 3
    assert payload["rank_capture_over_300s_interval_count"] == 1
    assert payload["rank_capture_excess_over_60s_total_ms"] == 591_000
    detail = payload["longest_rank_capture_intervals"]
    assert isinstance(detail, list)
    assert [item["duration_ms"] for item in detail] == [
        401_000, 300_000, 70_000,
    ]
    assert payload["additional_long_intervals_not_in_detail"] == 0
    assert payload["interval_60s_threshold_is_diagnostic_only"] is True
    assert payload["rank_witness_frozen_300s_age_rule_unchanged"] is True
    assert payload["original_mainnet_source_gap_coverage_certified"] is False
    assert payload["entire_forward_rank_capture_continuity_certified"] is False
    assert payload["ready_for_review"] is False
    assert payload["promotion_authority"] is False


def test_very_short_or_singleton_rank_capture_source_does_not_infer_missing_data(
) -> None:
    row = _snapshot(1000)
    single = rank_capture_timing_census((row,))
    assert single["rank_capture_interval_count"] == 0
    assert single["rank_capture_over_60s_interval_count"] == 0
    assert single["rank_capture_max_interval_ms"] == 0
    assert single["longest_rank_capture_intervals"] == []
    with pytest.raises(RankCaptureTimingError, match="empty"):
        rank_capture_timing_census(())


def test_backdated_rank_source_rejected_without_salvaging_late_winners() -> None:
    with pytest.raises(RankCaptureTimingError, match="progression"):
        rank_capture_timing_census((_snapshot(3000), _snapshot(2000)))
    with pytest.raises(RankCaptureTimingError, match="progression"):
        rank_capture_timing_census((_snapshot(3000), _snapshot(3000)))


def test_complete_large_census_reports_total_even_if_details_are_capped() -> None:
    rows = tuple(
        _snapshot(1000 + 70_000 * number)
        for number in range(135)
    )
    census = rank_capture_timing_census(rows)
    assert census["rank_capture_over_60s_interval_count"] == 134
    assert census["additional_long_intervals_not_in_detail"] == 6
    detail = census["longest_rank_capture_intervals"]
    assert isinstance(detail, list)
    assert len(detail) == 128
    assert census["rank_capture_excess_over_60s_total_ms"] == 1_340_000


def test_worker_rank_receipt_includes_conservative_census_without_authority() -> None:
    first = _snapshot(1000)
    second = _snapshot(80_000)
    worker = VerifiedGithubShortRankEvidence(
        snapshots=(first, second),
        rank_state_digest="a" * 64,
        archive_sha256="b" * 64,
        worker_run_id=38162541394,
        worker_head_sha="c" * 40,
        worker_run_attempt=1,
    )
    receipt = worker.receipt()
    assert receipt["rank_capture_over_60s_interval_count"] == 1
    assert receipt["rank_capture_max_interval_ms"] == 79_000
    assert receipt["github_outer_artifact_sha256_reconciled"] is True
    assert receipt["rank_features_bound_to_exact_mainnet_source"] is False
    assert receipt["execution_authority"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["terminal_account_profitability_certified"] is False
    newer = replace(worker, snapshots=(first,))
    assert newer.receipt()["rank_capture_over_60s_interval_count"] == 0
