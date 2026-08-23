from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from cocomelon.domain.features import EligibilityDecision, FeatureSnapshot
from cocomelon.domain.market import Candle, MarketId, PerpMarketSnapshot

ZERO = Decimal("0")
HUNDRED = Decimal("100")
ONE = Decimal("1")
TWO = Decimal("2")


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NO_TRADE = "no_trade"


class StrategyRole(StrEnum):
    PRIMARY = "primary"
    CONTEXT = "context"


def _require_score(value: Decimal) -> None:
    if not value.is_finite() or value < ZERO or value > HUNDRED:
        raise ValueError("score must be finite and between 0 and 100")


def _require_positive_decimal(value: Decimal, field: str) -> None:
    if not value.is_finite() or value <= ZERO:
        raise ValueError(f"{field} must be positive and finite")


def _normalize_strings(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(values))
    if any(not value.strip() for value in normalized):
        raise ValueError(f"{field} values must not be empty")
    return normalized


def _canonical_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy: str
    role: StrategyRole
    market: MarketId
    direction: Direction
    score: Decimal
    timestamp_ms: int
    reason_codes: tuple[str, ...]
    feature_snapshot_id: str
    invalidation_price: Decimal | None
    veto_directions: tuple[Direction, ...]

    def __post_init__(self) -> None:
        if not self.strategy.strip():
            raise ValueError("strategy must not be empty")
        _require_score(self.score)
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if not self.feature_snapshot_id.strip():
            raise ValueError("feature_snapshot_id must not be empty")

        object.__setattr__(
            self,
            "reason_codes",
            _normalize_strings(self.reason_codes, "reason_codes"),
        )
        vetoes = tuple(dict.fromkeys(self.veto_directions))
        if Direction.NO_TRADE in vetoes:
            raise ValueError("veto_directions cannot include NO_TRADE")
        object.__setattr__(self, "veto_directions", vetoes)

        if self.role is StrategyRole.PRIMARY:
            if vetoes:
                raise ValueError("primary signals cannot set context vetoes")
            if self.direction is Direction.NO_TRADE:
                if self.invalidation_price is not None:
                    raise ValueError("primary NO_TRADE cannot set invalidation_price")
            else:
                if self.invalidation_price is None:
                    raise ValueError("directional primary signals require invalidation_price")
                _require_positive_decimal(self.invalidation_price, "invalidation_price")
        else:
            if self.invalidation_price is not None:
                raise ValueError("context signals cannot set invalidation_price")

    @property
    def signal_id(self) -> str:
        payload: dict[str, object] = {
            "strategy": self.strategy,
            "role": self.role.value,
            "market": self.market.canonical,
            "direction": self.direction.value,
            "score": str(self.score),
            "timestamp_ms": self.timestamp_ms,
            "reason_codes": self.reason_codes,
            "feature_snapshot_id": self.feature_snapshot_id,
            "invalidation_price": _canonical_decimal(self.invalidation_price),
            "veto_directions": tuple(direction.value for direction in self.veto_directions),
        }
        return _digest(payload)


@dataclass(frozen=True, slots=True)
class MicrostructureWindow:
    market: MarketId
    start_ms: int
    as_of_ms: int
    trade_count: int
    buy_notional: Decimal
    sell_notional: Decimal
    trade_flow_imbalance: Decimal | None
    latest_book_imbalance: Decimal | None
    book_imbalance_change: Decimal | None
    latest_event_age_ms: int | None
    event_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.as_of_ms < 0:
            raise ValueError("window timestamps must be non-negative")
        if self.start_ms > self.as_of_ms:
            raise ValueError("start_ms must be <= as_of_ms")
        if self.trade_count < 0:
            raise ValueError("trade_count must be non-negative")
        _require_nonnegative_finite(self.buy_notional, "buy_notional")
        _require_nonnegative_finite(self.sell_notional, "sell_notional")
        _require_unit_imbalance(self.trade_flow_imbalance, "trade_flow_imbalance")
        _require_unit_imbalance(self.latest_book_imbalance, "latest_book_imbalance")
        if self.book_imbalance_change is not None:
            if (
                not self.book_imbalance_change.is_finite()
                or self.book_imbalance_change < -TWO
                or self.book_imbalance_change > TWO
            ):
                raise ValueError("book_imbalance_change must be finite and between -2 and 2")
        if self.latest_event_age_ms is not None and self.latest_event_age_ms < 0:
            raise ValueError("latest_event_age_ms must be non-negative")
        normalized_keys = tuple(sorted(set(self.event_keys)))
        if any(not key.strip() for key in normalized_keys):
            raise ValueError("event_keys values must not be empty")
        object.__setattr__(self, "event_keys", normalized_keys)


