from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from cocomelon.domain.features import (
    EligibilityDecision,
    OpportunityRank,
    ShortlistDelta,
)
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager, SubscriptionPlan


@dataclass(frozen=True, slots=True)
class ShortlistConfig:
    target_size: int = 20
    retention_rank: int = 30
    ranked_watchlist_size: int = 40

    def __post_init__(self) -> None:
        if self.target_size <= 0:
            raise ValueError("target_size must be positive")
        if self.retention_rank < self.target_size:
            raise ValueError("retention_rank must be >= target_size")
        if self.ranked_watchlist_size < self.target_size:
            raise ValueError("ranked_watchlist_size must be >= target_size")


class DynamicShortlistManager:
    def __init__(self, config: ShortlistConfig | None = None) -> None:
        self._config = config or ShortlistConfig()
        self._current: tuple[MarketId, ...] = ()

    @property
    def current(self) -> tuple[MarketId, ...]:
        return self._current

    def reconcile(
        self,
        ranks: Sequence[OpportunityRank],
        decisions: Sequence[EligibilityDecision],
        *,
        pinned_markets: Iterable[MarketId] = (),
    ) -> ShortlistDelta:
        rank_map: dict[str, OpportunityRank] = {}
        for rank in ranks:
            key = rank.market.canonical
            if key in rank_map:
                raise ValueError(f"duplicate opportunity rank for market {key}")
            rank_map[key] = rank

        decision_map: dict[str, EligibilityDecision] = {}
        for decision in decisions:
            key = decision.market.canonical
            if key in decision_map:
                raise ValueError(f"duplicate eligibility decision for market {key}")
            decision_map[key] = decision

        ranked = tuple(
            sorted(
                (
                    rank
                    for key, rank in rank_map.items()
                    if key in decision_map and decision_map[key].rankable
                ),
                key=lambda rank: (rank.ordinal, rank.market.canonical),
            )
        )
        ranked_watchlist = tuple(
            rank.market for rank in ranked[: self._config.ranked_watchlist_size]
        )

        pinned = tuple(
            sorted(
                {market.canonical: market for market in pinned_markets}.values(),
                key=lambda market: market.canonical,
            )
        )
        pinned_keys = {market.canonical for market in pinned}

        retained: list[MarketId] = []
        for market in self._current:
            key = market.canonical
            if key in pinned_keys:
                continue
            current_decision = decision_map.get(key)
            current_rank = rank_map.get(key)
            if (
                current_decision is not None
                and current_decision.rankable
                and current_rank is not None
                and current_rank.ordinal <= self._config.retention_rank
            ):
                retained.append(market)
        retained.sort(
            key=lambda market: (rank_map[market.canonical].ordinal, market.canonical)
        )
        selected = retained[: self._config.target_size]
        selected_keys = {market.canonical for market in selected}

        for rank in ranked:
            key = rank.market.canonical
            if key in pinned_keys or key in selected_keys:
                continue
            if len(selected) >= self._config.target_size:
                break
            selected.append(rank.market)
            selected_keys.add(key)

        selected.sort(
            key=lambda market: (rank_map[market.canonical].ordinal, market.canonical)
        )
        current = tuple((*selected, *pinned))
        previous_keys = {market.canonical for market in self._current}
        current_keys = {market.canonical for market in current}
        added = tuple(market for market in current if market.canonical not in previous_keys)
        removed = tuple(
            sorted(
                (market for market in self._current if market.canonical not in current_keys),
                key=lambda market: market.canonical,
            )
        )

        self._current = current
        return ShortlistDelta(
            added=added,
            removed=removed,
            current=current,
            ranked_watchlist=ranked_watchlist,
        )


def build_subscription_plan(
    deep_watchlist: DeepWatchlistManager,
    shortlist: ShortlistDelta,
    *,
    pinned_markets: Iterable[MarketId] = (),
) -> SubscriptionPlan:
    return deep_watchlist.reconcile(
        shortlist.current,
        pinned_markets=pinned_markets,
    )
