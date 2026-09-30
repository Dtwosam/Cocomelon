from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceDecision,
    ShadowCadenceOutcome,
)
from cocomelon.research.cadence_trade_quality_calibration import (
    CadenceTradeQualityCalibrationError,
    cadence_trade_quality_calibration,
)

MARKET = MarketId("", "BTC")


def _pair(
    index: int,
    *,
    direction: Direction,
    strategy: str,
    score: str,
    net_15m: str,
    net_1h: str,
) -> tuple[ShadowCadenceOutcome, ShadowCadenceOutcome]:
    boundary = index * FIFTEEN_MINUTES_MS
    common = {
        "cadence_ms": FIFTEEN_MINUTES_MS,
        "boundary_ms": boundary,
        "evaluated_at_ms": boundary + 30_000,
        "market": MARKET,
        "direction": direction,
        "score": Decimal(score),
        "lead_strategy": strategy,
        "decision_id": f"decision-{index}",
        "feature_snapshot_id": f"feature-{index}",
        "entry_px": Decimal("100"),
        "off_primary_boundary": False,
    }
    short_sample = ShadowCadenceDecision(
        **common,
        horizon_ms=FIFTEEN_MINUTES_MS,
        target_end_ms=boundary + FIFTEEN_MINUTES_MS,
        cost_fraction=Decimal("0"),
    )
    long_sample = ShadowCadenceDecision(
        **common,
        horizon_ms=ONE_HOUR_MS,
        target_end_ms=boundary + ONE_HOUR_MS,
        cost_fraction=Decimal("0"),
    )
    return (
        ShadowCadenceOutcome(
            sample=short_sample,
            exit_px=Decimal("100"),
            gross_return=Decimal(net_15m),
            net_return=Decimal(net_15m),
        ),
        ShadowCadenceOutcome(
            sample=long_sample,
            exit_px=Decimal("100"),
            gross_return=Decimal(net_1h),
            net_return=Decimal(net_1h),
        ),
    )


def _extend(
    target: list[ShadowCadenceOutcome],
    pair: tuple[ShadowCadenceOutcome, ShadowCadenceOutcome],
) -> None:
    target.extend(pair)


def test_calibration_waits_for_large_paired_sample() -> None:
    outcomes: list[ShadowCadenceOutcome] = []
    for index in range(100):
        _extend(
            outcomes,
            _pair(
                index,
                direction=Direction.LONG,
                strategy="trend",
                score="75",
                net_15m="0.01",
                net_1h="0.02",
            ),
        )

    result = cadence_trade_quality_calibration(outcomes)

    assert result["status"] == "not_ready"
    assert result["paired_decisions"] == 100
    assert result["still_needed_paired_decisions"] == 500
    assert result["qualifies_development"] is False


def test_calibration_selects_stable_quality_for_both_directions() -> None:
    outcomes: list[ShadowCadenceOutcome] = []
    for index in range(400):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        strategy = "trend" if direction is Direction.LONG else "breakout"
        _extend(
            outcomes,
            _pair(
                index,
                direction=direction,
                strategy=strategy,
                score="77",
                net_15m="0.004",
                net_1h="0.006",
            ),
        )
    for index in range(400, 600):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        strategy = "trend" if direction is Direction.LONG else "breakout"
        _extend(
            outcomes,
            _pair(
                index,
                direction=direction,
                strategy=strategy,
                score="77",
                net_15m="0.003",
                net_1h="0.005",
            ),
        )

    result = cadence_trade_quality_calibration(outcomes)

    assert result["status"] == "completed"
    assert result["selected_group_count"] == 2
    candidate = result["candidate_validation"]
    assert isinstance(candidate, dict)
    assert candidate["count"] == 200
    by_direction = result["candidate_validation_by_direction"]
    assert isinstance(by_direction, dict)
    assert by_direction["long"]["count"] == 100
    assert by_direction["short"]["count"] == 100
    assert result["all_stability_blocks_positive"] is True
    assert result["qualifies_development"] is True
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_negative_validation_block_prevents_development_qualification() -> None:
    outcomes: list[ShadowCadenceOutcome] = []
    for index in range(400):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        _extend(
            outcomes,
            _pair(
                index,
                direction=direction,
                strategy="trend",
                score="77",
                net_15m="0.004",
                net_1h="0.006",
            ),
        )
    for index in range(400, 600):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        negative = 450 <= index < 500
        _extend(
            outcomes,
            _pair(
                index,
                direction=direction,
                strategy="trend",
                score="77",
                net_15m="-0.02" if negative else "0.01",
                net_1h="-0.02" if negative else "0.01",
            ),
        )

    result = cadence_trade_quality_calibration(outcomes)

    assert result["status"] == "completed"
    assert result["candidate_validation"]["count"] == 200
    assert result["all_stability_blocks_positive"] is False
    assert result["qualifies_development"] is False


def test_pairing_rejects_horizon_lineage_mismatch() -> None:
    first, second = _pair(
        1,
        direction=Direction.LONG,
        strategy="trend",
        score="77",
        net_15m="0.01",
        net_1h="0.01",
    )
    sample = second.sample
    mismatched = ShadowCadenceOutcome(
        sample=ShadowCadenceDecision(
            cadence_ms=sample.cadence_ms,
            boundary_ms=sample.boundary_ms,
            evaluated_at_ms=sample.evaluated_at_ms,
            market=sample.market,
            direction=sample.direction,
            score=Decimal("81"),
            lead_strategy=sample.lead_strategy,
            decision_id=sample.decision_id,
            feature_snapshot_id=sample.feature_snapshot_id,
            entry_px=sample.entry_px,
            horizon_ms=sample.horizon_ms,
            target_end_ms=sample.target_end_ms,
            cost_fraction=sample.cost_fraction,
            off_primary_boundary=sample.off_primary_boundary,
        ),
        exit_px=second.exit_px,
        gross_return=second.gross_return,
        net_return=second.net_return,
    )

    with pytest.raises(
        CadenceTradeQualityCalibrationError,
        match="lineage mismatch",
    ):
        cadence_trade_quality_calibration((first, mismatched))
