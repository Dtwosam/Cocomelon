from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    TrendRegime,
    VolatilityRegime,
)
from cocomelon.domain.market import (
    Candle,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.domain.replay import ReplayRecord
from cocomelon.domain.strategy import (
    Direction,
    MicrostructureWindow,
    StrategyContext,
    StrategyDecision,
)
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.epochs import (
    DECISION_INTERVAL_MS,
    DecisionEpoch,
    EpochMarketEvaluation,
    _effective_snapshot,
)
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.features.candles import calculate_candle_features
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.features.regime import assign_volatility_regimes
from cocomelon.replay.source import JsonlReplaySource, validate_recording
from cocomelon.scanner.eligibility import (
    derive_eligibility_thresholds,
    evaluate_eligibility,
)
from cocomelon.strategies.microstructure import build_microstructure_window

StrategyEvaluator = Callable[[dict[str, object]], dict[str, object]]


@dataclass(frozen=True, slots=True)
class ResearchStrategyContextRecord:
    boundary_ms: int
    evaluated_at_ms: int
    context: StrategyContext


@dataclass(frozen=True, slots=True)
class ResearchStrategyContextEpoch:
    boundary_ms: int
    evaluated_at_ms: int
    contexts: tuple[ResearchStrategyContextRecord, ...]


@dataclass(frozen=True, slots=True)
class CandidateStrategyDecisionArtifact:
    candidate_code_revision: str
    candidate_config_digest: str
    recording_session_digest: str
    source_set_digest: str
    contexts_digest: str
    decisions: tuple[dict[str, object], ...]


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a canonical decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not resolved.is_finite():
        raise ValueError(f"{field} must be finite")
    return resolved


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _market_payload(market: MarketId) -> dict[str, object]:
    return {"coin": market.coin, "dex": market.dex}


def _market(value: object, field: str) -> MarketId:
    raw = _mapping(value, field)
    coin = _string(raw.get("coin"), f"{field}.coin")
    dex_value = raw.get("dex")
    if not isinstance(dex_value, str):
        raise ValueError(f"{field}.dex must be a string")
    return MarketId(dex=dex_value, coin=coin)


def _meta_payload(meta: PerpMarketMeta) -> dict[str, object]:
    return {
        "is_delisted": meta.is_delisted,
        "margin_mode": meta.margin_mode,
        "margin_table_id": meta.margin_table_id,
        "market": _market_payload(meta.market),
        "max_leverage": meta.max_leverage,
        "only_isolated": meta.only_isolated,
        "sz_decimals": meta.sz_decimals,
        "wire_name": meta.wire_name,
    }


def _meta(value: object) -> PerpMarketMeta:
    raw = _mapping(value, "market_snapshot.meta")
    margin_mode = raw.get("margin_mode")
    if margin_mode is not None and not isinstance(margin_mode, str):
        raise ValueError("market_snapshot.meta.margin_mode must be a string or null")
    return PerpMarketMeta(
        market=_market(raw.get("market"), "market_snapshot.meta.market"),
        wire_name=_string(raw.get("wire_name"), "market_snapshot.meta.wire_name"),
        sz_decimals=_integer(raw.get("sz_decimals"), "market_snapshot.meta.sz_decimals"),
        max_leverage=_integer(raw.get("max_leverage"), "market_snapshot.meta.max_leverage"),
        margin_table_id=_optional_integer(
            raw.get("margin_table_id"),
            "market_snapshot.meta.margin_table_id",
        ),
        only_isolated=_boolean(
            raw.get("only_isolated"),
            "market_snapshot.meta.only_isolated",
        ),
        is_delisted=_boolean(raw.get("is_delisted"), "market_snapshot.meta.is_delisted"),
        margin_mode=margin_mode,
    )


def _market_context_payload(context: PerpMarketContext) -> dict[str, object]:
    return {
        "day_ntl_vlm": str(context.day_ntl_vlm),
        "funding": str(context.funding),
        "mark_px": None if context.mark_px is None else str(context.mark_px),
        "market": _market_payload(context.market),
        "mid_px": None if context.mid_px is None else str(context.mid_px),
        "open_interest": str(context.open_interest),
        "oracle_px": None if context.oracle_px is None else str(context.oracle_px),
        "premium": None if context.premium is None else str(context.premium),
        "prev_day_px": str(context.prev_day_px),
    }


def _market_context(value: object) -> PerpMarketContext:
    raw = _mapping(value, "market_snapshot.context")
    return PerpMarketContext(
        market=_market(raw.get("market"), "market_snapshot.context.market"),
        mark_px=_optional_decimal(raw.get("mark_px"), "market_snapshot.context.mark_px"),
        mid_px=_optional_decimal(raw.get("mid_px"), "market_snapshot.context.mid_px"),
        oracle_px=_optional_decimal(
            raw.get("oracle_px"),
            "market_snapshot.context.oracle_px",
        ),
        funding=_decimal(raw.get("funding"), "market_snapshot.context.funding"),
        open_interest=_decimal(
            raw.get("open_interest"),
            "market_snapshot.context.open_interest",
        ),
        day_ntl_vlm=_decimal(
            raw.get("day_ntl_vlm"),
            "market_snapshot.context.day_ntl_vlm",
        ),
        premium=_optional_decimal(raw.get("premium"), "market_snapshot.context.premium"),
        prev_day_px=_decimal(
            raw.get("prev_day_px"),
            "market_snapshot.context.prev_day_px",
        ),
    )


def _snapshot_payload(snapshot: PerpMarketSnapshot) -> dict[str, object]:
    return {
        "context": _market_context_payload(snapshot.context),
        "meta": _meta_payload(snapshot.meta),
        "received_at_ms": snapshot.received_at_ms,
        "schema_version": snapshot.schema_version,
        "source": snapshot.source,
    }


def _snapshot(value: object) -> PerpMarketSnapshot:
    raw = _mapping(value, "market_snapshot")
    return PerpMarketSnapshot(
        meta=_meta(raw.get("meta")),
        context=_market_context(raw.get("context")),
        source=_string(raw.get("source"), "market_snapshot.source"),
        received_at_ms=_integer(
            raw.get("received_at_ms"),
            "market_snapshot.received_at_ms",
        ),
        schema_version=_integer(
            raw.get("schema_version"),
            "market_snapshot.schema_version",
        ),
    )


def _feature_payload(feature: FeatureSnapshot) -> dict[str, object]:
    decimal_fields = (
        "day_return",
        "funding",
        "open_interest",
        "day_notional_volume",
        "oi_change_fraction",
        "funding_change",
        "mark_oracle_dislocation_bps",
        "return_5m",
        "return_15m",
        "return_1h",
        "return_4h",
        "realized_vol_15m",
        "range_expansion_15m",
        "relative_volume_15m",
        "spread_bps",
        "bid_depth_25bps",
        "ask_depth_25bps",
        "book_imbalance",
    )
    payload: dict[str, object] = {
        "as_of_ms": feature.as_of_ms,
        "book_age_ms": feature.book_age_ms,
        "market": _market_payload(feature.market),
        "provenance": list(feature.provenance),
        "schema_version": feature.schema_version,
        "source_received_at_ms": feature.source_received_at_ms,
        "trend_regime": feature.trend_regime.value,
        "volatility_regime": feature.volatility_regime.value,
    }
    for field in decimal_fields:
        value = getattr(feature, field)
        payload[field] = None if value is None else str(value)
    return payload


def _feature(value: object) -> FeatureSnapshot:
    raw = _mapping(value, "feature_snapshot")
    provenance = _list(raw.get("provenance"), "feature_snapshot.provenance")
    if not all(isinstance(item, str) and item.strip() for item in provenance):
        raise ValueError("feature_snapshot.provenance must contain non-empty strings")
    return FeatureSnapshot(
        market=_market(raw.get("market"), "feature_snapshot.market"),
        as_of_ms=_integer(raw.get("as_of_ms"), "feature_snapshot.as_of_ms"),
        source_received_at_ms=_integer(
            raw.get("source_received_at_ms"),
            "feature_snapshot.source_received_at_ms",
        ),
        schema_version=_integer(
            raw.get("schema_version"),
            "feature_snapshot.schema_version",
        ),
        day_return=_optional_decimal(raw.get("day_return"), "feature_snapshot.day_return"),
        funding=_decimal(raw.get("funding"), "feature_snapshot.funding"),
        open_interest=_decimal(raw.get("open_interest"), "feature_snapshot.open_interest"),
        day_notional_volume=_decimal(
            raw.get("day_notional_volume"),
            "feature_snapshot.day_notional_volume",
        ),
        oi_change_fraction=_optional_decimal(
            raw.get("oi_change_fraction"),
            "feature_snapshot.oi_change_fraction",
        ),
        funding_change=_optional_decimal(
            raw.get("funding_change"),
            "feature_snapshot.funding_change",
        ),
        mark_oracle_dislocation_bps=_optional_decimal(
            raw.get("mark_oracle_dislocation_bps"),
            "feature_snapshot.mark_oracle_dislocation_bps",
        ),
        return_5m=_optional_decimal(raw.get("return_5m"), "feature_snapshot.return_5m"),
        return_15m=_optional_decimal(raw.get("return_15m"), "feature_snapshot.return_15m"),
        return_1h=_optional_decimal(raw.get("return_1h"), "feature_snapshot.return_1h"),
        return_4h=_optional_decimal(raw.get("return_4h"), "feature_snapshot.return_4h"),
        realized_vol_15m=_optional_decimal(
            raw.get("realized_vol_15m"),
            "feature_snapshot.realized_vol_15m",
        ),
        range_expansion_15m=_optional_decimal(
            raw.get("range_expansion_15m"),
            "feature_snapshot.range_expansion_15m",
        ),
        relative_volume_15m=_optional_decimal(
            raw.get("relative_volume_15m"),
            "feature_snapshot.relative_volume_15m",
        ),
        spread_bps=_optional_decimal(raw.get("spread_bps"), "feature_snapshot.spread_bps"),
        bid_depth_25bps=_optional_decimal(
            raw.get("bid_depth_25bps"),
            "feature_snapshot.bid_depth_25bps",
        ),
        ask_depth_25bps=_optional_decimal(
            raw.get("ask_depth_25bps"),
            "feature_snapshot.ask_depth_25bps",
        ),
        book_imbalance=_optional_decimal(
            raw.get("book_imbalance"),
            "feature_snapshot.book_imbalance",
        ),
        book_age_ms=_optional_integer(
            raw.get("book_age_ms"),
            "feature_snapshot.book_age_ms",
        ),
        trend_regime=TrendRegime(
            _string(raw.get("trend_regime"), "feature_snapshot.trend_regime")
        ),
        volatility_regime=VolatilityRegime(
            _string(
                raw.get("volatility_regime"),
                "feature_snapshot.volatility_regime",
            )
        ),
        provenance=tuple(str(item) for item in provenance),
    )


def _eligibility_payload(decision: EligibilityDecision) -> dict[str, object]:
    return {
        "deep_ready": decision.deep_ready,
        "market": _market_payload(decision.market),
        "rankable": decision.rankable,
        "reasons": list(decision.reasons),
    }


def _eligibility(value: object) -> EligibilityDecision:
    raw = _mapping(value, "eligibility")
    reasons = _list(raw.get("reasons"), "eligibility.reasons")
    if not all(isinstance(item, str) for item in reasons):
        raise ValueError("eligibility.reasons must contain strings")
    return EligibilityDecision(
        market=_market(raw.get("market"), "eligibility.market"),
        rankable=_boolean(raw.get("rankable"), "eligibility.rankable"),
        deep_ready=_boolean(raw.get("deep_ready"), "eligibility.deep_ready"),
        reasons=tuple(str(item) for item in reasons),
    )


def _candle_payload(candle: Candle) -> dict[str, object]:
    return {
        "close_px": str(candle.close_px),
        "end_ms": candle.end_ms,
        "high_px": str(candle.high_px),
        "interval": candle.interval,
        "low_px": str(candle.low_px),
        "market": _market_payload(candle.market),
        "open_px": str(candle.open_px),
        "received_at_ms": candle.received_at_ms,
        "schema_version": candle.schema_version,
        "source": candle.source,
        "start_ms": candle.start_ms,
        "trade_count": candle.trade_count,
        "volume": str(candle.volume),
    }


def _candle(value: object, field: str) -> Candle:
    raw = _mapping(value, field)
    return Candle(
        market=_market(raw.get("market"), f"{field}.market"),
        interval=_string(raw.get("interval"), f"{field}.interval"),
        start_ms=_integer(raw.get("start_ms"), f"{field}.start_ms"),
        end_ms=_integer(raw.get("end_ms"), f"{field}.end_ms"),
        open_px=_decimal(raw.get("open_px"), f"{field}.open_px"),
        high_px=_decimal(raw.get("high_px"), f"{field}.high_px"),
        low_px=_decimal(raw.get("low_px"), f"{field}.low_px"),
        close_px=_decimal(raw.get("close_px"), f"{field}.close_px"),
        volume=_decimal(raw.get("volume"), f"{field}.volume"),
        trade_count=_integer(raw.get("trade_count"), f"{field}.trade_count"),
        source=_string(raw.get("source"), f"{field}.source"),
        received_at_ms=_integer(
            raw.get("received_at_ms"),
            f"{field}.received_at_ms",
        ),
        schema_version=_integer(
            raw.get("schema_version"),
            f"{field}.schema_version",
        ),
    )


def _microstructure_payload(window: MicrostructureWindow | None) -> object:
    if window is None:
        return None
    return {
        "as_of_ms": window.as_of_ms,
        "book_imbalance_change": (
            None if window.book_imbalance_change is None else str(window.book_imbalance_change)
        ),
        "buy_notional": str(window.buy_notional),
        "event_keys": list(window.event_keys),
        "latest_book_imbalance": (
            None if window.latest_book_imbalance is None else str(window.latest_book_imbalance)
        ),
        "latest_event_age_ms": window.latest_event_age_ms,
        "market": _market_payload(window.market),
        "sell_notional": str(window.sell_notional),
        "start_ms": window.start_ms,
        "trade_count": window.trade_count,
        "trade_flow_imbalance": (
            None if window.trade_flow_imbalance is None else str(window.trade_flow_imbalance)
        ),
    }


def _microstructure(value: object) -> MicrostructureWindow | None:
    if value is None:
        return None
    raw = _mapping(value, "microstructure")
    event_keys = _list(raw.get("event_keys"), "microstructure.event_keys")
    if not all(isinstance(item, str) and item.strip() for item in event_keys):
        raise ValueError("microstructure.event_keys must contain non-empty strings")
    return MicrostructureWindow(
        market=_market(raw.get("market"), "microstructure.market"),
        start_ms=_integer(raw.get("start_ms"), "microstructure.start_ms"),
        as_of_ms=_integer(raw.get("as_of_ms"), "microstructure.as_of_ms"),
        trade_count=_integer(raw.get("trade_count"), "microstructure.trade_count"),
        buy_notional=_decimal(raw.get("buy_notional"), "microstructure.buy_notional"),
        sell_notional=_decimal(raw.get("sell_notional"), "microstructure.sell_notional"),
        trade_flow_imbalance=_optional_decimal(
            raw.get("trade_flow_imbalance"),
            "microstructure.trade_flow_imbalance",
        ),
        latest_book_imbalance=_optional_decimal(
            raw.get("latest_book_imbalance"),
            "microstructure.latest_book_imbalance",
        ),
        book_imbalance_change=_optional_decimal(
            raw.get("book_imbalance_change"),
            "microstructure.book_imbalance_change",
        ),
        latest_event_age_ms=_optional_integer(
            raw.get("latest_event_age_ms"),
            "microstructure.latest_event_age_ms",
        ),
        event_keys=tuple(str(item) for item in event_keys),
    )


def strategy_context_to_payload(context: StrategyContext) -> dict[str, object]:
    return {
        "as_of_ms": context.as_of_ms,
        "candles_15m": [_candle_payload(item) for item in context.candles_15m],
        "candles_5m": [_candle_payload(item) for item in context.candles_5m],
        "eligibility": _eligibility_payload(context.eligibility),
        "feature_snapshot": _feature_payload(context.feature_snapshot),
        "market_snapshot": _snapshot_payload(context.market_snapshot),
        "microstructure": _microstructure_payload(context.microstructure),
    }


def strategy_context_from_payload(value: object) -> StrategyContext:
    raw = _mapping(value, "strategy context")
    candles_5m = _list(raw.get("candles_5m"), "strategy context candles_5m")
    candles_15m = _list(raw.get("candles_15m"), "strategy context candles_15m")
    return StrategyContext(
        market_snapshot=_snapshot(raw.get("market_snapshot")),
        feature_snapshot=_feature(raw.get("feature_snapshot")),
        eligibility=_eligibility(raw.get("eligibility")),
        candles_5m=tuple(
            _candle(item, f"strategy context candles_5m[{index}]")
            for index, item in enumerate(candles_5m)
        ),
        candles_15m=tuple(
            _candle(item, f"strategy context candles_15m[{index}]")
            for index, item in enumerate(candles_15m)
        ),
        microstructure=_microstructure(raw.get("microstructure")),
        as_of_ms=_integer(raw.get("as_of_ms"), "strategy context as_of_ms"),
    )


def strategy_decision_to_payload(decision: StrategyDecision) -> dict[str, object]:
    return {
        "direction": decision.direction.value,
        "feature_snapshot_id": decision.feature_snapshot_id,
        "invalidation_price": (
            None if decision.invalidation_price is None else str(decision.invalidation_price)
        ),
        "lead_strategy": decision.lead_strategy,
        "market": _market_payload(decision.market),
        "reason_codes": list(decision.reason_codes),
        "score": str(decision.score),
        "signal_ids": list(decision.signal_ids),
        "timestamp_ms": decision.timestamp_ms,
    }


def strategy_decision_from_payload(value: object) -> StrategyDecision:
    raw = _mapping(value, "strategy decision")
    signal_ids = _list(raw.get("signal_ids"), "strategy decision signal_ids")
    reasons = _list(raw.get("reason_codes"), "strategy decision reason_codes")
    if not all(isinstance(item, str) for item in (*signal_ids, *reasons)):
        raise ValueError("strategy decision identifiers must contain strings")
    return StrategyDecision(
        market=_market(raw.get("market"), "strategy decision market"),
        direction=Direction(_string(raw.get("direction"), "strategy decision direction")),
        score=_decimal(raw.get("score"), "strategy decision score"),
        timestamp_ms=_integer(raw.get("timestamp_ms"), "strategy decision timestamp_ms"),
        feature_snapshot_id=_string(
            raw.get("feature_snapshot_id"),
            "strategy decision feature_snapshot_id",
        ),
        lead_strategy=_optional_string(
            raw.get("lead_strategy"),
            "strategy decision lead_strategy",
        ),
        invalidation_price=_optional_decimal(
            raw.get("invalidation_price"),
            "strategy decision invalidation_price",
        ),
        signal_ids=tuple(str(item) for item in signal_ids),
        reason_codes=tuple(str(item) for item in reasons),
    )


def _initial_boundary(available_at_ms: int, grace_ms: int) -> int:
    floor = available_at_ms // DECISION_INTERVAL_MS * DECISION_INTERVAL_MS
    if available_at_ms <= floor + grace_ms:
        return floor
    return floor + DECISION_INTERVAL_MS


class ResearchStrategyContextEngine:
    def __init__(
        self,
        selected_markets: Sequence[MarketId],
        *,
        replay_config: BaselineReplayConfig,
    ) -> None:
        ordered = tuple(sorted(selected_markets, key=lambda market: market.canonical))
        if not ordered:
            raise ValueError("research strategy markets must not be empty")
        if len({market.canonical for market in ordered}) != len(ordered):
            raise ValueError("research strategy markets contain duplicates")
        if replay_config.decision_interval != "15m":
            raise ValueError("research strategy context engine requires 15m decisions")
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
    ) -> tuple[PerpMarketSnapshot, FeatureSnapshot, tuple[Candle, ...], tuple[Candle, ...]] | None:
        state = self._state.state(market)
        snapshot = _effective_snapshot(state, as_of_ms=as_of_ms)
        if snapshot is None:
            return None
        previous = state.previous_snapshot
        if previous is not None and previous.received_at_ms > as_of_ms:
            previous = None
        broad = calculate_broad_features(snapshot, previous, as_of_ms=as_of_ms)
        candles_5m = tuple(state.candles_5m[key] for key in sorted(state.candles_5m))
        candles_15m = tuple(state.candles_15m[key] for key in sorted(state.candles_15m))
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
            and int(book.receive_time.timestamp() * 1000) <= as_of_ms
            and book.exchange_time_ms is not None
            and book.exchange_time_ms <= as_of_ms
        ):
            microstructure = calculate_microstructure_features(book, as_of_ms=as_of_ms)
        provenance = {snapshot.source}
        if state.latest_snapshot is not None:
            provenance.add(state.latest_snapshot.source)
        provenance.update(item.source for item in candles_5m)
        provenance.update(item.source for item in candles_15m)
        if book is not None and int(book.receive_time.timestamp() * 1000) <= as_of_ms:
            provenance.add(book.source)
        provenance.update(
            event.source
            for event in state.micro_events
            if int(event.receive_time.timestamp() * 1000) <= as_of_ms
        )
        feature = assemble_feature_snapshot(
            market,
            broad,
            candle=candle,
            microstructure=microstructure,
            as_of_ms=as_of_ms,
            provenance=tuple(provenance),
        )
        return snapshot, feature, candles_5m, candles_15m

    def _evaluate_epoch(self, boundary_ms: int) -> ResearchStrategyContextEpoch:
        evaluated_at_ms = boundary_ms + self._config.decision_grace_ms
        inputs_by_market: dict[
            str,
            tuple[PerpMarketSnapshot, FeatureSnapshot, tuple[Candle, ...], tuple[Candle, ...]],
        ] = {}
        features: list[FeatureSnapshot] = []
        for market in self._markets:
            inputs = self._feature_inputs(market, as_of_ms=evaluated_at_ms)
            if inputs is None:
                continue
            inputs_by_market[market.canonical] = inputs
            features.append(inputs[1])
        if not features:
            return ResearchStrategyContextEpoch(boundary_ms, evaluated_at_ms, ())

        regime_features = assign_volatility_regimes(features)
        thresholds = derive_eligibility_thresholds(regime_features, self._config.eligibility)
        contexts: list[ResearchStrategyContextRecord] = []
        for feature in regime_features:
            snapshot, _, candles_5m, candles_15m = inputs_by_market[feature.market.canonical]
            state = self._state.state(feature.market)
            eligibility = evaluate_eligibility(
                snapshot,
                feature,
                thresholds,
                self._config.eligibility,
            )
            events = tuple(
                event
                for event in state.micro_events
                if int(event.receive_time.timestamp() * 1000) <= evaluated_at_ms
            )
            microstructure = (
                None
                if not events
                else build_microstructure_window(
                    events,
                    market=feature.market,
                    as_of_ms=evaluated_at_ms,
                    window_ms=self._config.microstructure_window_ms,
                )
            )
            context = StrategyContext(
                market_snapshot=snapshot,
                feature_snapshot=feature,
                eligibility=eligibility,
                candles_5m=candles_5m,
                candles_15m=candles_15m,
                microstructure=microstructure,
                as_of_ms=evaluated_at_ms,
            )
            contexts.append(
                ResearchStrategyContextRecord(
                    boundary_ms=boundary_ms,
                    evaluated_at_ms=evaluated_at_ms,
                    context=context,
                )
            )
        contexts.sort(key=lambda item: item.context.feature_snapshot.market.canonical)
        return ResearchStrategyContextEpoch(
            boundary_ms=boundary_ms,
            evaluated_at_ms=evaluated_at_ms,
            contexts=tuple(contexts),
        )

    def _emit_due(
        self,
        cutoff_ms: int,
        *,
        inclusive: bool,
    ) -> tuple[ResearchStrategyContextEpoch, ...]:
        emitted: list[ResearchStrategyContextEpoch] = []
        while self._next_boundary_ms is not None:
            evaluated_at_ms = self._next_boundary_ms + self._config.decision_grace_ms
            due = evaluated_at_ms <= cutoff_ms if inclusive else evaluated_at_ms < cutoff_ms
            if not due:
                break
            emitted.append(self._evaluate_epoch(self._next_boundary_ms))
            self._next_boundary_ms += DECISION_INTERVAL_MS
        return tuple(emitted)

    def observe(
        self,
        record: ReplayRecord,
        now_ms: int,
    ) -> tuple[ResearchStrategyContextEpoch, ...]:
        if now_ms < record.available_at_ms:
            raise ValueError("research strategy now_ms cannot precede record availability")
        if (
            self._last_available_at_ms is not None
            and record.available_at_ms < self._last_available_at_ms
        ):
            raise ValueError("research strategy records must not regress in availability time")
        if self._next_boundary_ms is None:
            self._next_boundary_ms = _initial_boundary(
                record.available_at_ms,
                self._config.decision_grace_ms,
            )
        emitted = self._emit_due(record.available_at_ms, inclusive=False)
        self._state.apply(record, now_ms)
        self._last_available_at_ms = record.available_at_ms
        return emitted

    def flush(self, end_ms: int) -> tuple[ResearchStrategyContextEpoch, ...]:
        if end_ms < 0:
            raise ValueError("research strategy end_ms must be non-negative")
        if self._last_available_at_ms is not None and end_ms < self._last_available_at_ms:
            raise ValueError("research strategy flush cannot precede observed evidence")
        return self._emit_due(end_ms, inclusive=True)


