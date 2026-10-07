from __future__ import annotations

from decimal import Decimal

from cocomelon.research.cooldown_context_candidate import (
    build_cooldown_context_candidate_freeze,
)
from cocomelon.research.cooldown_context_prospective import (
    build_cooldown_context_prospective_report,
)
from cocomelon.research.cooldown_context_selection import (
    build_cooldown_context_selection_record,
)


def _candidate() -> dict[str, object]:
    return {
        "dimensions": (
            "relaxation_window_ms",
            "lead_strategy",
        ),
        "values": ("900000", "trend"),
        "discovery_rows": 10,
        "discovery_markets": 5,
        "discovery_positive_share": "0.7",
        "discovery_total_pnl": "20",
        "discovery_mean_return": "0.003",
        "validation_rows": 8,
        "validation_markets": 4,
        "validation_positive_share": "0.75",
        "validation_total_pnl": "12",
        "validation_mean_return": "0.002",
        "validation_leave_one_option_min_pnl": "7",
        "validation_leave_one_market_min_pnl": "3",
        "validation_block_rows": (4, 4),
        "validation_block_positive_shares": ("0.75", "0.75"),
        "validation_block_pnl": ("5", "7"),
        "validation_blocks_consistent": 2,
        "stable_on_validation": True,
        "strategy_authority": False,
        "risk_authority": False,
        "execution_authority": False,
    }


def _selection() -> dict[str, object]:
    cooldown = {
        "candidate_id": (
            "prospective-consecutive-loss-cooldown-relaxation-v1"
        ),
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "forward_markout_only": True,
        "realized_pnl_modeled": False,
        "relaxed_cooldown_windows_ms": [900_000, 1_800_000],
        "option_results": [
            {"timestamp_ms": 1_000},
            {"timestamp_ms": 2_000},
        ],
    }
    stability = {
        "source_option_count": 18,
        "settled_1h_outcomes": 18,
        "split_timestamp_ms": 2_000,
        "discovery_rows": 10,
        "validation_rows": 8,
        "candidate_count": 1,
        "stable_candidate_count": 1,
        "candidates": [_candidate()],
        "candidate_dimension_sets": (
            ("relaxation_window_ms", "lead_strategy"),
        ),
        "direction_only_candidates_allowed": False,
        "lead_strategy_context_required": True,
        "relaxation_window_context_required": True,
        "window_eligible_outcomes_only": True,
        "one_hour_fee_adjusted_execution_economics_required": True,
        "chronological_holdout_required": True,
        "leave_one_option_robustness_required": True,
        "leave_one_market_robustness_required": True,
        "validation_block_consistency_required": True,
        "research_only": True,
        "descriptive_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "promotion_authority": False,
        "execution_authority": False,
        "schema_version": 2,
    }
    return build_cooldown_context_selection_record(
        cooldown,
        stability,
    ).to_dict()


def _freeze():
    return build_cooldown_context_candidate_freeze(
        _selection(),
        frozen_at_ms=10_000,
        source_paper_run_id=1,
        source_paper_run_attempt=1,
        source_paper_head_sha="a" * 40,
    )


def _option(
    *,
    timestamp_ms: int,
    market: str,
    pnl: str,
    lead_strategy: str = "trend",
    windows: tuple[int, ...] = (900_000,),
) -> dict[str, object]:
    direction_return = "0.01" if Decimal(pnl) > 0 else "-0.01"
    return {
        "timestamp_ms": timestamp_ms,
        "market": market,
        "direction": "short",
        "lead_strategy": lead_strategy,
        "elapsed_bucket": "early",
        "rank_ordinal": 2,
        "applicable_relaxed_windows_ms": list(windows),
        "markouts": {
            "3600000": {
                "status": "settled",
                "entry_fee_adjusted_mark_to_market_pnl": pnl,
                "directional_return_fraction": direction_return,
            }
        },
    }


def _summary(options: list[dict[str, object]]) -> dict[str, object]:
    return {
        "candidate_id": (
            "prospective-consecutive-loss-cooldown-relaxation-v1"
        ),
        "research_only": True,
        "descriptive_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_risk_limits": False,
        "forward_markout_only": True,
        "realized_pnl_modeled": False,
        "relaxed_cooldown_windows_ms": [900_000, 1_800_000],
        "option_results": options,
    }


