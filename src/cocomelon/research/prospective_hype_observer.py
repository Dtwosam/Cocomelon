from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.market import Candle, MarketId, PerpMarketSnapshot
from cocomelon.domain.strategy import Direction
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.features.candles import calculate_candle_features
from cocomelon.features.cross_market import (
    CrossMarketContextSnapshot,
    build_cross_market_contexts,
)
from cocomelon.hyperliquid.normalize import (
    normalize_candles,
    normalize_meta_and_asset_ctxs,
)
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
    HistoricalDiscoveryFreezeSpec,
    evaluate_prospective_context_candidate,
)
from cocomelon.research.prospective_context_evidence import (
    FROZEN_CONTEXT_BASKET,
    ProspectiveEvidenceStore,
    ProspectiveObservation,
    ProspectiveOutcome,
    build_prospective_observation,
    build_prospective_outcome,
)

HOUR_MS = 3_600_000
FEATURE_LOOKBACK_MS = 6 * HOUR_MS
CURRENT_1H_LOOKBACK_MS = 3 * HOUR_MS


class ProspectiveObserverError(RuntimeError):
    pass


class ProspectivePublicReader(Protocol):
    def meta_and_asset_ctxs(self, dex: str = "") -> object: ...

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ProspectiveMarketData:
    as_of_ms: int
    markets: Mapping[str, PerpMarketSnapshot]
    candles_15m: Mapping[str, tuple[Candle, ...]]
    hype_candles_1h: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        for market in FROZEN_CONTEXT_BASKET:
            snapshot = self.markets.get(market)
            if snapshot is None:
                raise ValueError(f"missing frozen basket market snapshot: {market}")
            if snapshot.received_at_ms > self.as_of_ms:
                raise ValueError(f"future-received market snapshot: {market}")
            candles = self.candles_15m.get(market)
            if candles is None:
                raise ValueError(f"missing frozen basket 15m candles: {market}")
        if not self.hype_candles_1h:
            raise ValueError("HYPE 1h candles must not be empty")


@dataclass(frozen=True, slots=True)
class ProspectiveObservationResult:
    status: str
    as_of_ms: int
    anchor_end_ms: int | None
    raw_direction: Direction | None
    effective_direction: Direction | None
    context_state_1h: str | None
    observation_id: str | None
    created: bool

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if not self.status.strip():
            raise ValueError("status must not be empty")


@dataclass(frozen=True, slots=True)
class ProspectiveSettlementResult:
    settled: tuple[ProspectiveOutcome, ...]
    missing_target_observation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProspectiveObserverCycleResult:
    observation: ProspectiveObservationResult
    settlements: ProspectiveSettlementResult


def _latest_closed(
    candles: Sequence[Candle],
    *,
    market: MarketId,
    interval: str,
    as_of_ms: int,
) -> Candle:
    eligible = tuple(
        candle
        for candle in candles
        if candle.market == market
        and candle.interval == interval
        and candle.end_ms <= as_of_ms
        and candle.received_at_ms <= as_of_ms
    )
    if not eligible:
        raise ProspectiveObserverError(
            f"no closed {interval} candle available for {market.canonical}"
        )
    return max(eligible, key=lambda candle: (candle.end_ms, candle.start_ms))


def _feature_snapshots(
    data: ProspectiveMarketData,
    *,
    anchor_end_ms: int,
) -> tuple[FeatureSnapshot, ...]:
    features: list[FeatureSnapshot] = []
    for canonical in FROZEN_CONTEXT_BASKET:
        market_snapshot = data.markets[canonical]
        market = market_snapshot.meta.market
        if market.canonical != canonical or market_snapshot.context.market != market:
            raise ProspectiveObserverError(f"market snapshot identity mismatch: {canonical}")
        if market_snapshot.meta.is_delisted:
            raise ProspectiveObserverError(f"frozen basket market is delisted: {canonical}")

        candles = data.candles_15m[canonical]
        latest = _latest_closed(
            candles,
            market=market,
            interval="15m",
            as_of_ms=data.as_of_ms,
        )
        if latest.end_ms != anchor_end_ms:
            raise ProspectiveObserverError(
                f"frozen basket anchor mismatch for {canonical}: "
                f"{latest.end_ms} != {anchor_end_ms}"
            )

        broad = calculate_broad_features(
            market_snapshot,
            None,
            as_of_ms=data.as_of_ms,
        )
        candle_values = calculate_candle_features(
            market,
            candles_15m=candles,
            as_of_ms=data.as_of_ms,
        )
        if candle_values.return_1h is None:
            raise ProspectiveObserverError(
                f"missing 1h return for frozen basket market: {canonical}"
            )
        features.append(
            assemble_feature_snapshot(
                market,
                broad,
                candle=candle_values,
                as_of_ms=data.as_of_ms,
                provenance=tuple(
                    sorted(
                        {
                            market_snapshot.source,
                            *(candle.source for candle in candles),
                        }
                    )
                ),
            )
        )
    return tuple(features)


