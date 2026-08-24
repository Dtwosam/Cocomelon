from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.features import EligibilityDecision, FeatureSnapshot
from cocomelon.domain.market import MarketId, PerpMarketContext, PerpMarketSnapshot
from cocomelon.domain.replay import ReplayRecord
from cocomelon.domain.strategy import StrategyContext, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.baseline import RecordedMarketState, RecordedStateBook
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import BroadFeatureValues, calculate_broad_features
from cocomelon.features.candles import calculate_candle_features
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.features.regime import assign_volatility_regimes
from cocomelon.scanner.eligibility import (
    derive_eligibility_thresholds,
    evaluate_eligibility,
)
from cocomelon.strategies.engine import evaluate_strategies
from cocomelon.strategies.microstructure import build_microstructure_window

DECISION_INTERVAL_MS = 15 * 60 * 1_000


@dataclass(frozen=True, slots=True)
class EpochMarketEvaluation:
    feature: FeatureSnapshot
    eligibility: EligibilityDecision
    decision: StrategyDecision


@dataclass(frozen=True, slots=True)
class DecisionEpoch:
    boundary_ms: int
    evaluated_at_ms: int
    markets: tuple[EpochMarketEvaluation, ...]

    def __post_init__(self) -> None:
        if self.boundary_ms < 0 or self.evaluated_at_ms < 0:
            raise ValueError("epoch timestamps must be non-negative")
        if self.evaluated_at_ms < self.boundary_ms:
            raise ValueError("evaluated_at_ms must be >= boundary_ms")
        ordered = tuple(
            sorted(self.markets, key=lambda item: item.feature.market.canonical)
        )
        keys = tuple(item.feature.market.canonical for item in ordered)
        if len(set(keys)) != len(keys):
            raise ValueError("decision epoch contains duplicate markets")
        object.__setattr__(self, "markets", ordered)


def _event_receive_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1_000)


def _payload_decimal(event: StreamEvent, key: str) -> Decimal:
    value = event.payload.get(key)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{key} must be a finite Decimal")
    return value


def _payload_optional_decimal(event: StreamEvent, key: str) -> Decimal | None:
    value = event.payload.get(key)
    if value is None:
        return None
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{key} must be a finite Decimal or None")
    return value


def _effective_snapshot(
    state: RecordedMarketState,
    *,
    as_of_ms: int,
) -> PerpMarketSnapshot | None:
    base = state.latest_snapshot
    if base is None or base.received_at_ms > as_of_ms:
        return None

    event = state.latest_asset_ctx
    if event is None or event.kind is not StreamKind.ACTIVE_ASSET_CTX:
        return base
    received_at_ms = _event_receive_ms(event)
    if received_at_ms > as_of_ms or received_at_ms < base.received_at_ms:
        return base

    mid_px = _payload_optional_decimal(event, "mid_px")
    context = PerpMarketContext(
        market=state.market,
        mark_px=_payload_decimal(event, "mark_px"),
        mid_px=base.context.mid_px if mid_px is None else mid_px,
        oracle_px=_payload_decimal(event, "oracle_px"),
        funding=_payload_decimal(event, "funding"),
        open_interest=_payload_decimal(event, "open_interest"),
        day_ntl_vlm=base.context.day_ntl_vlm,
        premium=base.context.premium,
        prev_day_px=base.context.prev_day_px,
    )
    return PerpMarketSnapshot(
        meta=base.meta,
        context=context,
        source=event.source,
        received_at_ms=received_at_ms,
        schema_version=max(base.schema_version, event.schema_version),
    )


def _initial_boundary(available_at_ms: int, grace_ms: int) -> int:
    floor = available_at_ms // DECISION_INTERVAL_MS * DECISION_INTERVAL_MS
    if available_at_ms <= floor + grace_ms:
        return floor
    return floor + DECISION_INTERVAL_MS


