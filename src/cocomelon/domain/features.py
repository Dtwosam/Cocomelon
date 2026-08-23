from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from cocomelon.domain.market import MarketId


class TrendRegime(StrEnum):
    UP = "up"
    DOWN = "down"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class VolatilityRegime(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    UNKNOWN = "unknown"


def _require_unit_interval(value: Decimal, field: str) -> None:
    if not value.is_finite() or value < 0 or value > 1:
        raise ValueError(f"{field} must be finite and between 0 and 1")


def _require_finite(value: Decimal | None, field: str) -> None:
    if value is not None and not value.is_finite():
        raise ValueError(f"{field} must be finite")


def _canonical_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    market: MarketId
    as_of_ms: int
    source_received_at_ms: int
    schema_version: int
    day_return: Decimal | None
    funding: Decimal
    open_interest: Decimal
    day_notional_volume: Decimal
    oi_change_fraction: Decimal | None
    funding_change: Decimal | None
    mark_oracle_dislocation_bps: Decimal | None
    return_5m: Decimal | None
    return_15m: Decimal | None
    return_1h: Decimal | None
    return_4h: Decimal | None
    realized_vol_15m: Decimal | None
    range_expansion_15m: Decimal | None
    relative_volume_15m: Decimal | None
    spread_bps: Decimal | None
    bid_depth_25bps: Decimal | None
    ask_depth_25bps: Decimal | None
    book_imbalance: Decimal | None
    book_age_ms: int | None
    trend_regime: TrendRegime
    volatility_regime: VolatilityRegime
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.source_received_at_ms < 0:
            raise ValueError("source_received_at_ms must be non-negative")
        if self.source_received_at_ms > self.as_of_ms:
            raise ValueError("source_received_at_ms must not be after as_of_ms")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.book_age_ms is not None and self.book_age_ms < 0:
            raise ValueError("book_age_ms must be non-negative")

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
        for field in decimal_fields:
            _require_finite(getattr(self, field), field)

        normalized_provenance = tuple(sorted(set(self.provenance)))
        if any(not source.strip() for source in normalized_provenance):
            raise ValueError("provenance values must not be empty")
        object.__setattr__(self, "provenance", normalized_provenance)

    @property
    def snapshot_id(self) -> str:
        payload = {
            "market": self.market.canonical,
            "as_of_ms": self.as_of_ms,
            "source_received_at_ms": self.source_received_at_ms,
            "schema_version": self.schema_version,
            "day_return": _canonical_decimal(self.day_return),
            "funding": _canonical_decimal(self.funding),
            "open_interest": _canonical_decimal(self.open_interest),
            "day_notional_volume": _canonical_decimal(self.day_notional_volume),
            "oi_change_fraction": _canonical_decimal(self.oi_change_fraction),
            "funding_change": _canonical_decimal(self.funding_change),
            "mark_oracle_dislocation_bps": _canonical_decimal(
                self.mark_oracle_dislocation_bps
            ),
            "return_5m": _canonical_decimal(self.return_5m),
            "return_15m": _canonical_decimal(self.return_15m),
            "return_1h": _canonical_decimal(self.return_1h),
            "return_4h": _canonical_decimal(self.return_4h),
            "realized_vol_15m": _canonical_decimal(self.realized_vol_15m),
            "range_expansion_15m": _canonical_decimal(self.range_expansion_15m),
            "relative_volume_15m": _canonical_decimal(self.relative_volume_15m),
            "spread_bps": _canonical_decimal(self.spread_bps),
            "bid_depth_25bps": _canonical_decimal(self.bid_depth_25bps),
            "ask_depth_25bps": _canonical_decimal(self.ask_depth_25bps),
            "book_imbalance": _canonical_decimal(self.book_imbalance),
            "book_age_ms": self.book_age_ms,
            "trend_regime": self.trend_regime.value,
            "volatility_regime": self.volatility_regime.value,
            "provenance": self.provenance,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    market: MarketId
    rankable: bool
    deep_ready: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.deep_ready and not self.rankable:
            raise ValueError("deep_ready requires rankable")
        normalized = tuple(dict.fromkeys(self.reasons))
        if any(not reason.strip() for reason in normalized):
            raise ValueError("eligibility reasons must not be empty")
        object.__setattr__(self, "reasons", normalized)


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    name: str
    raw_value: Decimal
    percentile: Decimal
    weight: Decimal
    contribution: Decimal

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        _require_finite(self.raw_value, "raw_value")
        _require_unit_interval(self.percentile, "percentile")
        _require_unit_interval(self.weight, "weight")
        _require_unit_interval(self.contribution, "contribution")
        if self.contribution != self.percentile * self.weight:
            raise ValueError("contribution must equal percentile * weight")


@dataclass(frozen=True, slots=True)
class OpportunityRank:
    market: MarketId
    ordinal: int
    score: Decimal
    components: tuple[ScoreComponent, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ordinal <= 0:
            raise ValueError("ordinal must be positive")
        _require_unit_interval(self.score, "score")
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("reason_codes must not contain empty values")
        object.__setattr__(self, "reason_codes", tuple(dict.fromkeys(self.reason_codes)))


@dataclass(frozen=True, slots=True)
class ShortlistDelta:
    added: tuple[MarketId, ...]
    removed: tuple[MarketId, ...]
    current: tuple[MarketId, ...]
    ranked_watchlist: tuple[MarketId, ...] = ()