def _require_nonnegative_finite(value: Decimal, field: str) -> None:
    if not value.is_finite() or value < ZERO:
        raise ValueError(f"{field} must be non-negative and finite")


def _require_unit_imbalance(value: Decimal | None, field: str) -> None:
    if value is not None and (not value.is_finite() or value < -ONE or value > ONE):
        raise ValueError(f"{field} imbalance must be finite and between -1 and 1")


@dataclass(frozen=True, slots=True)
class StrategyContext:
    market_snapshot: PerpMarketSnapshot
    feature_snapshot: FeatureSnapshot
    eligibility: EligibilityDecision
    candles_5m: tuple[Candle, ...]
    candles_15m: tuple[Candle, ...]
    microstructure: MicrostructureWindow | None
    as_of_ms: int

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        market = self.feature_snapshot.market
        market_ids = {
            self.market_snapshot.meta.market,
            self.market_snapshot.context.market,
            self.eligibility.market,
            market,
        }
        if len(market_ids) != 1:
            raise ValueError("strategy context market identities must match")
        if self.market_snapshot.received_at_ms > self.as_of_ms:
            raise ValueError("market snapshot cannot be received after as_of_ms")
        if self.feature_snapshot.as_of_ms > self.as_of_ms:
            raise ValueError("feature snapshot cannot be after as_of_ms")
        if self.feature_snapshot.source_received_at_ms > self.as_of_ms:
            raise ValueError("feature source cannot be received after as_of_ms")
        if self.microstructure is not None:
            if self.microstructure.market != market:
                raise ValueError("microstructure market must match strategy context market")
            if self.microstructure.as_of_ms > self.as_of_ms:
                raise ValueError("microstructure window cannot be after as_of_ms")


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    market: MarketId
    direction: Direction
    score: Decimal
    timestamp_ms: int
    feature_snapshot_id: str
    lead_strategy: str | None
    invalidation_price: Decimal | None
    signal_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_score(self.score)
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if not self.feature_snapshot_id.strip():
            raise ValueError("feature_snapshot_id must not be empty")
        object.__setattr__(
            self,
            "signal_ids",
            _normalize_strings(self.signal_ids, "signal_ids"),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_strings(self.reason_codes, "reason_codes"),
        )

        if self.direction is Direction.NO_TRADE:
            if self.invalidation_price is not None:
                raise ValueError("NO_TRADE decisions cannot set invalidation_price")
        else:
            if self.lead_strategy is None or not self.lead_strategy.strip():
                raise ValueError("directional decisions require lead_strategy")
            if self.invalidation_price is None:
                raise ValueError("directional decisions require invalidation_price")
            _require_positive_decimal(self.invalidation_price, "invalidation_price")

    @property
    def decision_id(self) -> str:
        payload: dict[str, object] = {
            "market": self.market.canonical,
            "direction": self.direction.value,
            "score": str(self.score),
            "timestamp_ms": self.timestamp_ms,
            "feature_snapshot_id": self.feature_snapshot_id,
            "lead_strategy": self.lead_strategy,
            "invalidation_price": _canonical_decimal(self.invalidation_price),
            "signal_ids": self.signal_ids,
            "reason_codes": self.reason_codes,
        }
        return _digest(payload)
