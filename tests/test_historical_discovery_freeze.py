from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.features import (
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.features.cross_market import build_cross_market_contexts
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    HistoricalDiscoveryFreezeSpec,
    evaluate_prospective_context_candidate,
)

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")
SOL = MarketId("", "SOL")
HYPE = MarketId("", "HYPE")
CUTOVER_MS = 1_790_121_600_000
FOUR_HOURS = 14_400_000


def _snapshot(
    market: MarketId,
    *,
    as_of_ms: int,
    return_1h: str,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=as_of_ms - 1_000,
        schema_version=1,
        day_return=Decimal("0"),
        funding=Decimal("0"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=None,
        return_5m=None,
        return_15m=None,
        return_1h=Decimal(return_1h),
        return_4h=None,
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UNKNOWN,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=("hyperliquid-mainnet-info",),
    )


def _matching_snapshots(
    *,
    as_of_ms: int,
) -> tuple[tuple[FeatureSnapshot, ...], FeatureSnapshot]:
    snapshots = (
        _snapshot(BTC, as_of_ms=as_of_ms, return_1h="-0.02"),
        _snapshot(ETH, as_of_ms=as_of_ms, return_1h="-0.01"),
        _snapshot(SOL, as_of_ms=as_of_ms, return_1h="-0.03"),
        _snapshot(HYPE, as_of_ms=as_of_ms, return_1h="-0.015"),
    )
    hype = next(item for item in snapshots if item.market == HYPE)
    return snapshots, hype


def test_frozen_hype_candidate_binds_exact_discovery_and_occupancy_lineage() -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1

    assert spec.candidate_id == "hype-down-bearish-near-basket-long-4h-v1"
    assert spec.market == HYPE
    assert spec.context_state_1h == "down/bearish/near_basket"
    assert spec.direction is Direction.LONG
    assert spec.horizon_ms == FOUR_HOURS
    assert spec.discovery_start_ms == 1_772_323_200_000
    assert spec.discovery_end_ms == 1_789_862_400_000
    assert spec.validation_not_before_ms == CUTOVER_MS
    assert spec.discovery_report_id == (
        "f3b38a6625ad2ea2d1b2df7e736f5dbded6f2b415c53c80db35514e4f3589481"
    )
    assert spec.discovery_dataset_id == (
        "268aa965584316f35a9db520b13848fd030123eadc99482a89cd7bc68ffc091f"
    )
    assert spec.occupancy_report_id == (
        "fc083ac327d1cbc758af4515393a35647b980ae231f9a3763e1e8005286414c9"
    )
    assert spec.occupancy_dataset_id == (
        "543e919969cc3160f4b72ef687102f1a989ec8446d4f691b05c376b6d19b72df"
    )
    assert spec.prospective_only is True
    assert spec.promotion_eligible is False
    assert len(spec.spec_id) == 64


def test_frozen_candidate_rejects_early_validation_cutover() -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1

    with pytest.raises(ValueError, match="discovery embargo"):
        replace(
            spec,
            validation_not_before_ms=spec.discovery_end_ms + 1,
        )


def test_frozen_candidate_can_never_be_promotion_eligible() -> None:
    with pytest.raises(ValueError, match="promotion eligible"):
        replace(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            promotion_eligible=True,
        )


def test_matching_context_before_cutover_is_forced_no_trade() -> None:
    snapshots, hype = _matching_snapshots(as_of_ms=CUTOVER_MS - 1)
    context = next(
        item
        for item in build_cross_market_contexts(snapshots)
        if item.market == HYPE
    )

    decision = evaluate_prospective_context_candidate(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        feature=hype,
        cross_market=context,
    )

    assert context.for_window("1h").context_state == "down/bearish/near_basket"
    assert decision.direction is Direction.NO_TRADE
    assert decision.hold_until_ms is None
    assert decision.reason_codes == ("before_prospective_cutover",)


def test_exact_post_cutover_context_emits_fixed_long_observation() -> None:
    snapshots, hype = _matching_snapshots(as_of_ms=CUTOVER_MS)
    context = next(
        item
        for item in build_cross_market_contexts(snapshots)
        if item.market == HYPE
    )

    decision = evaluate_prospective_context_candidate(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        feature=hype,
        cross_market=context,
    )

    assert decision.direction is Direction.LONG
    assert decision.hold_until_ms == CUTOVER_MS + FOUR_HOURS
    assert decision.context_state_1h == "down/bearish/near_basket"
    assert decision.reason_codes == ("frozen_historical_context_match",)
    assert len(decision.decision_id) == 24


def test_post_cutover_context_mismatch_remains_no_trade() -> None:
    as_of_ms = CUTOVER_MS + 3_600_000
    snapshots = (
        _snapshot(BTC, as_of_ms=as_of_ms, return_1h="0.02"),
        _snapshot(ETH, as_of_ms=as_of_ms, return_1h="0.01"),
        _snapshot(SOL, as_of_ms=as_of_ms, return_1h="0.03"),
        _snapshot(HYPE, as_of_ms=as_of_ms, return_1h="0.015"),
    )
    hype = next(item for item in snapshots if item.market == HYPE)
    context = next(
        item
        for item in build_cross_market_contexts(snapshots)
        if item.market == HYPE
    )

    decision = evaluate_prospective_context_candidate(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
        feature=hype,
        cross_market=context,
    )

    assert context.for_window("1h").context_state == "up/bullish/near_basket"
    assert decision.direction is Direction.NO_TRADE
    assert decision.reason_codes == ("context_mismatch",)


def test_prospective_candidate_requires_market_and_time_alignment() -> None:
    snapshots, hype = _matching_snapshots(as_of_ms=CUTOVER_MS)
    contexts = build_cross_market_contexts(snapshots)
    btc_context = next(item for item in contexts if item.market == BTC)
    hype_context = next(item for item in contexts if item.market == HYPE)

    with pytest.raises(ValueError, match="candidate market"):
        evaluate_prospective_context_candidate(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            feature=hype,
            cross_market=btc_context,
        )

    future_hype = _snapshot(
        HYPE,
        as_of_ms=CUTOVER_MS + 3_600_000,
        return_1h="-0.015",
    )
    with pytest.raises(ValueError, match="same as_of_ms"):
        evaluate_prospective_context_candidate(
            HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
            feature=future_hype,
            cross_market=hype_context,
        )


def test_spec_identity_changes_if_rule_or_costs_change() -> None:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    changed_context = replace(spec, context_state_1h="down/mixed/near_basket")
    changed_cost = replace(
        spec,
        costs=replace(
            spec.costs,
            round_trip_slippage_fraction=Decimal("0.0006"),
        ),
    )

    assert changed_context.spec_id != spec.spec_id
    assert changed_cost.spec_id != spec.spec_id
