from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.features.cross_market import (
    basket_breadth_bucket,
    basket_direction_bucket,
    relative_strength_bucket,
)
from cocomelon.features.math import quantile
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
MEDIAN: Final = Decimal("0.5")
DEFAULT_MIN_CONTEXT_MARKETS: Final = 5


class CadenceActiveContextError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceActiveCrossSection:
    target_snapshot_id: str
    target_market: str
    as_of_ms: int
    market_count: int
    return_1h_count: int
    median_return_1h: Decimal
    breadth_positive_1h: Decimal
    return_dispersion_1h: Decimal
    relative_return_1h: Decimal
    relative_zscore_1h: Decimal | None
    context_state_1h: str

    def __post_init__(self) -> None:
        if self.market_count <= 0 or self.return_1h_count <= 0:
            raise ValueError("cross-section counts must be positive")
        if self.return_1h_count > self.market_count:
            raise ValueError(
                "return_1h_count cannot exceed market_count"
            )
        for field in (
            "median_return_1h",
            "breadth_positive_1h",
            "return_dispersion_1h",
            "relative_return_1h",
        ):
            value = getattr(self, field)
            if not value.is_finite():
                raise ValueError(f"{field} must be finite")
        if (
            self.relative_zscore_1h is not None
            and not self.relative_zscore_1h.is_finite()
        ):
            raise ValueError("relative_zscore_1h must be finite")


class CadenceActiveCrossSectionIndex:
    def __init__(
        self,
        feature_store: LearningFeatureSnapshotStore,
        *,
        min_context_markets: int = DEFAULT_MIN_CONTEXT_MARKETS,
    ) -> None:
        if min_context_markets < 2:
            raise ValueError(
                "min_context_markets must be at least two"
            )
        by_as_of: defaultdict[
            int,
            dict[str, FeatureSnapshot],
        ] = defaultdict(dict)
        for verified in feature_store.iter_verified():
            snapshot = verified.snapshot
            market = snapshot.market.canonical
            existing = by_as_of[snapshot.as_of_ms].get(market)
            if existing is not None and existing != snapshot:
                raise CadenceActiveContextError(
                    "CADENCE_ACTIVE_CONTEXT_DUPLICATE_ASOF_MARKET"
                )
            by_as_of[snapshot.as_of_ms][market] = snapshot
        self._by_as_of = {
            as_of_ms: dict(markets)
            for as_of_ms, markets in by_as_of.items()
        }
        self.min_context_markets = min_context_markets

    @classmethod
    def from_root(
        cls,
        feature_store_root: str | Path,
        *,
        min_context_markets: int = DEFAULT_MIN_CONTEXT_MARKETS,
    ) -> CadenceActiveCrossSectionIndex:
        return cls(
            LearningFeatureSnapshotStore(feature_store_root),
            min_context_markets=min_context_markets,
        )

    def resolve(
        self,
        target: FeatureSnapshot,
        *,
        decision_evaluated_at_ms: int,
    ) -> CadenceActiveCrossSection:
        if target.as_of_ms > decision_evaluated_at_ms:
            raise CadenceActiveContextError(
                "CADENCE_ACTIVE_CONTEXT_TARGET_AFTER_DECISION"
            )
        if target.source_received_at_ms > decision_evaluated_at_ms:
            raise CadenceActiveContextError(
                "CADENCE_ACTIVE_CONTEXT_TARGET_SOURCE_AFTER_DECISION"
            )
        if target.return_1h is None:
            raise CadenceActiveContextError(
                "CADENCE_ACTIVE_CONTEXT_TARGET_RETURN_1H_MISSING"
            )
        group = self._by_as_of.get(target.as_of_ms)
        if group is None:
            raise CadenceActiveContextError(
                "CADENCE_ACTIVE_CONTEXT_ASOF_MISSING"
            )
        if target.market.canonical not in group:
            raise CadenceActiveContextError(
                "CADENCE_ACTIVE_CONTEXT_TARGET_NOT_IN_GROUP"
            )

        observed: list[Decimal] = []
        for snapshot in group.values():
            if snapshot.source_received_at_ms > decision_evaluated_at_ms:
                continue
            if snapshot.return_1h is not None:
                observed.append(snapshot.return_1h)

        if len(observed) < self.min_context_markets:
            raise CadenceActiveContextError(
                "CADENCE_ACTIVE_CONTEXT_INSUFFICIENT_MARKETS"
            )
        values = tuple(observed)
        count = Decimal(len(values))
        median = quantile(values, MEDIAN)
        breadth = (
            Decimal(sum(1 for value in values if value > ZERO))
            / count
        )
        mean = sum(values, ZERO) / count
        variance = (
            sum(
                ((value - mean) * (value - mean) for value in values),
                ZERO,
            )
            / count
        )
        dispersion = variance.sqrt()
        relative = target.return_1h - median
        zscore = (
            None
            if dispersion == ZERO
            else relative / dispersion
        )
        state = "/".join(
            (
                basket_direction_bucket(median),
                basket_breadth_bucket(breadth),
                relative_strength_bucket(zscore),
            )
        )
        return CadenceActiveCrossSection(
            target_snapshot_id=target.snapshot_id,
            target_market=target.market.canonical,
            as_of_ms=target.as_of_ms,
            market_count=len(group),
            return_1h_count=len(values),
            median_return_1h=median,
            breadth_positive_1h=breadth,
            return_dispersion_1h=dispersion,
            relative_return_1h=relative,
            relative_zscore_1h=zscore,
            context_state_1h=state,
        )