class BaselineDecisionEngine:
    def __init__(
        self,
        selected_markets: Sequence[MarketId],
        *,
        replay_config: BaselineReplayConfig,
    ) -> None:
        ordered = tuple(sorted(selected_markets, key=lambda market: market.canonical))
        if not ordered:
            raise ValueError("selected_markets must not be empty")
        keys = tuple(market.canonical for market in ordered)
        if len(set(keys)) != len(keys):
            raise ValueError("selected_markets contains duplicates")
        if replay_config.decision_interval != "15m":
            raise ValueError("baseline decision engine requires a 15m interval")

        self._markets = ordered
        self._config = replay_config
        self._state = RecordedStateBook(
            microstructure_window_ms=replay_config.microstructure_window_ms
        )
        self._next_boundary_ms: int | None = None
        self._last_available_at_ms: int | None = None

    @property
    def state_book(self) -> RecordedStateBook:
        return self._state

    def _feature_inputs(
        self,
        market: MarketId,
        *,
        as_of_ms: int,
    ) -> tuple[PerpMarketSnapshot, BroadFeatureValues, FeatureSnapshot] | None:
        state = self._state.state(market)
        snapshot = _effective_snapshot(state, as_of_ms=as_of_ms)
        if snapshot is None:
            return None

        previous = state.previous_snapshot
        if previous is not None and previous.received_at_ms > as_of_ms:
            previous = None
        broad = calculate_broad_features(snapshot, previous, as_of_ms=as_of_ms)

        candles_5m = tuple(
            state.candles_5m[key] for key in sorted(state.candles_5m)
        )
        candles_15m = tuple(
            state.candles_15m[key] for key in sorted(state.candles_15m)
        )
        candle = calculate_candle_features(
            market,
            candles_5m=candles_5m,
            candles_15m=candles_15m,
            as_of_ms=as_of_ms,
        )

        microstructure = None
        book = state.latest_book
        if (
            book is not None
            and _event_receive_ms(book) <= as_of_ms
            and book.exchange_time_ms is not None
            and book.exchange_time_ms <= as_of_ms
        ):
            microstructure = calculate_microstructure_features(book, as_of_ms=as_of_ms)

        provenance = {snapshot.source}
        if state.latest_snapshot is not None:
            provenance.add(state.latest_snapshot.source)
        provenance.update(item.source for item in candles_5m)
        provenance.update(item.source for item in candles_15m)
        if book is not None and _event_receive_ms(book) <= as_of_ms:
            provenance.add(book.source)
        for event in state.micro_events:
            if _event_receive_ms(event) <= as_of_ms:
                provenance.add(event.source)

        feature = assemble_feature_snapshot(
            market,
            broad,
            candle=candle,
            microstructure=microstructure,
            as_of_ms=as_of_ms,
            provenance=tuple(provenance),
        )
        return snapshot, broad, feature

    def _evaluate_epoch(self, boundary_ms: int) -> DecisionEpoch:
        evaluated_at_ms = boundary_ms + self._config.decision_grace_ms
        assembled: list[FeatureSnapshot] = []
        snapshots: dict[str, PerpMarketSnapshot] = {}

        for market in self._markets:
            inputs = self._feature_inputs(market, as_of_ms=evaluated_at_ms)
            if inputs is None:
                continue
            snapshot, _, feature = inputs
            snapshots[market.canonical] = snapshot
            assembled.append(feature)

        if not assembled:
            return DecisionEpoch(
                boundary_ms=boundary_ms,
                evaluated_at_ms=evaluated_at_ms,
                markets=(),
            )

        features = assign_volatility_regimes(assembled)
        thresholds = derive_eligibility_thresholds(features, self._config.eligibility)
        evaluations: list[EpochMarketEvaluation] = []

        for feature in features:
            market = feature.market
            state = self._state.state(market)
            snapshot = snapshots[market.canonical]
            eligibility = evaluate_eligibility(
                snapshot,
                feature,
                thresholds,
                self._config.eligibility,
            )
            candles_5m = tuple(
                state.candles_5m[key] for key in sorted(state.candles_5m)
            )
            candles_15m = tuple(
                state.candles_15m[key] for key in sorted(state.candles_15m)
            )
            events = tuple(
                event
                for event in state.micro_events
                if _event_receive_ms(event) <= evaluated_at_ms
            )
            microstructure = (
                None
                if not events
                else build_microstructure_window(
                    events,
                    market=market,
                    as_of_ms=evaluated_at_ms,
                    window_ms=self._config.microstructure_window_ms,
                )
            )
            decision = evaluate_strategies(
                StrategyContext(
                    market_snapshot=snapshot,
                    feature_snapshot=feature,
                    eligibility=eligibility,
                    candles_5m=candles_5m,
                    candles_15m=candles_15m,
                    microstructure=microstructure,
                    as_of_ms=evaluated_at_ms,
                )
            ).decision
            evaluations.append(
                EpochMarketEvaluation(
                    feature=feature,
                    eligibility=eligibility,
                    decision=decision,
                )
            )

        return DecisionEpoch(
            boundary_ms=boundary_ms,
            evaluated_at_ms=evaluated_at_ms,
            markets=tuple(evaluations),
        )

    def _emit_due(self, cutoff_ms: int, *, inclusive: bool) -> tuple[DecisionEpoch, ...]:
        emitted: list[DecisionEpoch] = []
        while self._next_boundary_ms is not None:
            evaluated_at_ms = self._next_boundary_ms + self._config.decision_grace_ms
            due = evaluated_at_ms <= cutoff_ms if inclusive else evaluated_at_ms < cutoff_ms
            if not due:
                break
            emitted.append(self._evaluate_epoch(self._next_boundary_ms))
            self._next_boundary_ms += DECISION_INTERVAL_MS
        return tuple(emitted)

    def observe(self, record: ReplayRecord, now_ms: int) -> tuple[DecisionEpoch, ...]:
        if now_ms < record.available_at_ms:
            raise ValueError("now_ms cannot precede record availability")
        if (
            self._last_available_at_ms is not None
            and record.available_at_ms < self._last_available_at_ms
        ):
            raise ValueError("baseline decision records must not regress in availability time")
        if self._next_boundary_ms is None:
            self._next_boundary_ms = _initial_boundary(
                record.available_at_ms,
                self._config.decision_grace_ms,
            )

        emitted = self._emit_due(record.available_at_ms, inclusive=False)
        self._state.apply(record, now_ms)
        self._last_available_at_ms = record.available_at_ms
        return emitted

    def flush(self, end_ms: int) -> tuple[DecisionEpoch, ...]:
        if end_ms < 0:
            raise ValueError("end_ms must be non-negative")
        if self._last_available_at_ms is not None and end_ms < self._last_available_at_ms:
            raise ValueError("flush end_ms cannot precede observed evidence")
        return self._emit_due(end_ms, inclusive=True)