def _context_request(record: ResearchStrategyContextRecord) -> dict[str, object]:
    return {
        "boundary_ms": record.boundary_ms,
        "context": strategy_context_to_payload(record.context),
        "evaluated_at_ms": record.evaluated_at_ms,
    }


def _decision_record(
    record: ResearchStrategyContextRecord,
    decision: StrategyDecision,
) -> dict[str, object]:
    feature = record.context.feature_snapshot
    if decision.market != feature.market:
        raise ValueError("candidate decision market does not match trusted context")
    if decision.timestamp_ms != record.evaluated_at_ms:
        raise ValueError("candidate decision timestamp does not match trusted context")
    if decision.feature_snapshot_id != feature.snapshot_id:
        raise ValueError("candidate decision feature snapshot does not match trusted context")
    return {
        "boundary_ms": record.boundary_ms,
        "decision": strategy_decision_to_payload(decision),
        "evaluated_at_ms": record.evaluated_at_ms,
        "feature_snapshot_id": feature.snapshot_id,
        "market": feature.market.canonical,
    }


def _validate_sha(value: str, field: str) -> str:
    resolved = value.strip().lower()
    if len(resolved) != 40 or any(char not in "0123456789abcdef" for char in resolved):
        raise ValueError(f"{field} must be a 40-character commit SHA")
    return resolved


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")


