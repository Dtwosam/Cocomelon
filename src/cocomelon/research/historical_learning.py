from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.market import Candle, MarketId
from cocomelon.hyperliquid.client import INTERVAL_MS


class HistoricalLearningError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CandleBackfillWindow:
    interval: str
    start_ms: int
    end_ms: int
    interval_ms: int

    def __post_init__(self) -> None:
        if self.interval not in INTERVAL_MS:
            raise ValueError(f"unsupported candle interval: {self.interval}")
        if self.interval_ms != INTERVAL_MS[self.interval]:
            raise ValueError("interval_ms does not match interval")
        if self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")

    @property
    def candle_capacity(self) -> int:
        return ((self.end_ms - self.start_ms) // self.interval_ms) + 1


@dataclass(frozen=True, slots=True)
class DirectionalOutcome:
    market: MarketId
    interval: str
    anchor_end_ms: int
    target_end_ms: int
    horizon_ms: int
    entry_px: Decimal
    exit_px: Decimal
    long_gross_return: Decimal
    short_gross_return: Decimal
    provenance: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.anchor_end_ms < 0:
            raise ValueError("anchor_end_ms must be non-negative")
        if self.target_end_ms <= self.anchor_end_ms:
            raise ValueError("target_end_ms must be after anchor_end_ms")
        if self.horizon_ms != self.target_end_ms - self.anchor_end_ms:
            raise ValueError("horizon_ms must match target minus anchor")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.entry_px <= 0 or not self.entry_px.is_finite():
            raise ValueError("entry_px must be positive and finite")
        if self.exit_px <= 0 or not self.exit_px.is_finite():
            raise ValueError("exit_px must be positive and finite")
        if not self.long_gross_return.is_finite():
            raise ValueError("long_gross_return must be finite")
        if not self.short_gross_return.is_finite():
            raise ValueError("short_gross_return must be finite")
        expected_long = (self.exit_px - self.entry_px) / self.entry_px
        expected_short = (self.entry_px - self.exit_px) / self.entry_px
        if self.long_gross_return != expected_long:
            raise ValueError("long_gross_return does not match prices")
        if self.short_gross_return != expected_short:
            raise ValueError("short_gross_return does not match prices")
        normalized = tuple(sorted(set(self.provenance)))
        if not normalized or any(not item.strip() for item in normalized):
            raise ValueError("provenance must contain non-empty values")
        object.__setattr__(self, "provenance", normalized)
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def outcome_id(self) -> str:
        payload = {
            "market": self.market.canonical,
            "interval": self.interval,
            "anchor_end_ms": self.anchor_end_ms,
            "target_end_ms": self.target_end_ms,
            "horizon_ms": self.horizon_ms,
            "entry_px": str(self.entry_px),
            "exit_px": str(self.exit_px),
            "long_gross_return": str(self.long_gross_return),
            "short_gross_return": str(self.short_gross_return),
            "provenance": self.provenance,
            "schema_version": self.schema_version,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:24]


def plan_candle_windows(
    *,
    interval: str,
    start_ms: int,
    end_ms: int,
    max_candles: int = 5_000,
) -> tuple[CandleBackfillWindow, ...]:
    interval_ms = INTERVAL_MS.get(interval)
    if interval_ms is None:
        raise ValueError(f"unsupported candle interval: {interval}")
    if start_ms < 0:
        raise ValueError("start_ms must be non-negative")
    if end_ms < start_ms:
        raise ValueError("end_ms must be >= start_ms")
    if max_candles <= 0:
        raise ValueError("max_candles must be positive")

    max_span_ms = interval_ms * (max_candles - 1)
    windows: list[CandleBackfillWindow] = []
    cursor = start_ms
    while cursor <= end_ms:
        window_end = min(end_ms, cursor + max_span_ms)
        windows.append(
            CandleBackfillWindow(
                interval=interval,
                start_ms=cursor,
                end_ms=window_end,
                interval_ms=interval_ms,
            )
        )
        cursor = window_end + interval_ms
    return tuple(windows)


def _validated_horizons(horizons_ms: Sequence[int]) -> tuple[int, ...]:
    horizons = tuple(horizons_ms)
    if any(value <= 0 for value in horizons):
        raise ValueError("horizons_ms values must be positive")
    if len(set(horizons)) != len(horizons):
        raise ValueError("horizons_ms values must be unique")
    return tuple(sorted(horizons))


def _validate_candles(candles: Sequence[Candle]) -> tuple[Candle, ...]:
    ordered = tuple(sorted(candles, key=lambda item: (item.end_ms, item.start_ms)))
    if not ordered:
        return ()

    market = ordered[0].market
    interval = ordered[0].interval
    seen_end_ms: set[int] = set()
    for candle in ordered:
        if candle.market != market:
            raise HistoricalLearningError("MIXED_MARKETS")
        if candle.interval != interval:
            raise HistoricalLearningError("MIXED_INTERVALS")
        if candle.end_ms in seen_end_ms:
            raise HistoricalLearningError("DUPLICATE_CANDLE_END")
        seen_end_ms.add(candle.end_ms)
        if candle.close_px <= 0 or not candle.close_px.is_finite():
            raise HistoricalLearningError("NON_POSITIVE_CLOSE")
        if not candle.source.strip():
            raise HistoricalLearningError("EMPTY_SOURCE")
    return ordered


def build_directional_outcomes(
    candles: Sequence[Candle],
    *,
    horizons_ms: Sequence[int],
) -> tuple[DirectionalOutcome, ...]:
    horizons = _validated_horizons(horizons_ms)
    ordered = _validate_candles(candles)
    if not ordered or not horizons:
        return ()

    by_end_ms = {candle.end_ms: candle for candle in ordered}
    outcomes: list[DirectionalOutcome] = []
    for anchor in ordered:
        for horizon_ms in horizons:
            target = by_end_ms.get(anchor.end_ms + horizon_ms)
            if target is None:
                continue
            long_return = (target.close_px - anchor.close_px) / anchor.close_px
            short_return = (anchor.close_px - target.close_px) / anchor.close_px
            outcomes.append(
                DirectionalOutcome(
                    market=anchor.market,
                    interval=anchor.interval,
                    anchor_end_ms=anchor.end_ms,
                    target_end_ms=target.end_ms,
                    horizon_ms=horizon_ms,
                    entry_px=anchor.close_px,
                    exit_px=target.close_px,
                    long_gross_return=long_return,
                    short_gross_return=short_return,
                    provenance=(anchor.source, target.source),
                )
            )

    return tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.anchor_end_ms,
                item.horizon_ms,
                item.target_end_ms,
                item.outcome_id,
            ),
        )
    )
