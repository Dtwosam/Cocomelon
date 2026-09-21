from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import Candle, FundingRate, MarketId
from cocomelon.features.math import quantile
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.research.historical_learning import (
    DirectionalOutcome,
    is_expected_funding_successor,
)

ZERO = Decimal("0")
ONE = Decimal("1")
MEDIAN = Decimal("0.5")
AVAILABILITY_BASIS = "exchange_timestamp"

CONTEXT_FEATURE_NAMES = (
    "btc_return_5m",
    "btc_return_1h",
    "btc_return_4h",
    "eth_return_5m",
    "eth_return_1h",
    "eth_return_4h",
    "market_median_return_5m",
    "market_median_return_1h",
    "market_breadth_positive_5m",
    "market_breadth_positive_1h",
    "market_relative_return_5m",
    "market_relative_return_1h",
)

STATIC_UNAVAILABLE_FEATURES = (
    "ask_depth_25bps",
    "bid_depth_25bps",
    "book_imbalance",
    "day_notional_volume",
    "mark_oracle_dislocation_bps",
    "open_interest",
    "order_flow",
    "oi_change_fraction",
    "spread_bps",
    *CONTEXT_FEATURE_NAMES,
)

OPTIONAL_FEATURE_NAMES = (
    "return_5m",
    "return_15m",
    "return_1h",
    "return_4h",
    "realized_vol_15m",
    "range_expansion_15m",
    "relative_volume_15m",
    "funding_rate",
    "funding_change",
    "funding_premium",
    "funding_premium_change",
    *CONTEXT_FEATURE_NAMES,
)


class HistoricalFeatureError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _finite_optional(value: Decimal | None, field: str) -> None:
    if value is not None and not value.is_finite():
        raise ValueError(f"{field} must be finite")


