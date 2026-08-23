from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    OpportunityRank,
    ShortlistDelta,
)
from cocomelon.domain.market import Candle, MarketId, PerpMarketSnapshot
from cocomelon.domain.stream import StreamEvent
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.features.candles import calculate_candle_features
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.features.regime import assign_volatility_regimes
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager, SubscriptionPlan
from cocomelon.scanner.eligibility import (
    EligibilityConfig,
    derive_eligibility_thresholds,
    evaluate_eligibility,
)
from cocomelon.scanner.ranker import rank_opportunities
from cocomelon.scanner.shortlist import (
    DynamicShortlistManager,
    ShortlistConfig,
    build_subscription_plan,
)


@dataclass(frozen=True, slots=True)
class ScanResult:
    feature_snapshots: tuple[FeatureSnapshot, ...]
    eligibility: tuple[EligibilityDecision, ...]
    ranks: tuple[OpportunityRank, ...]
    shortlist: ShortlistDelta
    subscription_plan: SubscriptionPlan


class FeatureScanner:
    def __init__(
        self,
        *,
        eligibility_config: EligibilityConfig | None = None,
        shortlist_config: ShortlistConfig | None = None,
        deep_watchlist: DeepWatchlistManager | None = None,
    ) -> None:
        self._eligibility_config = eligibility_config or EligibilityConfig()
        self._shortlist_config = shortlist_config or ShortlistConfig()
        self._shortlist = DynamicShortlistManager(self._shortlist_config)
        self._deep_watchlist = deep_watchlist or DeepWatchlistManager()

    def scan(
        self,
        current_markets: Mapping[str, PerpMarketSnapshot],
        *,
        previous_markets: Mapping[str, PerpMarketSnapshot] | None = None,
        candles_5m: Mapping[str, Sequence[Candle]] | None = None,
        candles_15m: Mapping[str, Sequence[Candle]] | None = None,
        l2_books: Mapping[str, StreamEvent] | None = None,
        as_of_ms: int,
        pinned_markets: Iterable[MarketId] = (),
    ) -> ScanResult:
        if as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")

        previous = previous_markets or {}
        five_minute = candles_5m or {}
        fifteen_minute = candles_15m or {}
        books = l2_books or {}
        pinned = tuple(pinned_markets)

        current_by_market: dict[str, PerpMarketSnapshot] = {}
        broad_snapshots: list[FeatureSnapshot] = []
        broad_values_by_market = {}

        ordered_current = sorted(
            current_markets.values(),
            key=lambda snapshot: snapshot.meta.market.canonical,
        )
        for market_snapshot in ordered_current:
            market = market_snapshot.meta.market
            key = market.canonical
            if key in current_by_market:
                raise ValueError(f"duplicate current market snapshot: {key}")
            if market_snapshot.context.market != market:
                raise ValueError(f"market metadata/context mismatch: {key}")
            if market_snapshot.received_at_ms > as_of_ms:
                continue

            prior = previous.get(key)
            if prior is not None and prior.received_at_ms > as_of_ms:
                prior = None

            broad = calculate_broad_features(
                market_snapshot,
                prior,
                as_of_ms=as_of_ms,
            )
            feature = assemble_feature_snapshot(
                market,
                broad,
                as_of_ms=as_of_ms,
                provenance=(market_snapshot.source,),
            )
            current_by_market[key] = market_snapshot
            broad_values_by_market[key] = broad
            broad_snapshots.append(feature)

        if not broad_snapshots:
            shortlist = self._shortlist.reconcile((), (), pinned_markets=pinned)
            subscription_plan = build_subscription_plan(
                self._deep_watchlist,
                shortlist,
                pinned_markets=pinned,
            )
            return ScanResult(
                feature_snapshots=(),
                eligibility=(),
                ranks=(),
                shortlist=shortlist,
                subscription_plan=subscription_plan,
            )

        coarse_thresholds = derive_eligibility_thresholds(
            broad_snapshots,
            self._eligibility_config,
        )
        coarse_decisions = tuple(
            evaluate_eligibility(
                current_by_market[feature.market.canonical],
                feature,
                coarse_thresholds,
                self._eligibility_config,
            )
            for feature in broad_snapshots
        )
        coarse_ranks = rank_opportunities(
            broad_snapshots,
            coarse_decisions,
            mode="coarse",
        )
        tier_b_keys = {
            rank.market.canonical
            for rank in coarse_ranks[: self._shortlist_config.ranked_watchlist_size]
        }

        enriched_keys: set[str] = set()
        assembled: list[FeatureSnapshot] = []
        for broad_feature in broad_snapshots:
            market = broad_feature.market
            key = market.canonical
            if key not in tier_b_keys:
                assembled.append(broad_feature)
                continue

            candle_values = None
            candle_5m_values = five_minute.get(key, ())
            candle_15m_values = fifteen_minute.get(key, ())
            if candle_5m_values or candle_15m_values:
                candle_values = calculate_candle_features(
                    market,
                    candles_5m=candle_5m_values,
                    candles_15m=candle_15m_values,
                    as_of_ms=as_of_ms,
                )
                enriched_keys.add(key)

            microstructure_values = None
            book = books.get(key)
            if book is not None:
                if book.market != market:
                    raise ValueError(f"L2 book market mismatch for {key}")
                microstructure_values = calculate_microstructure_features(
                    book,
                    as_of_ms=as_of_ms,
                )
                enriched_keys.add(key)

            provenance = {current_by_market[key].source}
            for candle in (*candle_5m_values, *candle_15m_values):
                provenance.add(candle.source)
            if book is not None:
                provenance.add(book.source)

            assembled.append(
                assemble_feature_snapshot(
                    market,
                    broad_values_by_market[key],
                    candle=candle_values,
                    microstructure=microstructure_values,
                    as_of_ms=as_of_ms,
                    provenance=tuple(provenance),
                )
            )

        feature_snapshots = assign_volatility_regimes(assembled)
        final_thresholds = derive_eligibility_thresholds(
            feature_snapshots,
            self._eligibility_config,
        )
        final_decisions = tuple(
            evaluate_eligibility(
                current_by_market[feature.market.canonical],
                feature,
                final_thresholds,
                self._eligibility_config,
            )
            for feature in feature_snapshots
        )

        final_coarse_ranks = rank_opportunities(
            feature_snapshots,
            final_decisions,
            mode="coarse",
        )
        enriched_features = tuple(
            feature
            for feature in feature_snapshots
            if feature.market.canonical in enriched_keys
        )
        final_decision_map = {
            decision.market.canonical: decision for decision in final_decisions
        }
        enriched_decisions = tuple(
            final_decision_map[feature.market.canonical]
            for feature in enriched_features
        )
        enriched_ranks = (
            rank_opportunities(
                enriched_features,
                enriched_decisions,
                mode="enriched",
            )
            if enriched_features
            else ()
        )
        enriched_rank_map = {
            rank.market.canonical: rank for rank in enriched_ranks
        }

        combined = [
            enriched_rank_map.get(rank.market.canonical, rank)
            for rank in final_coarse_ranks
        ]
        combined.sort(key=lambda rank: (-rank.score, rank.market.canonical))
        final_ranks = tuple(
            OpportunityRank(
                market=rank.market,
                ordinal=ordinal,
                score=rank.score,
                components=rank.components,
                reason_codes=rank.reason_codes,
            )
            for ordinal, rank in enumerate(combined, start=1)
        )

        shortlist = self._shortlist.reconcile(
            final_ranks,
            final_decisions,
            pinned_markets=pinned,
        )
        subscription_plan = build_subscription_plan(
            self._deep_watchlist,
            shortlist,
            pinned_markets=pinned,
        )
        return ScanResult(
            feature_snapshots=tuple(feature_snapshots),
            eligibility=final_decisions,
            ranks=final_ranks,
            shortlist=shortlist,
            subscription_plan=subscription_plan,
        )