def _context_records(
    *,
    recording_root: Path,
    bundle_path: Path,
) -> tuple[ResearchStrategyContextRecord, ...]:
    bundle = load_baseline_replay_bundle(bundle_path)
    if validate_recording(recording_root) != bundle.manifest.segments:
        raise ValueError("candidate strategy source does not match trusted replay bundle")
    from cocomelon.evidence.recording import load_recording_session

    session = load_recording_session(recording_root)
    if session is None or session.session_id != bundle.recording_session_digest:
        raise ValueError("candidate strategy recording does not match trusted replay bundle")
    engine = ResearchStrategyContextEngine(
        tuple(item.market for item in session.selected),
        replay_config=bundle.replay_config,
    )
    records: list[ResearchStrategyContextRecord] = []
    for replay_record in JsonlReplaySource(recording_root).iter_records(bundle.manifest):
        for epoch in engine.observe(replay_record, replay_record.available_at_ms):
            records.extend(epoch.contexts)
    for epoch in engine.flush(bundle.manifest.end_ms):
        records.extend(epoch.contexts)
    return tuple(records)


def build_candidate_strategy_decisions(
    *,
    recording_root: str | Path,
    bundle_path: str | Path,
    output_path: str | Path,
    candidate_code_revision: str,
    evaluator: StrategyEvaluator,
) -> CandidateStrategyDecisionArtifact:
    recording = Path(recording_root)
    bundle_file = Path(bundle_path)
    bundle = load_baseline_replay_bundle(bundle_file)
    records = _context_records(recording_root=recording, bundle_path=bundle_file)
    if not records:
        raise ValueError("trusted recording produced no candidate strategy contexts")

    decisions: list[dict[str, object]] = []
    context_payloads: list[dict[str, object]] = []
    for record in records:
        request = _context_request(record)
        context_payloads.append(request)
        raw_decision = evaluator(request)
        decision = strategy_decision_from_payload(raw_decision)
        decisions.append(_decision_record(record, decision))

    payload: dict[str, object] = {
        "candidate_code_revision": _validate_sha(
            candidate_code_revision,
            "candidate_code_revision",
        ),
        "candidate_config_digest": bundle.replay_config.config_digest,
        "contexts_digest": _canonical_digest(context_payloads),
        "decisions": decisions,
        "recording_session_digest": bundle.recording_session_digest,
        "schema_version": 1,
        "source_set_digest": bundle.source_set_digest,
    }
    _write_json(Path(output_path), payload)
    return load_candidate_strategy_decisions(Path(output_path), bundle_path=bundle_file)


