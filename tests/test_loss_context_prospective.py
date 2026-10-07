from __future__ import annotations

from decimal import Decimal

from cocomelon.research.loss_context_candidate import (
    build_loss_context_candidate_freeze,
)
from cocomelon.research.loss_context_prospective import (
    build_loss_context_prospective_report,
)
from cocomelon.research.loss_streak_context_audit import (
    LOSS_STREAK_CONTEXT_SCHEMA_VERSION,
)


def _freeze():
    candidate = {
        "dimensions": ("lead_strategy", "trend_regime"),
        "values": ("mean_reversion", "down"),
        "recurring_loss_streaks": 3,
        "discovery_rows": 14,
        "discovery_markets": 5,
        "discovery_loss_share": "0.7",
        "discovery_filter_delta_pnl": "30",
        "validation_rows": 12,
        "validation_markets": 4,
        "validation_loss_share": "0.75",
        "validation_filter_delta_pnl": "20",
        "validation_leave_one_trade_min_delta_pnl": "12",
        "validation_leave_one_market_min_delta_pnl": "6",
        "validation_block_rows": (6, 6),
        "validation_block_loss_shares": ("0.6666666666666666666666666667", "0.8333333333333333333333333333"),
        "validation_block_filter_delta_pnl": ("8", "12"),
        "validation_blocks_consistent": 2,
        "stable_on_validation": True,
        "strategy_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }
    audit = {
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "schema_version": LOSS_STREAK_CONTEXT_SCHEMA_VERSION,
        "trade_count": 40,
        "max_trade_closed_at_ms": 9_000,
        "baseline_normalization_complete": True,
        "context_filter_stability": {
            "schema_version": 1,
            "candidate_count": 1,
            "stable_candidate_count": 1,
            "candidates": [candidate],
            "direction_only_candidates_allowed": False,
            "lead_strategy_context_required": True,
            "entry_time_context_only": True,
            "realized_net_pnl_economics_required": True,
            "chronological_holdout_required": True,
            "leave_one_trade_robustness_required": True,
            "leave_one_market_robustness_required": True,
            "validation_block_consistency_required": True,
            "prospective_freeze_required_before_strategy_use": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "promotion_authority": False,
            "execution_authority": False,
        },
    }
    freeze = build_loss_context_candidate_freeze(
        audit,
        frozen_at_ms=10_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="a" * 40,
    )
    assert freeze is not None
    return freeze


def _row(
    *,
    trade_id: str,
    opened_at_ms: int,
    market: str,
    pnl: str,
    strategy: str = "mean_reversion",
    trend: str = "down",
) -> dict[str, object]:
    return {
        "trade_id": trade_id,
        "market": market,
        "direction": "long",
        "opened_at_ms": opened_at_ms,
        "closed_at_ms": opened_at_ms + 60_000,
        "net_pnl": pnl,
        "lead_strategy": strategy,
        "trend_regime": trend,
        "volatility_regime": "high",
        "return_15m_sign": "negative",
        "return_1h_sign": "negative",
        "funding_sign": "positive",
        "book_imbalance_sign": "negative",
        "rank_band": "top3",
    }


def test_only_post_embargo_exact_context_counts() -> None:
    freeze = _freeze()
    t = freeze.prospective_not_before_ms
    report = build_loss_context_prospective_report(
        (
            _row(
                trade_id="pre",
                opened_at_ms=t - 1,
                market="A",
                pnl="-5",
            ),
            _row(
                trade_id="wrong",
                opened_at_ms=t,
                market="A",
                pnl="-5",
                trend="up",
            ),
            _row(
                trade_id="match",
                opened_at_ms=t + 1,
                market="A",
                pnl="-5",
            ),
        ),
        freeze,
    )

    assert report.matching_outcomes == 1
    assert report.beneficial_outcomes == 1
    assert report.total_filter_delta_pnl == Decimal("5")
    assert report.ready_for_review is False


def test_future_review_requires_robust_multi_market_positive_delta() -> None:
    freeze = _freeze()
    rows: list[dict[str, object]] = []
    timestamp = freeze.prospective_not_before_ms
    markets = ("A", "B", "C", "D")
    for block in range(3):
        for index in range(10):
            rows.append(
                _row(
                    trade_id=f"{block}-{index}",
                    opened_at_ms=timestamp,
                    market=markets[(block * 10 + index) % 4],
                    pnl="-2" if index < 8 else "1",
                )
            )
            timestamp += 1
        timestamp += 1_000

    report = build_loss_context_prospective_report(
        tuple(rows),
        freeze,
    )

    assert report.matching_outcomes == 30
    assert report.matching_markets == 4
    assert report.beneficial_outcomes == 24
    assert report.harmful_outcomes == 6
    assert report.beneficial_share == Decimal("0.8")
    assert report.total_filter_delta_pnl == Decimal("42")
    assert report.leave_one_trade_min_delta_pnl is not None
    assert report.leave_one_trade_min_delta_pnl > 0
    assert report.leave_one_market_min_delta_pnl is not None
    assert report.leave_one_market_min_delta_pnl > 0
    assert report.prospective_block_rows == (10, 10, 10)
    assert report.prospective_block_filter_delta_pnl == (
        Decimal("14"),
        Decimal("14"),
        Decimal("14"),
    )
    assert report.prospective_blocks_consistent == 3
    assert report.ready_for_review is True
    assert report.changes_strategy is False
    assert report.execution_authority is False


def test_future_source_gap_fails_review_closed() -> None:
    freeze = _freeze()
    rows: list[dict[str, object]] = []
    timestamp = freeze.prospective_not_before_ms
    for index in range(30):
        rows.append(
            _row(
                trade_id=str(index),
                opened_at_ms=timestamp + index,
                market=("A", "B", "C", "D")[index % 4],
                pnl="-2",
            )
        )

    report = build_loss_context_prospective_report(
        tuple(rows),
        freeze,
        future_trade_count=31,
        unresolved_reason_counts={"missing feature snapshot": 1},
    )

    assert report.total_filter_delta_pnl == Decimal("60")
    assert report.source_complete is False
    assert report.future_unresolved_trade_count == 1
    assert report.ready_for_review is False


def test_one_market_carry_cannot_be_ready() -> None:
    freeze = _freeze()
    t = freeze.prospective_not_before_ms
    rows = tuple(
        _row(
            trade_id=str(index),
            opened_at_ms=t + index,
            market="ONLY",
            pnl="-2",
        )
        for index in range(30)
    )

    report = build_loss_context_prospective_report(rows, freeze)

    assert report.matching_markets == 1
    assert report.total_filter_delta_pnl == Decimal("60")
    assert report.leave_one_market_min_delta_pnl is None
    assert report.ready_for_review is False
