from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from cocomelon.domain.features import FeatureSnapshot, OpportunityRank
from cocomelon.domain.market import Candle, FundingRate, MarketId, PerpMarketSnapshot
from cocomelon.evidence.contracts import (
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
)
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.hyperliquid.normalize import normalize_candles, normalize_funding_history
from cocomelon.hyperliquid.registry import MarketRegistry
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.scanner.eligibility import (
    EligibilityConfig,
    derive_eligibility_thresholds,
    evaluate_eligibility,
)
from cocomelon.scanner.ranker import rank_opportunities

FUNDING_BOOTSTRAP_LOOKBACK_MS = 24 * 60 * 60 * 1_000
SCORE_SCALE = Decimal("100")


class EvidenceInfoReader(Protocol):
    def perp_dexs(self) -> object: ...

    def meta_and_asset_ctxs(self, dex: str = "") -> object: ...

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object: ...

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class RecordingBootstrap:
    session: EvidenceRecordingSession
    snapshots: tuple[PerpMarketSnapshot, ...]
    candles: tuple[Candle, ...]
    funding_rates: tuple[FundingRate, ...]
    subscriptions: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class RecordedPublicEvent:
    kind: str
    market: MarketId
    source: str
    exchange_time_ms: int | None
    receive_time: datetime
    schema_version: int
    event_key: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("kind must not be empty")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if self.exchange_time_ms is not None and self.exchange_time_ms < 0:
            raise ValueError("exchange_time_ms must be non-negative")
        if self.receive_time.tzinfo is None or self.receive_time.utcoffset() is None:
            raise ValueError("receive_time must be timezone-aware")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if not self.event_key.strip():
            raise ValueError("event_key must not be empty")