@dataclass(frozen=True, slots=True)
class HistoricalFeatureRow:
    market: MarketId
    anchor_end_ms: int
    anchor_close_px: Decimal
    return_5m: Decimal | None
    return_15m: Decimal | None
    return_1h: Decimal | None
    return_4h: Decimal | None
    realized_vol_15m: Decimal | None
    range_expansion_15m: Decimal | None
    relative_volume_15m: Decimal | None
    funding_rate: Decimal | None
    funding_change: Decimal | None
    funding_premium: Decimal | None
    funding_premium_change: Decimal | None
    funding_age_ms: int | None
    candle_15m_age_ms: int | None
    trend_regime: TrendRegime
    availability_basis: str
    source_retrieved_at_ms: int
    retrieved_after_anchor: bool
    available_features: tuple[str, ...]
    unavailable_features: tuple[str, ...]
    provenance: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]
    btc_return_5m: Decimal | None = None
    btc_return_1h: Decimal | None = None
    btc_return_4h: Decimal | None = None
    eth_return_5m: Decimal | None = None
    eth_return_1h: Decimal | None = None
    eth_return_4h: Decimal | None = None
    market_median_return_5m: Decimal | None = None
    market_median_return_1h: Decimal | None = None
    market_breadth_positive_5m: Decimal | None = None
    market_breadth_positive_1h: Decimal | None = None
    market_relative_return_5m: Decimal | None = None
    market_relative_return_1h: Decimal | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.anchor_end_ms < 0:
            raise ValueError("anchor_end_ms must be non-negative")
        if self.anchor_close_px <= 0 or not self.anchor_close_px.is_finite():
            raise ValueError("anchor_close_px must be positive and finite")
        if self.availability_basis != AVAILABILITY_BASIS:
            raise ValueError("availability_basis must be exchange_timestamp")
        if self.source_retrieved_at_ms < 0:
            raise ValueError("source_retrieved_at_ms must be non-negative")
        if self.retrieved_after_anchor != (
            self.source_retrieved_at_ms > self.anchor_end_ms
        ):
            raise ValueError("retrieved_after_anchor must match retrieval timestamp")
        if self.funding_age_ms is not None and self.funding_age_ms < 0:
            raise ValueError("funding_age_ms must be non-negative")
        if self.candle_15m_age_ms is not None and self.candle_15m_age_ms < 0:
            raise ValueError("candle_15m_age_ms must be non-negative")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

        for field in OPTIONAL_FEATURE_NAMES:
            _finite_optional(getattr(self, field), field)
        for field in (
            "market_breadth_positive_5m",
            "market_breadth_positive_1h",
        ):
            breadth = getattr(self, field)
            if breadth is not None and not ZERO <= breadth <= ONE:
                raise ValueError(f"{field} must be between 0 and 1")

        available = tuple(sorted(set(self.available_features)))
        unavailable = tuple(sorted(set(self.unavailable_features)))
        if set(available) & set(unavailable):
            raise ValueError("available and unavailable features must be disjoint")
        if any(not item.strip() for item in (*available, *unavailable)):
            raise ValueError("feature names must not be empty")
        object.__setattr__(self, "available_features", available)
        object.__setattr__(self, "unavailable_features", unavailable)

        provenance = tuple(sorted(set(self.provenance)))
        manifest_ids = tuple(sorted(set(self.source_manifest_ids)))
        if not provenance or any(not item.strip() for item in provenance):
            raise ValueError("provenance must contain non-empty source identities")
        if not manifest_ids or any(not item.strip() for item in manifest_ids):
            raise ValueError("source_manifest_ids must contain non-empty identities")
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "source_manifest_ids", manifest_ids)

    def identity_payload(self) -> dict[str, object]:
        return {
            "market": self.market.canonical,
            "anchor_end_ms": self.anchor_end_ms,
            "anchor_close_px": str(self.anchor_close_px),
            "return_5m": _decimal(self.return_5m),
            "return_15m": _decimal(self.return_15m),
            "return_1h": _decimal(self.return_1h),
            "return_4h": _decimal(self.return_4h),
            "realized_vol_15m": _decimal(self.realized_vol_15m),
            "range_expansion_15m": _decimal(self.range_expansion_15m),
            "relative_volume_15m": _decimal(self.relative_volume_15m),
            "funding_rate": _decimal(self.funding_rate),
            "funding_change": _decimal(self.funding_change),
            "funding_premium": _decimal(self.funding_premium),
            "funding_premium_change": _decimal(self.funding_premium_change),
            "funding_age_ms": self.funding_age_ms,
            "candle_15m_age_ms": self.candle_15m_age_ms,
            "trend_regime": self.trend_regime.value,
            "availability_basis": self.availability_basis,
            "source_retrieved_at_ms": self.source_retrieved_at_ms,
            "retrieved_after_anchor": self.retrieved_after_anchor,
            "available_features": self.available_features,
            "unavailable_features": self.unavailable_features,
            "provenance": self.provenance,
            "source_manifest_ids": self.source_manifest_ids,
            "btc_return_5m": _decimal(self.btc_return_5m),
            "btc_return_1h": _decimal(self.btc_return_1h),
            "btc_return_4h": _decimal(self.btc_return_4h),
            "eth_return_5m": _decimal(self.eth_return_5m),
            "eth_return_1h": _decimal(self.eth_return_1h),
            "eth_return_4h": _decimal(self.eth_return_4h),
            "market_median_return_5m": _decimal(self.market_median_return_5m),
            "market_median_return_1h": _decimal(self.market_median_return_1h),
            "market_breadth_positive_5m": _decimal(
                self.market_breadth_positive_5m
            ),
            "market_breadth_positive_1h": _decimal(
                self.market_breadth_positive_1h
            ),
            "market_relative_return_5m": _decimal(self.market_relative_return_5m),
            "market_relative_return_1h": _decimal(self.market_relative_return_1h),
            "schema_version": self.schema_version,
        }

    @property
    def row_id(self) -> str:
        encoded = _canonical_json(self.identity_payload()).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class HistoricalTrainingRow:
    feature: HistoricalFeatureRow
    outcome: DirectionalOutcome
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.feature.market != self.outcome.market:
            raise ValueError("feature and outcome markets must match")
        if self.feature.anchor_end_ms != self.outcome.anchor_end_ms:
            raise ValueError("feature and outcome anchors must match")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def feature_id(self) -> str:
        return self.feature.row_id

    @property
    def outcome_id(self) -> str:
        return self.outcome.outcome_id

    @property
    def market(self) -> MarketId:
        return self.feature.market

    @property
    def anchor_end_ms(self) -> int:
        return self.feature.anchor_end_ms

    @property
    def horizon_ms(self) -> int:
        return self.outcome.horizon_ms

    @property
    def long_gross_return(self) -> Decimal:
        return self.outcome.long_gross_return

    @property
    def short_gross_return(self) -> Decimal:
        return self.outcome.short_gross_return

    @property
    def training_row_id(self) -> str:
        payload = {
            "feature_id": self.feature_id,
            "outcome_id": self.outcome_id,
            "schema_version": self.schema_version,
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]