def _hype_context(
    features: Sequence[FeatureSnapshot],
) -> tuple[FeatureSnapshot, CrossMarketContextSnapshot]:
    contexts = build_cross_market_contexts(features)
    feature = next((item for item in features if item.market.canonical == "HYPE"), None)
    context = next((item for item in contexts if item.market.canonical == "HYPE"), None)
    if feature is None or context is None:
        raise ProspectiveObserverError("HYPE missing from frozen basket context")
    return feature, context


def observe_current_anchor(
    data: ProspectiveMarketData,
    *,
    store: ProspectiveEvidenceStore,
    spec: HistoricalDiscoveryFreezeSpec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
) -> ProspectiveObservationResult:
    if store.spec.spec_id != spec.spec_id:
        raise ValueError("prospective store does not match frozen spec")
    if data.as_of_ms < spec.validation_not_before_ms:
        return ProspectiveObservationResult(
            status="before_prospective_cutover",
            as_of_ms=data.as_of_ms,
            anchor_end_ms=None,
            raw_direction=None,
            effective_direction=None,
            context_state_1h=None,
            observation_id=None,
            created=False,
        )

    entry = _latest_closed(
        data.hype_candles_1h,
        market=spec.market,
        interval=spec.anchor_interval,
        as_of_ms=data.as_of_ms,
    )
    if entry.end_ms < spec.validation_not_before_ms:
        return ProspectiveObservationResult(
            status="waiting_for_post_cutover_anchor",
            as_of_ms=data.as_of_ms,
            anchor_end_ms=entry.end_ms,
            raw_direction=None,
            effective_direction=None,
            context_state_1h=None,
            observation_id=None,
            created=False,
        )

    existing = store.observation_for_anchor(entry.end_ms)
    if existing is not None:
        return ProspectiveObservationResult(
            status="already_recorded",
            as_of_ms=data.as_of_ms,
            anchor_end_ms=existing.anchor_end_ms,
            raw_direction=existing.raw_direction,
            effective_direction=existing.effective_direction,
            context_state_1h=existing.context_state_1h,
            observation_id=existing.observation_id,
            created=False,
        )

    hype_15m = _latest_closed(
        data.candles_15m["HYPE"],
        market=spec.market,
        interval="15m",
        as_of_ms=data.as_of_ms,
    )
    if hype_15m.close_px != entry.close_px:
        raise ProspectiveObserverError(
            "HYPE 15m and 1h closes disagree at prospective anchor"
        )

    features = _feature_snapshots(data, anchor_end_ms=entry.end_ms)
    hype_feature, hype_context = _hype_context(features)
    raw_decision = evaluate_prospective_context_candidate(
        spec,
        feature=hype_feature,
        cross_market=hype_context,
    )
    observation = build_prospective_observation(
        spec,
        raw_decision=raw_decision,
        entry_candle=entry,
        prior_observations=store.iter_observations(),
    )
    store.record_observation(observation)
    return ProspectiveObservationResult(
        status="recorded",
        as_of_ms=data.as_of_ms,
        anchor_end_ms=observation.anchor_end_ms,
        raw_direction=observation.raw_direction,
        effective_direction=observation.effective_direction,
        context_state_1h=observation.context_state_1h,
        observation_id=observation.observation_id,
        created=True,
    )


