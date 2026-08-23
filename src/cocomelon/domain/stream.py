from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from cocomelon.domain.market import MarketId


class StreamKind(StrEnum):
    ALL_MIDS = "all_mids"
    L2_BOOK = "l2_book"
    TRADE = "trade"
    CANDLE = "candle"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    kind: StreamKind
    market: MarketId
    exchange_time_ms: int | None
    receive_time: datetime
    schema_version: int
    source: str
    event_key: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if self.exchange_time_ms is not None and self.exchange_time_ms < 0:
            raise ValueError("exchange_time_ms must be non-negative")
        if self.receive_time.tzinfo is None or self.receive_time.utcoffset() is None:
            raise ValueError("receive_time must be timezone-aware")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if not self.event_key.strip():
            raise ValueError("event_key must not be empty")


@dataclass(frozen=True, slots=True)
class DataGap:
    stream_id: str
    started_ms: int
    ended_ms: int | None
    reason: str
    source: str = "hyperliquid-mainnet-ws"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.stream_id.strip():
            raise ValueError("stream_id must not be empty")
        if self.started_ms < 0:
            raise ValueError("started_ms must be non-negative")
        if self.ended_ms is not None and self.ended_ms < self.started_ms:
            raise ValueError("ended_ms must be >= started_ms")
        if not self.reason.strip():
            raise ValueError("reason must not be empty")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def is_open(self) -> bool:
        return self.ended_ms is None


@dataclass(frozen=True, slots=True)
class FreshnessState:
    stream_id: str
    last_message_ms: int | None
    stale_after_ms: int

    def __post_init__(self) -> None:
        if not self.stream_id.strip():
            raise ValueError("stream_id must not be empty")
        if self.last_message_ms is not None and self.last_message_ms < 0:
            raise ValueError("last_message_ms must be non-negative")
        if self.stale_after_ms <= 0:
            raise ValueError("stale_after_ms must be positive")

    def is_stale(self, *, now_ms: int) -> bool:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        if self.last_message_ms is None:
            return True
        if now_ms < self.last_message_ms:
            raise ValueError("now_ms must be >= last_message_ms")
        return now_ms - self.last_message_ms >= self.stale_after_ms


@dataclass(frozen=True, slots=True)
class StreamHealth:
    connected: bool
    last_server_message_ms: int | None
    reconnect_count: int = 0
    duplicate_count: int = 0
    anomaly_count: int = 0

    def __post_init__(self) -> None:
        if self.last_server_message_ms is not None and self.last_server_message_ms < 0:
            raise ValueError("last_server_message_ms must be non-negative")
        if self.reconnect_count < 0:
            raise ValueError("reconnect_count must be non-negative")
        if self.duplicate_count < 0:
            raise ValueError("duplicate_count must be non-negative")
        if self.anomaly_count < 0:
            raise ValueError("anomaly_count must be non-negative")
