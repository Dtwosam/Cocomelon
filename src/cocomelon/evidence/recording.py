from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from cocomelon.domain.market import Candle, FundingRate, MarketId, PerpMarketSnapshot


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