def settle_due_observations(
    *,
    store: ProspectiveEvidenceStore,
    candles_1h: Sequence[Candle],
    as_of_ms: int,
    spec: HistoricalDiscoveryFreezeSpec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
) -> ProspectiveSettlementResult:
    if store.spec.spec_id != spec.spec_id:
        raise ValueError("prospective store does not match frozen spec")
    due = store.due_unsettled_observations(as_of_ms=as_of_ms)
    by_end: dict[int, Candle] = {}
    for candle in candles_1h:
        if candle.market != spec.market or candle.interval != spec.anchor_interval:
            raise ValueError("settlement candles must be frozen HYPE 1h candles")
        if candle.received_at_ms > as_of_ms:
            raise ValueError("settlement candle was received after as_of_ms")
        if candle.end_ms in by_end:
            raise ProspectiveObserverError(
                f"duplicate HYPE settlement candle end: {candle.end_ms}"
            )
        by_end[candle.end_ms] = candle

    settled: list[ProspectiveOutcome] = []
    missing: list[str] = []
    for observation in due:
        candle = by_end.get(observation.target_end_ms)
        if candle is None:
            missing.append(observation.observation_id)
            continue
        outcome = build_prospective_outcome(
            spec,
            observation=observation,
            exit_candle=candle,
        )
        store.record_outcome(outcome)
        settled.append(outcome)

    return ProspectiveSettlementResult(
        settled=tuple(settled),
        missing_target_observation_ids=tuple(missing),
    )


def collect_current_market_data(
    reader: ProspectivePublicReader,
    *,
    clock_ms: Callable[[], int],
) -> ProspectiveMarketData:
    raw_markets = reader.meta_and_asset_ctxs("")
    market_received_at_ms = clock_ms()
    snapshots = normalize_meta_and_asset_ctxs(
        "",
        raw_markets,
        received_at_ms=market_received_at_ms,
    )
    by_market = {item.meta.market.canonical: item for item in snapshots}

    now_ms = clock_ms()
    candles_15m: dict[str, tuple[Candle, ...]] = {}
    for canonical in FROZEN_CONTEXT_BASKET:
        market = MarketId("", canonical)
        raw = reader.candles(
            market,
            "15m",
            start_ms=max(0, now_ms - FEATURE_LOOKBACK_MS),
            end_ms=now_ms,
        )
        received_at_ms = clock_ms()
        candles_15m[canonical] = normalize_candles(
            market,
            raw,
            received_at_ms=received_at_ms,
        )

    raw_hype_1h = reader.candles(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.market,
        "1h",
        start_ms=max(0, now_ms - CURRENT_1H_LOOKBACK_MS),
        end_ms=now_ms,
    )
    hype_received_at_ms = clock_ms()
    hype_candles_1h = normalize_candles(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.market,
        raw_hype_1h,
        received_at_ms=hype_received_at_ms,
    )
    as_of_ms = clock_ms()

    return ProspectiveMarketData(
        as_of_ms=as_of_ms,
        markets=by_market,
        candles_15m=candles_15m,
        hype_candles_1h=hype_candles_1h,
    )


def collect_settlement_candles(
    reader: ProspectivePublicReader,
    *,
    due: Sequence[ProspectiveObservation],
    as_of_ms: int,
    clock_ms: Callable[[], int],
    spec: HistoricalDiscoveryFreezeSpec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
) -> tuple[Candle, ...]:
    if not due:
        return ()
    start_ms = max(0, min(item.target_end_ms for item in due) - HOUR_MS)
    end_ms = max(item.target_end_ms for item in due)
    raw = reader.candles(
        spec.market,
        spec.anchor_interval,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    return normalize_candles(
        spec.market,
        raw,
        received_at_ms=clock_ms(),
    )


def run_prospective_observer_cycle(
    reader: ProspectivePublicReader,
    *,
    store: ProspectiveEvidenceStore,
    clock_ms: Callable[[], int],
    spec: HistoricalDiscoveryFreezeSpec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
) -> ProspectiveObserverCycleResult:
    current = collect_current_market_data(reader, clock_ms=clock_ms)
    observation = observe_current_anchor(current, store=store, spec=spec)

    settle_as_of_ms = clock_ms()
    due = store.due_unsettled_observations(as_of_ms=settle_as_of_ms)
    settlement_candles = collect_settlement_candles(
        reader,
        due=due,
        as_of_ms=settle_as_of_ms,
        clock_ms=clock_ms,
        spec=spec,
    )
    settlements = settle_due_observations(
        store=store,
        candles_1h=settlement_candles,
        as_of_ms=clock_ms(),
        spec=spec,
    )
    return ProspectiveObserverCycleResult(
        observation=observation,
        settlements=settlements,
    )