def load_candidate_strategy_decisions(
    path: str | Path,
    *,
    bundle_path: str | Path,
) -> CandidateStrategyDecisionArtifact:
    target = Path(path)
    try:
        decoded: object = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("candidate strategy decisions must contain valid JSON") from exc
    raw = _mapping(decoded, "candidate strategy decisions")
    if raw.get("schema_version") != 1:
        raise ValueError("candidate strategy decisions schema version is invalid")
    bundle = load_baseline_replay_bundle(bundle_path)
    candidate_config_digest = _string(
        raw.get("candidate_config_digest"),
        "candidate strategy config digest",
    )
    if candidate_config_digest != bundle.replay_config.config_digest:
        raise ValueError("candidate strategy config does not match trusted replay bundle")
    recording_session_digest = _string(
        raw.get("recording_session_digest"),
        "candidate strategy recording session digest",
    )
    if recording_session_digest != bundle.recording_session_digest:
        raise ValueError("candidate strategy recording does not match trusted source")
    source_set_digest = _string(
        raw.get("source_set_digest"),
        "candidate strategy source set digest",
    )
    if source_set_digest != bundle.source_set_digest:
        raise ValueError("candidate strategy source set does not match trusted source")
    contexts_digest = _string(raw.get("contexts_digest"), "candidate strategy contexts digest")
    if len(contexts_digest) != 64:
        raise ValueError("candidate strategy contexts digest is invalid")
    raw_decisions = _list(raw.get("decisions"), "candidate strategy decisions")
    decisions = tuple(dict(_mapping(item, "candidate strategy decision")) for item in raw_decisions)
    return CandidateStrategyDecisionArtifact(
        candidate_code_revision=_validate_sha(
            _string(raw.get("candidate_code_revision"), "candidate strategy code revision"),
            "candidate strategy code revision",
        ),
        candidate_config_digest=candidate_config_digest,
        recording_session_digest=recording_session_digest,
        source_set_digest=source_set_digest,
        contexts_digest=contexts_digest,
        decisions=decisions,
    )


