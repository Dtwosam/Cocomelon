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
from cocomelon.research.prospective_context_evidence import (
    FROZEN_CONTEXT_BASKET,
)

ZERO: Final = Decimal("0")
MEDIAN: Final = Decimal("0.5")


class CadenceBasketContextError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CadenceFrozenBasketContext:
    target_snapshot_id: str
    target_market: str
    as_of_ms: int
    basket_markets: tuple[str, ...]
    basket_median_return_1h: Decimal
    basket_breadth_positive_1h: Decimal
    basket_return_dispersion_1h: Decimal
    relative_return_1h_vs_basket: Decimal
    relative_return_zscore_1h_vs_basket: Decimal | None
    context_state_1h: str

    def __post_init__(self) -> None:
        if self.basket_markets != FROZEN_CONTEXT_BASKET:
            raise ValueError("basket markets must match frozen context basket")
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        for field in (
            "basket_median_return_1h",
            "basket_breadth_positive_1h",
            "basket_return_dispersion_1h",
            "relative_return_1h_vs_basket",
        ):
            value = getattr(self, field)
            if not value.is_finite():
                raise ValueError(f"{field} must be finite")
        if (
            self.relative_return_zscore_1h_vs_basket is not None
            and not self.relative_return_zscore_1h_vs_basket.is_finite()
        ):
            raise ValueError(
                "relative_return_zscore_1h_vs_basket must be finite"
            )


class CadenceFrozenBasketIndex:
    def __init__(
        self,
        feature_store: LearningFeatureSnapshotStore,
    ) -> None:
        by_as_of: defaultdict[
            int,
            dict[str, FeatureSnapshot],
        ] = defaultdict(dict)
        duplicate: list[tuple[int, str]] = []
        for verified in feature_store.iter_verified():
            snapshot = verified.snapshot
            market = snapshot.market.canonical
            existing = by_as_of[snapshot.as_of_ms].get(market)
            if existing is not None and existing != snapshot:
                duplicate.append((snapshot.as_of_ms, market))
                continue
            by_as_of[snapshot.as_of_ms][market] = snapshot
        if duplicate:
            raise CadenceBasketContextError(
                "CADENCE_BASKET_DUPLICATE_ASOF_MARKET"
            )
        self._by_as_of = {
            as_of_ms: dict(markets)
            for as_of_ms, markets in by_as_of.items()
        }

    @classmethod
    def from_root(
        cls,
        feature_store_root: str | Path,
    ) -> CadenceFrozenBasketIndex:
        return cls(LearningFeatureSnapshotStore(feature_store_root))

    def resolve(
        self,
        target: FeatureSnapshot,
        *,
        decision_evaluated_at_ms: int,
    ) -> CadenceFrozenBasketContext:
        if target.as_of_ms > decision_evaluated_at_ms:
            raise CadenceBasketContextError(
                "CADENCE_BASKET_TARGET_AFTER_DECISION"
            )
        if target.source_received_at_ms > decision_evaluated_at_ms:
            raise CadenceBasketContextError(
                "CADENCE_BASKET_TARGET_SOURCE_AFTER_DECISION"
            )

        snapshots = self._by_as_of.get(target.as_of_ms)
        if snapshots is None:
            raise CadenceBasketContextError(
                "CADENCE_BASKET_ASOF_MISSING"
            )
        basket: list[FeatureSnapshot] = []
        for canonical in FROZEN_CONTEXT_BASKET:
            snapshot = snapshots.get(canonical)
            if snapshot is None:
                raise CadenceBasketContextError(
                    f"CADENCE_BASKET_MARKET_MISSING:{canonical}"
                )
            if snapshot.source_received_at_ms > decision_evaluated_at_ms:
                raise CadenceBasketContextError(
                    f"CADENCE_BASKET_SOURCE_AFTER_DECISION:{canonical}"
                )
            if snapshot.return_1h is None:
                raise CadenceBasketContextError(
                    f"CADENCE_BASKET_RETURN_1H_MISSING:{canonical}"
                )
            basket.append(snapshot)

        if target.return_1h is None:
            raise CadenceBasketContextError(
                "CADENCE_BASKET_TARGET_RETURN_1H_MISSING"
            )

        returns = tuple(
            snapshot.return_1h
            for snapshot in basket
            if snapshot.return_1h is not None
        )
        if len(returns) != len(FROZEN_CONTEXT_BASKET):
            raise CadenceBasketContextError(
                "CADENCE_BASKET_RETURN_1H_INCOMPLETE"
            )
        count = Decimal(len(returns))
        median = quantile(returns, MEDIAN)
        breadth = (
            Decimal(sum(1 for value in returns if value > ZERO))
            / count
        )
        mean = sum(returns, ZERO) / count
        variance = (
            sum(
                ((value - mean) * (value - mean) for value in returns),
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
        return CadenceFrozenBasketContext(
            target_snapshot_id=target.snapshot_id,
            target_market=target.market.canonical,
            as_of_ms=target.as_of_ms,
            basket_markets=FROZEN_CONTEXT_BASKET,
            basket_median_return_1h=median,
            basket_breadth_positive_1h=breadth,
            basket_return_dispersion_1h=dispersion,
            relative_return_1h_vs_basket=relative,
            relative_return_zscore_1h_vs_basket=zscore,
            context_state_1h=state,
        )
