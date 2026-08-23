from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.ws_protocol import subscription_id

HYPERLIQUID_MAX_SUBSCRIPTIONS = 1000
DEFAULT_SAFETY_CEILING = 800
DEFAULT_CANDLE_INTERVALS = ("1m", "5m", "15m")

Subscription = dict[str, object]


@dataclass(frozen=True, slots=True)
class SubscriptionPlan:
    unsubscribe: tuple[Subscription, ...]
    subscribe: tuple[Subscription, ...]
    desired_count: int


class DeepWatchlistManager:
    def __init__(
        self,
        *,
        broad_dexes: Iterable[str] = (),
        candle_intervals: Iterable[str] = DEFAULT_CANDLE_INTERVALS,
        safety_ceiling: int = DEFAULT_SAFETY_CEILING,
    ) -> None:
        if safety_ceiling <= 0:
            raise ValueError("safety ceiling must be positive")
        if safety_ceiling > HYPERLIQUID_MAX_SUBSCRIPTIONS:
            raise ValueError(
                "safety ceiling must not exceed Hyperliquid's 1000-subscription limit"
            )

        dexes = tuple(sorted(set(broad_dexes)))
        if any(not dex.strip() for dex in dexes):
            raise ValueError("broad dex names must not be empty")

        intervals = tuple(dict.fromkeys(candle_intervals))
        if not intervals or any(not interval.strip() for interval in intervals):
            raise ValueError("candle intervals must contain non-empty values")

        self._broad_dexes = dexes
        self._candle_intervals = intervals
        self._safety_ceiling = safety_ceiling
        self._active: dict[str, Subscription] = {}

    @property
    def active_count(self) -> int:
        return len(self._active)

    def reconcile(
        self,
        markets: Iterable[MarketId],
        *,
        pinned_markets: Iterable[MarketId] = (),
    ) -> SubscriptionPlan:
        desired = self._desired_subscriptions((*markets, *pinned_markets))
        if len(desired) > self._safety_ceiling:
            raise ValueError(
                f"desired subscription count {len(desired)} exceeds safety ceiling "
                f"{self._safety_ceiling}"
            )

        removed_ids = sorted(set(self._active) - set(desired))
        added_ids = sorted(set(desired) - set(self._active))
        plan = SubscriptionPlan(
            unsubscribe=tuple(dict(self._active[item]) for item in removed_ids),
            subscribe=tuple(dict(desired[item]) for item in added_ids),
            desired_count=len(desired),
        )

        self._active = {key: dict(value) for key, value in desired.items()}
        return plan

    def _desired_subscriptions(self, markets: Iterable[MarketId]) -> dict[str, Subscription]:
        desired: dict[str, Subscription] = {}
        self._add(desired, {"type": "allMids"})
        for dex in self._broad_dexes:
            self._add(desired, {"type": "allMids", "dex": dex})

        unique_markets = {market.canonical: market for market in markets}
        for canonical in sorted(unique_markets):
            wire_name = unique_markets[canonical].wire_name
            self._add(desired, {"type": "activeAssetCtx", "coin": wire_name})
            self._add(desired, {"type": "l2Book", "coin": wire_name})
            self._add(desired, {"type": "trades", "coin": wire_name})
            for interval in self._candle_intervals:
                self._add(
                    desired,
                    {"type": "candle", "coin": wire_name, "interval": interval},
                )
        return desired

    @staticmethod
    def _add(desired: dict[str, Subscription], subscription: Mapping[str, object]) -> None:
        normalized = dict(subscription)
        desired[subscription_id(normalized)] = normalized