def test_pre_embargo_and_wrong_context_rows_never_count() -> None:
    freeze = _freeze()
    t = freeze.prospective_not_before_ms
    report = build_cooldown_context_prospective_report(
        _summary(
            [
                _option(
                    timestamp_ms=t - 1,
                    market="A",
                    pnl="10",
                ),
                _option(
                    timestamp_ms=t,
                    market="A",
                    pnl="10",
                    lead_strategy="breakout",
                ),
                _option(
                    timestamp_ms=t + 1,
                    market="A",
                    pnl="10",
                    windows=(1_800_000,),
                ),
                _option(
                    timestamp_ms=t + 2,
                    market="A",
                    pnl="10",
                ),
            ]
        ),
        freeze,
    )

    assert report.matching_outcomes == 1
    assert report.profitable_outcomes == 1
    assert report.total_fee_adjusted_pnl == Decimal("10")
    assert report.ready_for_review is False


def test_future_review_requires_robust_positive_economics_and_blocks() -> None:
    freeze = _freeze()
    options: list[dict[str, object]] = []
    timestamp = freeze.prospective_not_before_ms
    markets = ("A", "B", "C", "D")

    for block in range(3):
        for index in range(10):
            options.append(
                _option(
                    timestamp_ms=timestamp,
                    market=markets[(block * 10 + index) % len(markets)],
                    pnl="2" if index < 8 else "-1",
                )
            )
            timestamp += 1
        timestamp += 1_000

    report = build_cooldown_context_prospective_report(
        _summary(options),
        freeze,
    )

    assert report.matching_outcomes == 30
    assert report.matching_markets == 4
    assert report.profitable_outcomes == 24
    assert report.positive_share == Decimal("0.8")
    assert report.total_fee_adjusted_pnl == Decimal("42")
    assert report.leave_one_option_min_pnl is not None
    assert report.leave_one_option_min_pnl > 0
    assert report.leave_one_market_min_pnl is not None
    assert report.leave_one_market_min_pnl > 0
    assert report.prospective_block_rows == (10, 10, 10)
    assert report.prospective_block_positive_shares == (
        Decimal("0.8"),
        Decimal("0.8"),
        Decimal("0.8"),
    )
    assert report.prospective_block_pnl == (
        Decimal("14"),
        Decimal("14"),
        Decimal("14"),
    )
    assert report.prospective_blocks_consistent == 3
    assert report.ready_for_review is True


def test_one_bad_future_block_keeps_candidate_unready() -> None:
    freeze = _freeze()
    options: list[dict[str, object]] = []
    timestamp = freeze.prospective_not_before_ms
    markets = ("A", "B", "C", "D")
    positive_counts = (8, 3, 8)

    for block, positive_count in enumerate(positive_counts):
        for index in range(10):
            options.append(
                _option(
                    timestamp_ms=timestamp,
                    market=markets[(block * 10 + index) % len(markets)],
                    pnl="2" if index < positive_count else "-1",
                )
            )
            timestamp += 1
        timestamp += 1_000

    report = build_cooldown_context_prospective_report(
        _summary(options),
        freeze,
    )

    assert report.positive_share == Decimal(
        "0.6333333333333333333333333333"
    )
    assert report.total_fee_adjusted_pnl > 0
    assert report.prospective_block_positive_shares == (
        Decimal("0.8"),
        Decimal("0.3"),
        Decimal("0.8"),
    )
    assert report.prospective_block_pnl == (
        Decimal("14"),
        Decimal("-1"),
        Decimal("14"),
    )
    assert report.prospective_blocks_consistent == 2
    assert report.ready_for_review is False


def test_review_gate_never_changes_risk_or_execution_authority() -> None:
    payload = build_cooldown_context_prospective_report(
        _summary([]),
        _freeze(),
    ).to_dict()

    assert payload["prospective_only"] is True
    assert payload["paper_only"] is True
    assert payload["research_only"] is True
    assert payload["changes_strategy"] is False
    assert payload["changes_risk_limits"] is False
    assert payload["promotion_authority"] is False
    assert payload["execution_authority"] is False
