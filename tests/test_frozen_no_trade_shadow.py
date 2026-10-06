from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.frozen_no_trade_shadow import (
    MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1,
    build_frozen_no_trade_shadow_report,
)


def _outcome(
    *,
    timestamp_ms: int,
    value: str,
    market: str = "MON",
    volatility: str = "normal",
    stage: str = "strategy_abstained",
) -> dict[str, object]:
    direction = (
        "short"
        if Decimal(value) < 0
        else "long"
        if Decimal(value) > 0
        else "no_trade"
    )
    return {
        "decision_fact_id": f"fact-{timestamp_ms}-{value}",
        "strategy_decision_id": f"decision-{timestamp_ms}-{value}",
        "market": market,
        "decision_timestamp_ms": timestamp_ms,
        "feature_snapshot_id": f"feature-{timestamp_ms}",
        "feature_as_of_ms": timestamp_ms,
        "horizon_ms": 3_600_000,
        "target_as_of_ms": timestamp_ms + 3_600_000,
        "forward_mark_return": value,
        "favored_direction": direction,
        "reason_codes": ["no_primary_thesis"],
        "decision_stage": stage,
        "trend_regime": "mixed",
        "volatility_regime": volatility,
        "return_15m_sign": "flat",
        "return_1h_sign": "flat",
        "funding_sign": "positive",
        "book_imbalance_sign": "positive",
    }


def _report(outcomes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "decision_state_digest": "a" * 64,
        "feature_state_digest": "b" * 64,
        "diagnostic_only": True,
        "hypothetical_pnl": False,
        "execution_authority": False,
        "schema_version": 2,
        "outcomes": outcomes,
    }


def test_frozen_mon_candidate_binds_exact_touched_lineage() -> None:
    spec = MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1

    assert spec.candidate_id == "mon-normal-volatility-short-1h-50bps-v1"
    assert spec.market == "MON"
    assert spec.volatility_regime == "normal"
    assert spec.direction.value == "short"
    assert spec.horizon_ms == 3_600_000
    assert spec.material_threshold_bps == 50
    assert spec.source_evidence_run_id == 37_466_651_710
    assert spec.source_upstream_run_id == 37_445_353_628
    assert spec.source_max_decision_timestamp_ms == 1_791_283_530_000
    assert spec.validation_not_before_ms == 1_791_305_130_000
    assert spec.validation_not_before_ms - spec.source_max_decision_timestamp_ms == (
        6 * 60 * 60 * 1_000
    )
    assert spec.discovery_material_outcomes == 52
    assert spec.discovery_direction_share == Decimal(
        "0.6153846153846153846153846154"
    )
    assert spec.validation_material_outcomes == 25
    assert spec.validation_direction_share == Decimal("0.76")
    assert spec.validation_block_outcomes == (8, 8, 9)
    assert spec.validation_block_direction_shares == (
        Decimal("0.75"),
        Decimal("0.75"),
        Decimal("0.7777777777777777777777777778"),
    )
    assert spec.source_evidence_class == "touched_development"
    assert spec.prospective_evidence_class == "prospective_shadow"
    assert spec.prospective_only is True
    assert spec.promotion_eligible is False
    assert spec.execution_authority is False
    assert len(spec.spec_id) == 64


def test_frozen_candidate_rejects_cutover_inside_embargo() -> None:
    spec = MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1

    with pytest.raises(ValueError, match="6h prospective embargo"):
        replace(
            spec,
            validation_not_before_ms=spec.source_max_decision_timestamp_ms + 1,
        )


def test_shadow_never_counts_discovery_or_validation_source_rows() -> None:
    spec = MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1
    old = [
        _outcome(
            timestamp_ms=spec.validation_not_before_ms - 1 - index,
            value="-0.02",
        )
        for index in range(20)
    ]

    report = build_frozen_no_trade_shadow_report(_report(old))

    assert report.matching_labeled_outcomes == 0
    assert report.material_outcomes == 0
    assert report.short_material_share is None
    assert report.ready_for_review is False
    assert report.first_matching_decision_timestamp_ms is None


def test_shadow_filters_market_volatility_and_decision_stage() -> None:
    spec = MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1
    t = spec.validation_not_before_ms
    outcomes = [
        _outcome(timestamp_ms=t, value="-0.01"),
        _outcome(timestamp_ms=t + 1, value="-0.01", market="HYPE"),
        _outcome(timestamp_ms=t + 2, value="-0.01", volatility="high"),
        _outcome(
            timestamp_ms=t + 3,
            value="-0.01",
            stage="eligibility_blocked",
        ),
    ]

    report = build_frozen_no_trade_shadow_report(_report(outcomes))

    assert report.matching_labeled_outcomes == 1
    assert report.material_outcomes == 1
    assert report.short_favored_material_outcomes == 1
    assert report.short_material_share == Decimal("1")
    assert report.ready_for_review is False


def test_shadow_requires_material_move_not_every_tiny_price_change() -> None:
    spec = MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1
    t = spec.validation_not_before_ms
    outcomes = [
        _outcome(timestamp_ms=t, value="-0.0049"),
        _outcome(timestamp_ms=t + 1, value="0.0049"),
        _outcome(timestamp_ms=t + 2, value="-0.005"),
    ]

    report = build_frozen_no_trade_shadow_report(_report(outcomes))

    assert report.matching_labeled_outcomes == 3
    assert report.material_outcomes == 1
    assert report.short_favored_material_outcomes == 1
    assert report.long_favored_material_outcomes == 0


def test_shadow_review_needs_enough_rows_and_three_consistent_time_blocks() -> None:
    spec = MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1
    outcomes: list[dict[str, object]] = []
    timestamp = spec.validation_not_before_ms

    for block in range(3):
        for index in range(10):
            outcomes.append(
                _outcome(
                    timestamp_ms=timestamp,
                    value="-0.01" if index < 7 else "0.01",
                )
            )
            timestamp += 1
        timestamp += 1_000

    report = build_frozen_no_trade_shadow_report(_report(outcomes))

    assert report.material_outcomes == 30
    assert report.short_material_share == Decimal("0.7")
    assert report.validation_block_outcomes == (10, 10, 10)
    assert report.validation_block_short_shares == (
        Decimal("0.7"),
        Decimal("0.7"),
        Decimal("0.7"),
    )
    assert report.validation_blocks_meeting_row_floor == 3
    assert report.validation_blocks_directionally_consistent == 3
    assert report.ready_for_review is True


def test_shadow_review_fails_when_one_later_block_flips() -> None:
    spec = MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1
    outcomes: list[dict[str, object]] = []
    timestamp = spec.validation_not_before_ms
    short_counts = (8, 3, 8)

    for short_count in short_counts:
        for index in range(10):
            outcomes.append(
                _outcome(
                    timestamp_ms=timestamp,
                    value="-0.01" if index < short_count else "0.01",
                )
            )
            timestamp += 1
        timestamp += 1_000

    report = build_frozen_no_trade_shadow_report(_report(outcomes))

    assert report.short_material_share == Decimal("0.6333333333333333333333333333")
    assert report.validation_block_short_shares == (
        Decimal("0.8"),
        Decimal("0.3"),
        Decimal("0.8"),
    )
    assert report.validation_blocks_directionally_consistent == 2
    assert report.ready_for_review is False