def _received_at(received_at_ms: int) -> datetime:
    if received_at_ms < 0:
        raise ValueError("received_at_ms must be non-negative")
    return datetime.fromtimestamp(received_at_ms / 1000, tz=UTC)


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical mapping keys must be strings")
            normalized[key] = _canonical_value(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value type: {type(value).__name__}")


def _payload_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _canonical_value(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _startup_ranks(
    markets: Mapping[str, PerpMarketSnapshot],
    *,
    as_of_ms: int,
) -> tuple[dict[str, FeatureSnapshot], tuple[OpportunityRank, ...]]:
    current_by_market: dict[str, PerpMarketSnapshot] = {}
    features: list[FeatureSnapshot] = []
    for current in sorted(markets.values(), key=lambda item: item.meta.market.canonical):
        market = current.meta.market
        key = market.canonical
        if key in current_by_market:
            raise ValueError(f"duplicate current market snapshot: {key}")
        if current.context.market != market or current.received_at_ms > as_of_ms:
            continue
        current_by_market[key] = current
        broad = calculate_broad_features(current, None, as_of_ms=as_of_ms)
        features.append(
            assemble_feature_snapshot(
                market,
                broad,
                as_of_ms=as_of_ms,
                provenance=(current.source,),
            )
        )

    if not features:
        return {}, ()
    feature_tuple = tuple(features)
    eligibility_config = EligibilityConfig()
    thresholds = derive_eligibility_thresholds(feature_tuple, eligibility_config)
    decisions = tuple(
        evaluate_eligibility(
            current_by_market[feature.market.canonical],
            feature,
            thresholds,
            eligibility_config,
        )
        for feature in feature_tuple
    )
    ranks = rank_opportunities(feature_tuple, decisions, mode="coarse")
    return {item.market.canonical: item for item in feature_tuple}, ranks


def _warmup_candles(
    reader: EvidenceInfoReader,
    market: MarketId,
    config: EvidenceRecordingConfig,
    *,
    end_ms: int,
    now_ms: Callable[[], int],
) -> tuple[Candle, ...]:
    output: list[Candle] = []
    for interval, bar_count in (
        ("5m", config.warmup_5m_bars),
        ("15m", config.warmup_15m_bars),
    ):
        interval_ms = INTERVAL_MS[interval]
        start_ms = max(0, end_ms - interval_ms * (bar_count + 2))
        raw = reader.candles(
            market,
            interval,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        received_at_ms = now_ms()
        output.extend(
            normalize_candles(
                market,
                raw,
                received_at_ms=received_at_ms,
            )
        )
    return tuple(output)


def _recent_funding(
    reader: EvidenceInfoReader,
    market: MarketId,
    *,
    end_ms: int,
    now_ms: Callable[[], int],
) -> tuple[FundingRate, ...]:
    raw = reader.funding_history(
        market,
        start_ms=max(0, end_ms - FUNDING_BOOTSTRAP_LOOKBACK_MS),
        end_ms=end_ms,
    )
    received_at_ms = now_ms()
    return normalize_funding_history(
        market,
        raw,
        received_at_ms=received_at_ms,
    )


def build_recording_bootstrap(
    reader: EvidenceInfoReader,
    config: EvidenceRecordingConfig,
    *,
    now_ms: Callable[[], int],
    code_revision: str,
) -> RecordingBootstrap:
    started_at_ms = now_ms()
    registry = MarketRegistry(reader, now_ms=now_ms).refresh()
    feature_map, ranks = _startup_ranks(
        registry.markets,
        as_of_ms=registry.received_at_ms,
    )

    native_ranks = tuple(rank for rank in ranks if rank.market.dex == "")
    selected_ranks = native_ranks[: config.deep_limit]
    if not selected_ranks:
        raise ValueError("startup scan produced no rankable native markets")

    selected = tuple(
        SelectedEvidenceMarket(
            market=rank.market,
            rank=rank.ordinal,
            feature_snapshot_id=feature_map[rank.market.canonical].snapshot_id,
            score=rank.score * SCORE_SCALE,
        )
        for rank in selected_ranks
    )
    session = EvidenceRecordingSession(
        started_at_ms=started_at_ms,
        recorder_code_revision=code_revision,
        selected=selected,
        recording_config_digest=config.config_digest,
        api_url=config.api_url,
        ws_url=config.ws_url,
        selection_policy_id=config.selection_policy_id,
    )

    selected_markets = tuple(item.market for item in session.selected)
    selected_snapshots = tuple(
        registry.markets[market.canonical] for market in selected_markets
    )
    candles: list[Candle] = []
    funding_rates: list[FundingRate] = []
    for market in selected_markets:
        candles.extend(
            _warmup_candles(
                reader,
                market,
                config,
                end_ms=started_at_ms,
                now_ms=now_ms,
            )
        )
        funding_rates.extend(
            _recent_funding(
                reader,
                market,
                end_ms=started_at_ms,
                now_ms=now_ms,
            )
        )

    plan = DeepWatchlistManager(candle_intervals=config.candle_intervals).reconcile(
        selected_markets
    )
    return RecordingBootstrap(
        session=session,
        snapshots=selected_snapshots,
        candles=tuple(candles),
        funding_rates=tuple(funding_rates),
        subscriptions=plan.subscribe,
    )


def market_snapshot_record_event(snapshot: PerpMarketSnapshot) -> RecordedPublicEvent:
    market = snapshot.meta.market
    if snapshot.context.market != market:
        raise ValueError("market snapshot metadata and context market must match")
    payload: dict[str, object] = {
        "meta": {
            "wire_name": snapshot.meta.wire_name,
            "sz_decimals": snapshot.meta.sz_decimals,
            "max_leverage": snapshot.meta.max_leverage,
            "margin_table_id": snapshot.meta.margin_table_id,
            "only_isolated": snapshot.meta.only_isolated,
            "is_delisted": snapshot.meta.is_delisted,
            "margin_mode": snapshot.meta.margin_mode,
        },
        "context": {
            "mark_px": snapshot.context.mark_px,
            "mid_px": snapshot.context.mid_px,
            "oracle_px": snapshot.context.oracle_px,
            "funding": snapshot.context.funding,
            "open_interest": snapshot.context.open_interest,
            "day_ntl_vlm": snapshot.context.day_ntl_vlm,
            "premium": snapshot.context.premium,
            "prev_day_px": snapshot.context.prev_day_px,
        },
    }
    digest = _payload_digest(payload)
    return RecordedPublicEvent(
        kind="market_snapshot",
        market=market,
        source=snapshot.source,
        exchange_time_ms=None,
        receive_time=_received_at(snapshot.received_at_ms),
        schema_version=snapshot.schema_version,
        event_key=(
            f"rest:market_snapshot:{market.canonical}:{snapshot.received_at_ms}:{digest}"
        ),
        payload=payload,
    )


def funding_rate_record_event(rate: FundingRate) -> RecordedPublicEvent:
    payload: dict[str, object] = {
        "time_ms": rate.time_ms,
        "funding_rate": rate.funding_rate,
        "premium": rate.premium,
    }
    digest = _payload_digest(payload)
    return RecordedPublicEvent(
        kind="funding_rate",
        market=rate.market,
        source=rate.source,
        exchange_time_ms=rate.time_ms,
        receive_time=_received_at(rate.received_at_ms),
        schema_version=rate.schema_version,
        event_key=(
            f"rest:funding_rate:{rate.market.canonical}:{rate.time_ms}:"
            f"{rate.received_at_ms}:{digest}"
        ),
        payload=payload,
    )


def candle_record_event(candle: Candle) -> RecordedPublicEvent:
    payload: dict[str, object] = {
        "start_ms": candle.start_ms,
        "end_ms": candle.end_ms,
        "interval": candle.interval,
        "open_px": candle.open_px,
        "high_px": candle.high_px,
        "low_px": candle.low_px,
        "close_px": candle.close_px,
        "volume": candle.volume,
        "trade_count": candle.trade_count,
    }
    digest = _payload_digest(payload)
    return RecordedPublicEvent(
        kind="candle",
        market=candle.market,
        source=candle.source,
        exchange_time_ms=candle.start_ms,
        receive_time=_received_at(candle.received_at_ms),
        schema_version=candle.schema_version,
        event_key=(
            f"rest:candle:{candle.market.canonical}:{candle.interval}:{candle.start_ms}:"
            f"{candle.received_at_ms}:{digest}"
        ),
        payload=payload,
    )