class CandidateDecisionEpochEngine:
    def __init__(
        self,
        selected_markets: Sequence[MarketId],
        *,
        replay_config: BaselineReplayConfig,
        artifact: CandidateStrategyDecisionArtifact,
    ) -> None:
        self._contexts = ResearchStrategyContextEngine(
            selected_markets,
            replay_config=replay_config,
        )
        self._artifact = artifact
        self._decisions: dict[tuple[int, str], dict[str, object]] = {}
        for item in artifact.decisions:
            boundary_ms = _integer(item.get("boundary_ms"), "candidate decision boundary_ms")
            market = _string(item.get("market"), "candidate decision market")
            key = (boundary_ms, market)
            if key in self._decisions:
                raise ValueError("candidate decision coverage contains a duplicate context")
            self._decisions[key] = item
        self._context_payloads: list[dict[str, object]] = []

    @property
    def state_book(self) -> RecordedStateBook:
        return self._contexts.state_book

    def _decision_epoch(self, epoch: ResearchStrategyContextEpoch) -> DecisionEpoch:
        evaluations: list[EpochMarketEvaluation] = []
        for record in epoch.contexts:
            request = _context_request(record)
            self._context_payloads.append(request)
            market = record.context.feature_snapshot.market.canonical
            key = (record.boundary_ms, market)
            item = self._decisions.pop(key, None)
            if item is None:
                raise ValueError("missing candidate decision for trusted strategy context")
            if (
                _integer(item.get("evaluated_at_ms"), "candidate decision evaluated_at_ms")
                != record.evaluated_at_ms
            ):
                raise ValueError(
                    "candidate decision evaluated_at_ms does not match trusted context"
                )
            feature_id = _string(
                item.get("feature_snapshot_id"),
                "candidate decision feature_snapshot_id",
            )
            if feature_id != record.context.feature_snapshot.snapshot_id:
                raise ValueError(
                    "candidate decision feature snapshot does not match trusted context"
                )
            decision = strategy_decision_from_payload(item.get("decision"))
            _decision_record(record, decision)
            evaluations.append(
                EpochMarketEvaluation(
                    feature=record.context.feature_snapshot,
                    eligibility=record.context.eligibility,
                    decision=decision,
                )
            )
        return DecisionEpoch(
            boundary_ms=epoch.boundary_ms,
            evaluated_at_ms=epoch.evaluated_at_ms,
            markets=tuple(evaluations),
        )

    def observe(self, record: ReplayRecord, now_ms: int) -> tuple[DecisionEpoch, ...]:
        return tuple(
            self._decision_epoch(epoch)
            for epoch in self._contexts.observe(record, now_ms)
        )

    def flush(self, end_ms: int) -> tuple[DecisionEpoch, ...]:
        epochs = tuple(
            self._decision_epoch(epoch)
            for epoch in self._contexts.flush(end_ms)
        )
        if self._decisions:
            raise ValueError("candidate decision coverage contains extra contexts")
        if _canonical_digest(self._context_payloads) != self._artifact.contexts_digest:
            raise ValueError("candidate decision coverage does not match trusted context stream")
        return epochs


class DockerStrategyEvaluator:
    def __init__(self, image: str, *, timeout_seconds: int = 30) -> None:
        self._image = _string(image, "candidate strategy image")
        if timeout_seconds <= 0:
            raise ValueError("candidate strategy timeout must be positive")
        self._timeout_seconds = timeout_seconds

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            self._image,
        ]
        try:
            completed = subprocess.run(
                command,
                input=_canonical_json(payload) + "\n",
                text=True,
                capture_output=True,
                check=False,
                timeout=self._timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("candidate strategy sandbox failed") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                "candidate strategy sandbox exited non-zero: "
                + completed.stderr.strip()[:500]
            )
        stdout = completed.stdout.strip()
        try:
            decoded: object = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("candidate strategy sandbox returned invalid JSON") from exc
        return dict(_mapping(decoded, "candidate strategy sandbox result"))
