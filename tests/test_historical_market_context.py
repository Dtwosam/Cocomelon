from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    enrich_historical_market_context,
)
from cocomelon.research.historical_ridge import NUMERIC_FEATURES, RidgeFeatureTransform

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
SOL = MarketId(dex="", coin="SOL")
FIVE = 300_000


def _feature(
    market: MarketId,
    *,
    anchor_end_ms: int,
    return_5m: str | None,
    return_1h: str | None,
    return_4h: str | None,
    retrieved_at_ms: int,
    manifest_id: str,
) -> HistoricalFeatureRow:
    def value(raw: str | None) -> Decimal | None:
        return None if raw is None else Decimal(raw)

    available = tuple(
        name
        for name, raw in (
            ("return_5m", return_5m),
            ("return_1h", return_1h),
            ("return_4h", return_4h),
        )
        if raw is not None
    )
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=value(return_5m),
        return_15m=None,
        return_1h=value(return_1h),
        return_4h=value(return_4h),
        realized_vol_15m=None,
        range_expansion_15m=None,
        relative_volume_15m=None,
        funding_rate=None,
        funding_change=None,
        funding_premium=None,
        funding_premium_change=None,
        funding_age_ms=None,
        candle_15m_age_ms=None,
        trend_regime=TrendRegime.MIXED,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=retrieved_at_ms,
        retrieved_after_anchor=retrieved_at_ms > anchor_end_ms,
        available_features=available,
        unavailable_features=(
            "return_15m",
            "realized_vol_15m",
            "range_expansion_15m",
            "relative_volume_15m",
            "funding_rate",
            "funding_change",
            "funding_premium",
            "funding_premium_change",
        ),
        provenance=(f"source-{market.canonical}",),
        source_manifest_ids=(manifest_id,),
    )


def test_market_context_uses_only_exact_anchor_cross_section() -> None:
    anchor = FIVE - 1
    rows = (
        _feature(
            BTC,
            anchor_end_ms=anchor,
            return_5m="0.02",
            return_1h="0.04",
            return_4h="0.08",
            retrieved_at_ms=1000,
            manifest_id="btc-manifest",
        ),
        _feature(
            ETH,
            anchor_end_ms=anchor,
            return_5m="-0.01",
            return_1h="0.01",
            return_4h="0.03",
            retrieved_at_ms=1200,
            manifest_id="eth-manifest",
        ),
        _feature(
            SOL,
            anchor_end_ms=anchor,
            return_5m="0.01",
            return_1h="-0.02",
            return_4h="0.02",
            retrieved_at_ms=1400,
            manifest_id="sol-manifest",
        ),
    )

    enriched = enrich_historical_market_context(rows)
    sol = next(row for row in enriched if row.market == SOL)

    assert sol.btc_return_5m == Decimal("0.02")
    assert sol.btc_return_1h == Decimal("0.04")
    assert sol.btc_return_4h == Decimal("0.08")
    assert sol.eth_return_5m == Decimal("-0.01")
    assert sol.eth_return_1h == Decimal("0.01")
    assert sol.eth_return_4h == Decimal("0.03")
    assert sol.market_median_return_5m == Decimal("0.01")
    assert sol.market_median_return_1h == Decimal("0.01")
    assert sol.market_breadth_positive_5m == Decimal("2") / Decimal("3")
    assert sol.market_breadth_positive_1h == Decimal("2") / Decimal("3")
    assert sol.market_relative_return_5m == Decimal("0")
    assert sol.market_relative_return_1h == Decimal("-0.03")
    assert sol.schema_version == 2
    assert set(sol.source_manifest_ids) == {
        "btc-manifest",
        "eth-manifest",
        "sol-manifest",
    }
    assert sol.source_retrieved_at_ms == 1400
    assert "market_breadth_positive_5m" in sol.available_features


def test_market_context_does_not_forward_fill_reference_market() -> None:
    first_anchor = FIVE - 1
    second_anchor = 2 * FIVE - 1
    rows = (
        _feature(
            BTC,
            anchor_end_ms=second_anchor,
            return_5m="0.03",
            return_1h="0.04",
            return_4h="0.05",
            retrieved_at_ms=2_000_000,
            manifest_id="btc-later",
        ),
        _feature(
            SOL,
            anchor_end_ms=first_anchor,
            return_5m="0.01",
            return_1h="0.02",
            return_4h="0.03",
            retrieved_at_ms=1_000_000,
            manifest_id="sol-now",
        ),
    )

    enriched = enrich_historical_market_context(rows)
    sol = next(row for row in enriched if row.market == SOL)

    assert sol.btc_return_5m is None
    assert sol.btc_return_1h is None
    assert sol.btc_return_4h is None
    assert sol.market_median_return_5m is None
    assert sol.market_breadth_positive_5m is None
    assert "btc_return_5m" in sol.unavailable_features
    assert sol.source_manifest_ids == ("sol-now",)


def test_market_context_is_deterministic_for_reordered_rows() -> None:
    anchor = FIVE - 1
    rows = (
        _feature(
            BTC,
            anchor_end_ms=anchor,
            return_5m="0.02",
            return_1h="0.04",
            return_4h="0.08",
            retrieved_at_ms=1000,
            manifest_id="btc",
        ),
        _feature(
            ETH,
            anchor_end_ms=anchor,
            return_5m="-0.01",
            return_1h="0.01",
            return_4h="0.03",
            retrieved_at_ms=1100,
            manifest_id="eth",
        ),
        _feature(
            SOL,
            anchor_end_ms=anchor,
            return_5m="0.01",
            return_1h="-0.02",
            return_4h="0.02",
            retrieved_at_ms=1200,
            manifest_id="sol",
        ),
    )

    assert enrich_historical_market_context(rows) == enrich_historical_market_context(
        tuple(reversed(rows))
    )


def test_ridge_registry_and_transform_consume_market_context() -> None:
    assert "btc_return_5m" in NUMERIC_FEATURES
    assert "market_relative_return_1h" in NUMERIC_FEATURES

    base = _feature(
        SOL,
        anchor_end_ms=FIVE - 1,
        return_5m="0.01",
        return_1h="0.02",
        return_4h="0.03",
        retrieved_at_ms=1000,
        manifest_id="sol",
    )
    one = replace(
        base,
        btc_return_5m=Decimal("0.01"),
        market_relative_return_1h=Decimal("-0.01"),
    )
    two = replace(
        base,
        anchor_end_ms=2 * FIVE - 1,
        btc_return_5m=Decimal("0.03"),
        market_relative_return_1h=Decimal("0.02"),
    )
    transform = RidgeFeatureTransform.fit((one, two))

    assert transform.vector(one) != transform.vector(two)