def _validate_candles(
    candles: Sequence[Candle],
    *,
    interval: str,
    expected_market: MarketId | None = None,
) -> tuple[Candle, ...]:
    ordered = tuple(sorted(candles, key=lambda item: (item.end_ms, item.start_ms)))
    seen: set[int] = set()
    market = expected_market
    for candle in ordered:
        if market is None:
            market = candle.market
        if candle.market != market:
            raise HistoricalFeatureError("MIXED_MARKETS")
        if candle.interval != interval:
            raise HistoricalFeatureError("MIXED_INTERVALS")
        if candle.end_ms in seen:
            raise HistoricalFeatureError("DUPLICATE_CANDLE_END")
        seen.add(candle.end_ms)
        prices = (candle.open_px, candle.high_px, candle.low_px, candle.close_px)
        if any(not value.is_finite() or value <= 0 for value in prices):
            raise HistoricalFeatureError("INVALID_CANDLE_PRICE")
        if candle.high_px < candle.low_px:
            raise HistoricalFeatureError("INVALID_CANDLE_RANGE")
        if not candle.volume.is_finite() or candle.volume < 0:
            raise HistoricalFeatureError("INVALID_CANDLE_VOLUME")
        if not candle.source.strip():
            raise HistoricalFeatureError("EMPTY_SOURCE")
    return ordered


def _validate_funding(
    funding_rates: Sequence[FundingRate],
    *,
    expected_market: MarketId,
) -> tuple[FundingRate, ...]:
    ordered = tuple(sorted(funding_rates, key=lambda item: item.time_ms))
    seen: set[int] = set()
    for rate in ordered:
        if rate.market != expected_market:
            raise HistoricalFeatureError("MIXED_MARKETS")
        if rate.time_ms in seen:
            raise HistoricalFeatureError("DUPLICATE_FUNDING_TIME")
        seen.add(rate.time_ms)
        if not rate.funding_rate.is_finite() or not rate.premium.is_finite():
            raise HistoricalFeatureError("INVALID_FUNDING_VALUE")
        if not rate.source.strip():
            raise HistoricalFeatureError("EMPTY_SOURCE")
    return ordered


def _simple_return(current: Decimal, previous: Decimal) -> Decimal:
    if previous <= 0:
        raise HistoricalFeatureError("NON_POSITIVE_PREVIOUS_CLOSE")
    return current / previous - ONE


def _exact_return(
    by_end_ms: dict[int, Candle],
    *,
    latest_end_ms: int,
    lookback_ms: int,
) -> Decimal | None:
    latest = by_end_ms.get(latest_end_ms)
    previous = by_end_ms.get(latest_end_ms - lookback_ms)
    if latest is None or previous is None:
        return None
    return _simple_return(latest.close_px, previous.close_px)


