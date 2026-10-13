"""A favorable signed v2 paper sample is NOT an authenticated venue edge."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FORWARD_NOT_BEFORE_MS_V2,
)
from scripts import audit_fresh_trend_v2_forward_outcome as outcome
from scripts.audit_both_side_trend_paired_handoff import (
    TrendPairHandoffAuditError,
)

ANCHOR = FORWARD_NOT_BEFORE_MS_V2
DURATION = 72 * 60 * 60 * 1000


def _cohort(*, longs: int = 8, shorts: int = 8, factor: str = "3") -> dict[str, object]:
    return {
        "anchor_end_ms": ANCHOR,
        "window": "exits_strictly_after_first_eligible_signed_checkpoint",
        "all": {
            "closed_trades": longs + shorts,
            "profit_factor": factor,
            "wins_after_costs": 10,
            "losses_after_costs": 6,
            "gross_positive_net_pnl": "60",
            "absolute_gross_negative_net_pnl": "20",
            "net_expectancy_per_closed_trade": "2.5",
            "net_pnl_after_costs": "40",
        },
        "long": {"closed_trades": longs},
        "short": {"closed_trades": shorts},
    }


def _inputs(
    *, duration: int = DURATION, candidate_gain: str = "30",
    first_gap: tuple[int, int | None] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object],
           dict[str, object], tuple[dict[str, object], ...]]:
    source: dict[str, object] = {
        "status": "archive_checkpoint_lineage_verified",
        "source_run_id": 40002,
        "source_run_attempt": 1,
        "v2_write_once_genesis_verified": True,
        "source_v2_terminal_receipt_verified": True,
        "archived_execution_economics_reconciled": True,
        "v2_actor_received_gap_record_chain_verified": True,
        "witnessed_forward_gap_event_count": 0,
        "source_worker_completed": True,
        "source_class": "completed_expected_upgrade_handoff_worker",
        "reconciled_lanes": {
            "baseline": {"forward_closed_trade_cohort": _cohort()},
            "candidate": {"forward_closed_trade_cohort": _cohort()},
        },
    }
    lineage: dict[str, object] = {
        "status": "v2_selected_anchor_worker_append_verified",
        "first_archived_v2_worker_proven": True,
        "identical_write_once_genesis_across_workers": True,
        "v2_actor_gap_witness_prefix_verified": True,
        "new_signed_checkpoint_append_verified": True,
        "current_run_id": 40002,
        "current_attempt": 1,
        "successor_row_count": 9,
        "successor_last_row_digest": "digest-8",
        "successor_end_ms": ANCHOR + duration,
        "successor_record_count": 90,
    }
    review: dict[str, object] = {
        "ready_for_review": True,
        "readiness_failures": (),
        "eligible_checkpoint_count": 9,
        "review_anchor_end_ms": ANCHOR,
        "future_duration_ms": duration,
        "candidate_total_account_pnl": candidate_gain,
        "candidate_minus_baseline_total_account_pnl": str(
            Decimal(candidate_gain) - Decimal(10)
        ),
        "forward_closed_trade_economics_by_direction": {
            lane: {
                "long_closed_trades": 8,
                "short_closed_trades": 8,
                "total_forward_closed_trades": 16,
            } for lane in ("baseline", "candidate")
        },
    }
    intervals = [] if first_gap is None else [list(first_gap)]
    lane_state = {
        "legacy_unscoped_gap_intervals": [],
        "known_gap_intervals_by_stream": {"BTC:book": intervals},
        "known_global_gap_intervals_by_stream": {},
    }
    state: dict[str, object] = {
        "historical_gap_scope_tainted": False,
        "baseline": lane_state,
        "candidate": lane_state,
    }
    rows: list[dict[str, object]] = []
    for index in range(9):
        end = ANCHOR + (duration * index // 8)
        baseline_pnl = "10" if index else "0"
        candidate_pnl = candidate_gain if index else "0"
        rows.append({
            "end_ms": end,
            "row_digest": f"digest-{index}",
            "record_count": (index + 1) * 10,
            "last_record_available_at_ms": end,
            "baseline": {
                "total_account_pnl": baseline_pnl,
                "max_drawdown_fraction": "0.02",
            },
            "candidate": {
                "total_account_pnl": candidate_pnl,
                "max_drawdown_fraction": "0.01",
            },
        })
    return source, lineage, review, state, tuple(rows)


def _evaluate(
    *, duration: int = DURATION, candidate_gain: str = "30",
    first_gap: tuple[int, int | None] | None = None,
) -> dict[str, object]:
    src, lin, rev, state, rows = _inputs(
        duration=duration, candidate_gain=candidate_gain,
        first_gap=first_gap,
    )
    return outcome._economics(
        source=src, lineage=lin, review=rev,
        signed_state=state, rows=rows,
    )


def test_only_positive_after_cost_full_72h_signed_window_gets_screen() -> None:
    r = _evaluate()
    assert r["status"] == (
        "signed_paper_account_positive_screen_not_venue_certified"
    )
    assert r["signed_72h_window_complete"] is True
    assert r["positive_signed_source_account_screen"] is True
    assert r["primary_candidate_minus_baseline_after_cost_marked_pnl"] == "20"
    assert r["candidate_after_cost_marked_pnl"] == "30"
    assert r["baseline_after_cost_marked_pnl"] == "10"
    assert r["candidate_fill_matched_trades"]["closed_trades"] == 16
    assert r["candidate_fill_matched_trades"]["after_cost_profit_factor"] == "3"
    assert r["candidate_fill_matched_trades"][
        "after_cost_net_expectancy_per_closed_trade"
    ] == "2.5"
    assert r["original_exchange_event_source_authenticated"] is False
    assert r["venue_mark_prices_authenticated"] is False
    assert r["live_execution_authority"] is False
    assert r["promotion_authority"] is False
    assert "independent_mainnet_tick_and_mark_source_not_authenticated" in r["reasons"]


@pytest.mark.parametrize("duration", [0, DURATION - 1, 48 * 60 * 60 * 1000])
def test_pre72h_window_never_gets_positive_screen(duration: int) -> None:
    r = _evaluate(duration=duration)
    assert r["signed_72h_window_complete"] is False
    assert r["positive_signed_source_account_screen"] is False
    assert "insufficient_72h_forward_signed_duration" in r["reasons"]


@pytest.mark.parametrize("candidate_gain", ["-1", "0", "9", "10"])
def test_candidate_must_be_positive_and_ahead_after_costs(
    candidate_gain: str,
) -> None:
    r = _evaluate(candidate_gain=candidate_gain)
    assert r["positive_signed_source_account_screen"] is False
    assert "candidate_not_positive_and_ahead_after_costs" in r["reasons"]


@pytest.mark.parametrize("gap", [
    (ANCHOR, None),
    (ANCHOR + 1000, ANCHOR + 2000),
    (ANCHOR - 50, ANCHOR + 50),
])
def test_recorded_closed_or_open_forward_source_gap_blocks_screen(
    gap: tuple[int, int | None],
) -> None:
    r = _evaluate(first_gap=gap)
    assert r["positive_signed_source_account_screen"] is False
    assert "recorded_market_feed_gaps_or_unresolved_sources" in r["reasons"]
    assert r["named_market_source_gap_history"][
        "no_recorded_forward_gaps"
    ] is False


def test_missing_original_worker_evidence_blocks_screen() -> None:
    source, lineage, review, state, rows = _inputs()
    lineage["first_archived_v2_worker_proven"] = False
    result = outcome._economics(
        source=source, lineage=lineage, review=review,
        signed_state=state, rows=rows,
    )
    assert result["positive_signed_source_account_screen"] is False
    assert "original_worker_and_forward_source_lineage_not_authenticated" in result["reasons"]


def test_unsigned_abstention_does_not_rewrite_signed_report() -> None:
    source, lineage, review, state, rows = _inputs()
    review["candidate_minus_baseline_total_account_pnl"] = "9999"
    with pytest.raises(TrendPairHandoffAuditError, match="differs from review"):
        outcome._economics(
            source=source, lineage=lineage, review=review,
            signed_state=state, rows=rows,
        )


def test_missing_trade_lineage_or_changed_profit_factor_is_rejected() -> None:
    source, lineage, review, state, rows = _inputs()
    cohort = source["reconciled_lanes"]["candidate"]["forward_closed_trade_cohort"]
    cohort["long"]["closed_trades"] = 7
    with pytest.raises(TrendPairHandoffAuditError, match="directional"):
        outcome._economics(
            source=source, lineage=lineage, review=review,
            signed_state=state, rows=rows,
        )
    cohort["long"]["closed_trades"] = 8
    cohort["all"]["profit_factor"] = "20"
    with pytest.raises(TrendPairHandoffAuditError, match="profit factor arithmetic"):
        outcome._economics(
            source=source, lineage=lineage, review=review,
            signed_state=state, rows=rows,
        )


def test_missing_or_tainted_v2_gap_history_blocks_economics() -> None:
    source, lineage, review, state, rows = _inputs()
    state["historical_gap_scope_tainted"] = True
    with pytest.raises(TrendPairHandoffAuditError, match="missing or tainted"):
        outcome._economics(
            source=source, lineage=lineage, review=review,
            signed_state=state, rows=rows,
        )


def test_empty_eligible_window_remains_unverified() -> None:
    source, lineage, review, state, rows = _inputs()
    review["eligible_checkpoint_count"] = 0
    result = outcome._economics(
        source=source, lineage=lineage, review=review,
        signed_state=state, rows=(),
    )
    assert result["status"] == "unverified"
    assert result["positive_signed_source_account_screen"] is False


def test_new_workflow_only_writes_unpromotable_diagnostic() -> None:
    from pathlib import Path

    w = Path(
        ".github/workflows/independent-fresh-trend-v2-source-audit.yml"
    ).read_text(encoding="utf-8")
    assert "scripts.audit_fresh_trend_v2_forward_outcome" in w
    assert "fresh-trend-v2-forward-economics.json" in w
    assert "verified 72h after-cost PROFITABLE edge: FALSE" in w
    assert "original venue stream independently authenticated: FALSE" in w
    assert "HYPERLIQUID_PRIVATE_KEY" not in w
    assert "COCOMELON_EXECUTION_MODE: live" not in w


def test_72_hour_checkpoint_time_without_new_source_records_never_qualifies() -> None:
    source, lineage, review, state, rows = _inputs()
    advanced = list(rows)
    # The last checkpoint copied the previous event count and timestamp,
    # even though its unsigned clock advanced to the 72h evaluation edge.
    advanced[-1] = {
        **advanced[-1],
        "record_count": advanced[-2]["record_count"],
        "last_record_available_at_ms": advanced[-2]["last_record_available_at_ms"],
    }
    lineage["successor_record_count"] = advanced[-1]["record_count"]
    result = outcome._economics(
        source=source, lineage=lineage, review=review,
        signed_state=state, rows=tuple(advanced),
    )
    assert result["signed_72h_window_complete"] is True
    assert result["signed_new_records_at_every_eligible_checkpoint"] is False
    assert result["positive_signed_source_account_screen"] is False
    assert "signed_market_record_progress_stalled_or_unverifiable" in result["reasons"]


def test_original_received_v2_data_gap_event_vetoes_closed_gap_paper_edge() -> None:
    source, lineage, review, state, rows = _inputs()
    source["witnessed_forward_gap_event_count"] = 1
    result = outcome._economics(
        source=source, lineage=lineage, review=review,
        signed_state=state, rows=rows,
    )
    assert result["positive_signed_source_account_screen"] is False
    assert "original_actor_received_forward_market_gap_event" in result["reasons"]
    assert result["original_exchange_event_source_authenticated"] is False


def test_missing_original_received_v2_gap_event_witness_vetoes_paper_edge() -> None:
    source, lineage, review, state, rows = _inputs()
    source["v2_actor_received_gap_record_chain_verified"] = False
    result = outcome._economics(
        source=source, lineage=lineage, review=review,
        signed_state=state, rows=rows,
    )
    assert result["positive_signed_source_account_screen"] is False
    assert "original_actor_gap_event_witness_not_authenticated" in result["reasons"]


def test_missing_cross_worker_original_gap_witness_prefix_vetoes_positive_paper_edge(
) -> None:
    source, lineage, review, state, rows = _inputs()
    lineage["v2_actor_gap_witness_prefix_verified"] = False
    receipt = outcome._economics(
        source=source, lineage=lineage,
        review=review, signed_state=state, rows=rows,
    )
    assert receipt["positive_signed_source_account_screen"] is False
    assert (
        "original_worker_and_forward_source_lineage_not_authenticated"
        in receipt["reasons"]
    )
    assert receipt["original_exchange_event_source_authenticated"] is False
    assert receipt["promotion_authority"] is False
