from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.features import EligibilityDecision, FeatureSnapshot
from cocomelon.domain.market import PerpMarketSnapshot
from cocomelon.features.math import quantile

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class EligibilityConfig:
    max_context_age_ms: int = 60_000
    volume_quantile: Decimal = Decimal("0.10")
    oi_quantile: Decimal = Decimal("0.10")
    absolute_min_day_notional_volume: Decimal = ZERO
    absolute_min_open_interest: Decimal = ZERO
    max_book_age_ms: int = 5_000
    hard_max_spread_bps: Decimal = Decimal("50")
    spread_quantile: Decimal = Decimal("0.90")
    depth_quantile: Decimal = Decimal("0.10")
    absolute_min_side_depth: Decimal = ZERO

    def __post_init__(self) -> None:
        if self.max_context_age_ms <= 0:
            raise ValueError("max_context_age_ms must be positive")
        if self.max_book_age_ms <= 0:
            raise ValueError("max_book_age_ms must be positive")
        for name in ("volume_quantile", "oi_quantile", "spread_quantile", "depth_quantile"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO or value > ONE:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        non_negative = (
            ("absolute_min_day_notional_volume", self.absolute_min_day_notional_volume),
            ("absolute_min_open_interest", self.absolute_min_open_interest),
            ("absolute_min_side_depth", self.absolute_min_side_depth),
        )
        for name, value in non_negative:
            if not value.is_finite() or value < ZERO:
                raise ValueError(f"{name} must be finite and non-negative")
        if not self.hard_max_spread_bps.is_finite() or self.hard_max_spread_bps <= ZERO:
            raise ValueError("hard_max_spread_bps must be finite and positive")


@dataclass(frozen=True, slots=True)
class EligibilityThresholds:
    min_day_notional_volume: Decimal
    min_open_interest: Decimal
    max_spread_bps: Decimal
    min_side_depth: Decimal


def derive_eligibility_thresholds(
    snapshots: Sequence[FeatureSnapshot],
    config: EligibilityConfig,
) -> EligibilityThresholds:
    if not snapshots:
        raise ValueError("snapshots must not be empty")

    volume_floor = max(
        config.absolute_min_day_notional_volume,
        quantile(tuple(item.day_notional_volume for item in snapshots), config.volume_quantile),
    )
    oi_floor = max(
        config.absolute_min_open_interest,
        quantile(tuple(item.open_interest for item in snapshots), config.oi_quantile),
    )

    deep = tuple(
        item
        for item in snapshots
        if item.spread_bps is not None
        and item.bid_depth_25bps is not None
        and item.ask_depth_25bps is not None
    )
    if len(deep) >= 5:
        spreads = tuple(item.spread_bps for item in deep if item.spread_bps is not None)
        side_depths = tuple(
            min(item.bid_depth_25bps, item.ask_depth_25bps)
            for item in deep
            if item.bid_depth_25bps is not None and item.ask_depth_25bps is not None
        )
        spread_ceiling = min(
            config.hard_max_spread_bps,
            quantile(spreads, config.spread_quantile),
        )
        depth_floor = max(
            config.absolute_min_side_depth,
            quantile(side_depths, config.depth_quantile),
        )
    else:
        spread_ceiling = config.hard_max_spread_bps
        depth_floor = config.absolute_min_side_depth

    return EligibilityThresholds(
        min_day_notional_volume=volume_floor,
        min_open_interest=oi_floor,
        max_spread_bps=spread_ceiling,
        min_side_depth=depth_floor,
    )


def _positive(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > ZERO


def evaluate_eligibility(
    market_snapshot: PerpMarketSnapshot,
    features: FeatureSnapshot,
    thresholds: EligibilityThresholds,
    config: EligibilityConfig,
) -> EligibilityDecision:
    market = market_snapshot.meta.market
    if features.market != market or market_snapshot.context.market != market:
        raise ValueError("market snapshot and feature snapshot must represent the same market")

    reasons: list[str] = []
    if market_snapshot.meta.is_delisted:
        reasons.append("delisted")

    context = market_snapshot.context
    if not all(
        _positive(value)
        for value in (context.mark_px, context.mid_px, context.oracle_px, context.prev_day_px)
    ):
        reasons.append("invalid_price_state")

    received_at = market_snapshot.received_at_ms
    if received_at > features.as_of_ms or features.as_of_ms - received_at > config.max_context_age_ms:
        reasons.append("stale_context")

    if market_snapshot.meta.max_leverage <= 0:
        reasons.append("unsupported_leverage")
    if features.day_notional_volume < thresholds.min_day_notional_volume:
        reasons.append("below_volume_floor")
    if features.open_interest < thresholds.min_open_interest:
        reasons.append("below_oi_floor")

    if reasons:
        return EligibilityDecision(
            market=market,
            rankable=False,
            deep_ready=False,
            reasons=tuple(reasons),
        )

    deep_values = (
        features.spread_bps,
        features.bid_depth_25bps,
        features.ask_depth_25bps,
        features.book_age_ms,
    )
    if any(value is None for value in deep_values):
        return EligibilityDecision(
            market=market,
            rankable=True,
            deep_ready=False,
            reasons=("missing_deep_data",),
        )

    assert features.spread_bps is not None
    assert features.bid_depth_25bps is not None
    assert features.ask_depth_25bps is not None
    assert features.book_age_ms is not None

    deep_reasons: list[str] = []
    if features.book_age_ms > config.max_book_age_ms:
        deep_reasons.append("stale_book")
    if features.spread_bps < ZERO or features.spread_bps > thresholds.max_spread_bps:
        deep_reasons.append("excessive_spread")
    if (
        features.bid_depth_25bps < thresholds.min_side_depth
        or features.ask_depth_25bps < thresholds.min_side_depth
    ):
        deep_reasons.append("insufficient_depth")

    return EligibilityDecision(
        market=market,
        rankable=True,
        deep_ready=not deep_reasons,
        reasons=tuple(deep_reasons),
    )