def _contiguous_15m_sample(
    by_end_ms: dict[int, Candle],
    *,
    latest_end_ms: int,
    bars: int,
) -> tuple[Candle, ...] | None:
    interval_ms = INTERVAL_MS["15m"]
    timestamps = tuple(
        latest_end_ms - interval_ms * offset
        for offset in range(bars - 1, -1, -1)
    )
    sample: list[Candle] = []
    for timestamp in timestamps:
        candle = by_end_ms.get(timestamp)
        if candle is None:
            return None
        sample.append(candle)
    return tuple(sample)


def _realized_volatility(sample: Sequence[Candle]) -> Decimal:
    returns = tuple(
        _simple_return(sample[index].close_px, sample[index - 1].close_px)
        for index in range(1, len(sample))
    )
    mean = sum(returns, ZERO) / Decimal(len(returns))
    variance = sum(((value - mean) ** 2 for value in returns), ZERO) / Decimal(
        len(returns)
    )
    return variance.sqrt()


def _relative_volume(sample: Sequence[Candle]) -> Decimal | None:
    prior = tuple(candle.volume for candle in sample[:-1])
    baseline = quantile(prior, MEDIAN)
    if baseline <= ZERO:
        return None
    return sample[-1].volume / baseline


def _normalized_range(candle: Candle) -> Decimal:
    return (candle.high_px - candle.low_px) / candle.open_px


def _range_expansion(sample: Sequence[Candle]) -> Decimal | None:
    ranges = tuple(_normalized_range(candle) for candle in sample)
    baseline = quantile(ranges[:-1], MEDIAN)
    if baseline <= ZERO:
        return None
    return ranges[-1] / baseline


def _trend_regime(
    return_15m: Decimal | None,
    return_1h: Decimal | None,
    return_4h: Decimal | None,
) -> TrendRegime:
    values = (return_15m, return_1h, return_4h)
    if any(value is None for value in values):
        return TrendRegime.UNKNOWN
    resolved = tuple(value for value in values if value is not None)
    if all(value > 0 for value in resolved):
        return TrendRegime.UP
    if all(value < 0 for value in resolved):
        return TrendRegime.DOWN
    return TrendRegime.MIXED


