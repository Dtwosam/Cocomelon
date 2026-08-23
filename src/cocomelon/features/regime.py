from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.features import FeatureSnapshot, VolatilityRegime
from cocomelon.features.math import quantile


def assign_volatility_regimes(
    snapshots: Sequence[FeatureSnapshot],
    *,
    low_quantile: Decimal = Decimal("0.20"),
    high_quantile: Decimal = Decimal("0.80"),
) -> tuple[FeatureSnapshot, ...]:
    values = tuple(
        snapshot.realized_vol_15m
        for snapshot in snapshots
        if snapshot.realized_vol_15m is not None
    )
    if len(values) < 5:
        return tuple(
            replace(snapshot, volatility_regime=VolatilityRegime.UNKNOWN)
            for snapshot in snapshots
        )

    low_threshold = quantile(values, low_quantile)
    high_threshold = quantile(values, high_quantile)
    assigned: list[FeatureSnapshot] = []
    for snapshot in snapshots:
        value = snapshot.realized_vol_15m
        if value is None:
            regime = VolatilityRegime.UNKNOWN
        elif value <= low_threshold:
            regime = VolatilityRegime.LOW
        elif value >= high_threshold:
            regime = VolatilityRegime.HIGH
        else:
            regime = VolatilityRegime.NORMAL
        assigned.append(replace(snapshot, volatility_regime=regime))
    return tuple(assigned)
