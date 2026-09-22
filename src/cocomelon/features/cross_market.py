from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.market import MarketId
from cocomelon.features.math import quantile

ZERO = Decimal("0")
MEDIAN = Decimal("0.5")
WINDOWS = ("5m", "15m", "1h", "4h")


class CrossMarketFeatureError(RuntimeError):
    pass


def basket_direction_bucket(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value > ZERO:
        return "up"
    if value < ZERO:
        return "down"
    return "flat"


def basket_breadth_bucket(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value <= Decimal("0.25"):
        return "bearish"
    if value >= Decimal("0.75"):
        return "bullish"
    return "mixed"


def relative_strength_bucket(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value <= Decimal("-1"):
        return "lagging_1sd"
    if value >= Decimal("1"):
        return "leading_1sd"
    return "near_basket"


@dataclass(frozen=True, slots=True)
class CrossMarketWindowContext:
    window: str
    btc_return: Decimal | None
    eth_return: Decimal | None
    basket_median_return: Decimal | None
    basket_breadth_positive: Decimal | None
    relative_return_vs_basket: Decimal | None
    basket_return_count: Decimal
    basket_return_dispersion: Decimal | None
    relative_return_zscore_vs_basket: Decimal | None

    def __post_init__(self) -> None:
        if self.window not in WINDOWS:
            raise ValueError("unsupported cross-market window")
        if self.basket_return_count < ZERO:
            raise ValueError("basket_return_count must be non-negative")
        for field in (
            "btc_return",
            "eth_return",
            "basket_median_return",
            "basket_breadth_positive",
            "relative_return_vs_basket",
            "basket_return_dispersion",
            "relative_return_zscore_vs_basket",
        ):
            value = getattr(self, field)
            if value is not None and not value.is_finite():
                raise ValueError(f"{field} must be finite")
        if self.basket_breadth_positive is not None and not (
            ZERO <= self.basket_breadth_positive <= Decimal("1")
        ):
            raise ValueError("basket_breadth_positive must be between zero and one")
        if (
            self.basket_return_dispersion is not None
            and self.basket_return_dispersion < ZERO
        ):
            raise ValueError("basket_return_dispersion must be non-negative")

    @property
    def context_state(self) -> str:
        return "/".join(
            (
                basket_direction_bucket(self.basket_median_return),
                basket_breadth_bucket(self.basket_breadth_positive),
                relative_strength_bucket(self.relative_return_zscore_vs_basket),
            )
        )


@dataclass(frozen=True, slots=True)
class CrossMarketContextSnapshot:
    market: MarketId
    as_of_ms: int
    source_received_at_ms: int
    windows: tuple[CrossMarketWindowContext, ...]
    provenance: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.source_received_at_ms < 0:
            raise ValueError("source_received_at_ms must be non-negative")
        if self.source_received_at_ms > self.as_of_ms:
            raise ValueError("source_received_at_ms must not be after as_of_ms")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        actual = tuple(item.window for item in self.windows)
        if actual != WINDOWS:
            raise ValueError("windows must match the canonical cross-market order")
        normalized = tuple(sorted(set(self.provenance)))
        if any(not item.strip() for item in normalized):
            raise ValueError("provenance values must not be empty")
        object.__setattr__(self, "provenance", normalized)

    def for_window(self, window: str) -> CrossMarketWindowContext:
        for item in self.windows:
            if item.window == window:
                return item
        raise ValueError(f"unsupported cross-market window: {window}")

    @property
    def snapshot_id(self) -> str:
        payload = {
            "market": self.market.canonical,
            "as_of_ms": self.as_of_ms,
            "source_received_at_ms": self.source_received_at_ms,
            "schema_version": self.schema_version,
            "windows": tuple(
                {
                    "window": item.window,
                    "btc_return": None if item.btc_return is None else str(item.btc_return),
                    "eth_return": None if item.eth_return is None else str(item.eth_return),
                    "basket_median_return": (
                        None
                        if item.basket_median_return is None
                        else str(item.basket_median_return)
                    ),
                    "basket_breadth_positive": (
                        None
                        if item.basket_breadth_positive is None
                        else str(item.basket_breadth_positive)
                    ),
                    "relative_return_vs_basket": (
                        None
                        if item.relative_return_vs_basket is None
                        else str(item.relative_return_vs_basket)
                    ),
                    "basket_return_count": str(item.basket_return_count),
                    "basket_return_dispersion": (
                        None
                        if item.basket_return_dispersion is None
                        else str(item.basket_return_dispersion)
                    ),
                    "relative_return_zscore_vs_basket": (
                        None
                        if item.relative_return_zscore_vs_basket is None
                        else str(item.relative_return_zscore_vs_basket)
                    ),
                }
                for item in self.windows
            ),
            "provenance": self.provenance,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:24]


def _return_for_window(snapshot: FeatureSnapshot, window: str) -> Decimal | None:
    return getattr(snapshot, f"return_{window}")


def _window_context(
    snapshots: Sequence[FeatureSnapshot],
    *,
    target: FeatureSnapshot,
    window: str,
) -> CrossMarketWindowContext:
    by_market = {snapshot.market.canonical: snapshot for snapshot in snapshots}
    btc = by_market.get("BTC")
    eth = by_market.get("ETH")
    btc_return = None if btc is None else _return_for_window(btc, window)
    eth_return = None if eth is None else _return_for_window(eth, window)

    observed = tuple(
        value
        for snapshot in snapshots
        if (value := _return_for_window(snapshot, window)) is not None
    )
    count = Decimal(len(observed))
    basket_median: Decimal | None = None
    breadth: Decimal | None = None
    dispersion: Decimal | None = None
    relative: Decimal | None = None
    relative_zscore: Decimal | None = None

    if len(observed) >= 2:
        basket_median = quantile(observed, MEDIAN)
        breadth = Decimal(sum(1 for value in observed if value > ZERO)) / count
        mean = sum(observed, ZERO) / count
        variance = sum(
            ((value - mean) * (value - mean) for value in observed),
            ZERO,
        ) / count
        dispersion = variance.sqrt()
        target_return = _return_for_window(target, window)
        if target_return is not None:
            relative = target_return - basket_median
            if dispersion > ZERO:
                relative_zscore = relative / dispersion

    return CrossMarketWindowContext(
        window=window,
        btc_return=btc_return,
        eth_return=eth_return,
        basket_median_return=basket_median,
        basket_breadth_positive=breadth,
        relative_return_vs_basket=relative,
        basket_return_count=count,
        basket_return_dispersion=dispersion,
        relative_return_zscore_vs_basket=relative_zscore,
    )


def build_cross_market_contexts(
    snapshots: Sequence[FeatureSnapshot],
) -> tuple[CrossMarketContextSnapshot, ...]:
    if not snapshots:
        return ()

    ordered = tuple(sorted(snapshots, key=lambda item: item.market.canonical))
    as_of_values = {snapshot.as_of_ms for snapshot in ordered}
    if len(as_of_values) != 1:
        raise CrossMarketFeatureError("MIXED_AS_OF_MS")

    markets = tuple(snapshot.market.canonical for snapshot in ordered)
    if len(set(markets)) != len(markets):
        raise CrossMarketFeatureError("DUPLICATE_MARKET")

    as_of_ms = ordered[0].as_of_ms
    source_received_at_ms = max(
        snapshot.source_received_at_ms for snapshot in ordered
    )
    provenance = tuple(
        sorted(
            {
                source
                for snapshot in ordered
                for source in snapshot.provenance
            }
        )
    )

    return tuple(
        CrossMarketContextSnapshot(
            market=target.market,
            as_of_ms=as_of_ms,
            source_received_at_ms=source_received_at_ms,
            windows=tuple(
                _window_context(ordered, target=target, window=window)
                for window in WINDOWS
            ),
            provenance=provenance,
        )
        for target in ordered
    )