def _availability(
    values: dict[str, Decimal | None],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    available = tuple(sorted(name for name, value in values.items() if value is not None))
    unavailable = tuple(
        sorted(
            {
                *STATIC_UNAVAILABLE_FEATURES,
                *(name for name, value in values.items() if value is None),
            }
        )
    )
    return available, unavailable


def build_historical_feature_rows(
    *,
    candles_5m: Sequence[Candle],
    candles_15m: Sequence[Candle],
    funding_rates: Sequence[FundingRate],
    source_manifest_ids: Sequence[str],
) -> tuple[HistoricalFeatureRow, ...]:
    ordered_5m = _validate_candles(candles_5m, interval="5m")
    if not ordered_5m:
        return ()
    market = ordered_5m[0].market
    ordered_15m = _validate_candles(
        candles_15m,
        interval="15m",
        expected_market=market,
    )
    ordered_funding = _validate_funding(funding_rates, expected_market=market)

    manifests = tuple(sorted(set(source_manifest_ids)))
    if not manifests or any(not item.strip() for item in manifests):
        raise HistoricalFeatureError("EMPTY_SOURCE_MANIFEST")

    by_5m_end = {candle.end_ms: candle for candle in ordered_5m}
    by_15m_end = {candle.end_ms: candle for candle in ordered_15m}
    ends_15m = tuple(candle.end_ms for candle in ordered_15m)
    funding_times = tuple(rate.time_ms for rate in ordered_funding)

    rows: list[HistoricalFeatureRow] = []
    for anchor in ordered_5m:
        anchor_ms = anchor.end_ms
        used_candles: dict[tuple[str, int], Candle] = {
            (anchor.interval, anchor.end_ms): anchor
        }
        return_5m = _exact_return(
            by_5m_end,
            latest_end_ms=anchor_ms,
            lookback_ms=INTERVAL_MS["5m"],
        )
        previous_5m = by_5m_end.get(anchor_ms - INTERVAL_MS["5m"])
        if previous_5m is not None:
            used_candles[(previous_5m.interval, previous_5m.end_ms)] = previous_5m

        latest_15m: Candle | None = None
        candle_15m_age_ms: int | None = None
        return_15m: Decimal | None = None
        return_1h: Decimal | None = None
        return_4h: Decimal | None = None
        realized_vol_15m: Decimal | None = None
        range_expansion_15m: Decimal | None = None
        relative_volume_15m: Decimal | None = None

        fifteen_position = bisect_right(ends_15m, anchor_ms) - 1
        if fifteen_position >= 0:
            latest_15m = ordered_15m[fifteen_position]
            latest_15m_end = latest_15m.end_ms
            used_candles[(latest_15m.interval, latest_15m.end_ms)] = latest_15m
            candle_15m_age_ms = anchor_ms - latest_15m_end
            return_15m = _exact_return(
                by_15m_end,
                latest_end_ms=latest_15m_end,
                lookback_ms=INTERVAL_MS["15m"],
            )
            return_1h = _exact_return(
                by_15m_end,
                latest_end_ms=latest_15m_end,
                lookback_ms=INTERVAL_MS["1h"],
            )
            return_4h = _exact_return(
                by_15m_end,
                latest_end_ms=latest_15m_end,
                lookback_ms=INTERVAL_MS["4h"],
            )
            for lookback_ms in (
                INTERVAL_MS["15m"],
                INTERVAL_MS["1h"],
                INTERVAL_MS["4h"],
            ):
                previous = by_15m_end.get(latest_15m_end - lookback_ms)
                if previous is not None:
                    used_candles[(previous.interval, previous.end_ms)] = previous
            sample = _contiguous_15m_sample(
                by_15m_end,
                latest_end_ms=latest_15m_end,
                bars=21,
            )
            if sample is not None:
                realized_vol_15m = _realized_volatility(sample)
                range_expansion_15m = _range_expansion(sample)
                relative_volume_15m = _relative_volume(sample)
                for candle in sample:
                    used_candles[(candle.interval, candle.end_ms)] = candle

        current_funding: FundingRate | None = None
        previous_funding: FundingRate | None = None
        funding_position = bisect_right(funding_times, anchor_ms) - 1
        if funding_position >= 0:
            current_funding = ordered_funding[funding_position]
            if funding_position > 0:
                candidate = ordered_funding[funding_position - 1]
                if is_expected_funding_successor(
                    candidate.time_ms,
                    current_funding.time_ms,
                ):
                    previous_funding = candidate

        funding_rate = None if current_funding is None else current_funding.funding_rate
        funding_premium = None if current_funding is None else current_funding.premium
        funding_age_ms = (
            None if current_funding is None else anchor_ms - current_funding.time_ms
        )
        funding_change = (
            None
            if current_funding is None or previous_funding is None
            else current_funding.funding_rate - previous_funding.funding_rate
        )
        funding_premium_change = (
            None
            if current_funding is None or previous_funding is None
            else current_funding.premium - previous_funding.premium
        )

        values = {
            "return_5m": return_5m,
            "return_15m": return_15m,
            "return_1h": return_1h,
            "return_4h": return_4h,
            "realized_vol_15m": realized_vol_15m,
            "range_expansion_15m": range_expansion_15m,
            "relative_volume_15m": relative_volume_15m,
            "funding_rate": funding_rate,
            "funding_change": funding_change,
            "funding_premium": funding_premium,
            "funding_premium_change": funding_premium_change,
        }
        available_features, unavailable_features = _availability(values)

        used_sources = {candle.source for candle in used_candles.values()}
        retrieved_at = max(
            candle.received_at_ms for candle in used_candles.values()
        )
        if current_funding is not None:
            used_sources.add(current_funding.source)
            retrieved_at = max(retrieved_at, current_funding.received_at_ms)
        if previous_funding is not None:
            used_sources.add(previous_funding.source)
            retrieved_at = max(retrieved_at, previous_funding.received_at_ms)

        rows.append(
            HistoricalFeatureRow(
                market=market,
                anchor_end_ms=anchor_ms,
                anchor_close_px=anchor.close_px,
                return_5m=return_5m,
                return_15m=return_15m,
                return_1h=return_1h,
                return_4h=return_4h,
                realized_vol_15m=realized_vol_15m,
                range_expansion_15m=range_expansion_15m,
                relative_volume_15m=relative_volume_15m,
                funding_rate=funding_rate,
                funding_change=funding_change,
                funding_premium=funding_premium,
                funding_premium_change=funding_premium_change,
                funding_age_ms=funding_age_ms,
                candle_15m_age_ms=candle_15m_age_ms,
                trend_regime=_trend_regime(return_15m, return_1h, return_4h),
                availability_basis=AVAILABILITY_BASIS,
                source_retrieved_at_ms=retrieved_at,
                retrieved_after_anchor=retrieved_at > anchor_ms,
                available_features=available_features,
                unavailable_features=unavailable_features,
                provenance=tuple(sorted(used_sources)),
                source_manifest_ids=manifests,
            )
        )
    return tuple(rows)


def _native_reference(
    rows: Sequence[HistoricalFeatureRow],
    coin: str,
) -> HistoricalFeatureRow | None:
    return next(
        (
            row
            for row in rows
            if row.market.dex == "" and row.market.coin == coin
        ),
        None,
    )


def _cross_section(
    rows: Sequence[HistoricalFeatureRow],
    field: str,
) -> tuple[Decimal | None, Decimal | None]:
    values = tuple(
        value
        for row in rows
        if (value := getattr(row, field)) is not None
    )
    if len(values) < 2:
        return None, None
    median = quantile(values, MEDIAN)
    breadth = Decimal(sum(value > ZERO for value in values)) / Decimal(len(values))
    return median, breadth


def enrich_historical_market_context(
    features: Sequence[HistoricalFeatureRow],
) -> tuple[HistoricalFeatureRow, ...]:
    by_anchor: dict[int, list[HistoricalFeatureRow]] = {}
    seen: set[tuple[MarketId, int]] = set()
    for feature in features:
        key = (feature.market, feature.anchor_end_ms)
        if key in seen:
            raise HistoricalFeatureError("DUPLICATE_FEATURE_ANCHOR")
        seen.add(key)
        by_anchor.setdefault(feature.anchor_end_ms, []).append(feature)

    enriched: list[HistoricalFeatureRow] = []
    for anchor_ms in sorted(by_anchor):
        anchor_rows = tuple(
            sorted(by_anchor[anchor_ms], key=lambda row: row.market.canonical)
        )
        btc = _native_reference(anchor_rows, "BTC")
        eth = _native_reference(anchor_rows, "ETH")
        median_5m, breadth_5m = _cross_section(anchor_rows, "return_5m")
        median_1h, breadth_1h = _cross_section(anchor_rows, "return_1h")

        for feature in anchor_rows:
            context = {
                "btc_return_5m": None if btc is None else btc.return_5m,
                "btc_return_1h": None if btc is None else btc.return_1h,
                "btc_return_4h": None if btc is None else btc.return_4h,
                "eth_return_5m": None if eth is None else eth.return_5m,
                "eth_return_1h": None if eth is None else eth.return_1h,
                "eth_return_4h": None if eth is None else eth.return_4h,
                "market_median_return_5m": median_5m,
                "market_median_return_1h": median_1h,
                "market_breadth_positive_5m": breadth_5m,
                "market_breadth_positive_1h": breadth_1h,
                "market_relative_return_5m": (
                    None
                    if feature.return_5m is None or median_5m is None
                    else feature.return_5m - median_5m
                ),
                "market_relative_return_1h": (
                    None
                    if feature.return_1h is None or median_1h is None
                    else feature.return_1h - median_1h
                ),
            }

            available = set(feature.available_features) - set(CONTEXT_FEATURE_NAMES)
            unavailable = set(feature.unavailable_features) - set(CONTEXT_FEATURE_NAMES)
            available.update(
                name for name, value in context.items() if value is not None
            )
            unavailable.update(
                name for name, value in context.items() if value is None
            )

            contributors = {feature}
            if btc is not None and any(
                value is not None
                for value in (btc.return_5m, btc.return_1h, btc.return_4h)
            ):
                contributors.add(btc)
            if eth is not None and any(
                value is not None
                for value in (eth.return_5m, eth.return_1h, eth.return_4h)
            ):
                contributors.add(eth)
            if median_5m is not None or median_1h is not None:
                contributors.update(
                    row
                    for row in anchor_rows
                    if row.return_5m is not None or row.return_1h is not None
                )

            enriched.append(
                replace(
                    feature,
                    btc_return_5m=context["btc_return_5m"],
                    btc_return_1h=context["btc_return_1h"],
                    btc_return_4h=context["btc_return_4h"],
                    eth_return_5m=context["eth_return_5m"],
                    eth_return_1h=context["eth_return_1h"],
                    eth_return_4h=context["eth_return_4h"],
                    market_median_return_5m=context["market_median_return_5m"],
                    market_median_return_1h=context["market_median_return_1h"],
                    market_breadth_positive_5m=context[
                        "market_breadth_positive_5m"
                    ],
                    market_breadth_positive_1h=context[
                        "market_breadth_positive_1h"
                    ],
                    market_relative_return_5m=context["market_relative_return_5m"],
                    market_relative_return_1h=context["market_relative_return_1h"],
                    source_retrieved_at_ms=max(
                        row.source_retrieved_at_ms for row in contributors
                    ),
                    retrieved_after_anchor=(
                        max(row.source_retrieved_at_ms for row in contributors)
                        > anchor_ms
                    ),
                    available_features=tuple(available),
                    unavailable_features=tuple(unavailable),
                    provenance=tuple(
                        source
                        for row in contributors
                        for source in row.provenance
                    ),
                    source_manifest_ids=tuple(
                        manifest_id
                        for row in contributors
                        for manifest_id in row.source_manifest_ids
                    ),
                    schema_version=2,
                )
            )

    return tuple(
        sorted(
            enriched,
            key=lambda row: (row.market.canonical, row.anchor_end_ms, row.row_id),
        )
    )


def join_features_to_outcomes(
    features: Sequence[HistoricalFeatureRow],
    outcomes: Sequence[DirectionalOutcome],
) -> tuple[HistoricalTrainingRow, ...]:
    feature_by_key: dict[tuple[MarketId, int], HistoricalFeatureRow] = {}
    for source_feature in features:
        feature_key = (source_feature.market, source_feature.anchor_end_ms)
        if feature_key in feature_by_key:
            raise HistoricalFeatureError("DUPLICATE_FEATURE_ANCHOR")
        feature_by_key[feature_key] = source_feature

    rows: list[HistoricalTrainingRow] = []
    seen_training_keys: set[tuple[str, str]] = set()
    for outcome in sorted(
        outcomes,
        key=lambda item: (
            item.market.canonical,
            item.anchor_end_ms,
            item.horizon_ms,
            item.outcome_id,
        ),
    ):
        matched_feature = feature_by_key.get((outcome.market, outcome.anchor_end_ms))
        if matched_feature is None:
            continue
        training_key = (matched_feature.row_id, outcome.outcome_id)
        if training_key in seen_training_keys:
            raise HistoricalFeatureError("DUPLICATE_TRAINING_ROW")
        seen_training_keys.add(training_key)
        rows.append(HistoricalTrainingRow(feature=matched_feature, outcome=outcome))
    return tuple(rows)
