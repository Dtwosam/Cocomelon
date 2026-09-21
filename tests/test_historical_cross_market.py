from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_cross_market import (
    HistoricalCrossMarketError,
    enrich_training_rows_with_basket_context,
)
from cocomelon.research.historical_features import HistoricalFeatureRow, HistoricalTrainingRow
from cocomelon.research.historical_learning import DirectionalOutcome

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
SOL = MarketId(dex="", coin="SOL")
FIVE = 300_000


def _feature(
    *,
    market: MarketId,
    anchor_end_ms: int,
    return_5m: str | None,
    return_15m: str | None,
    return_1h: str | None,
    return_4h: str | None,
    source: str,
    manifest: str,
    retrieved_at_ms: int = 99_000_000,
) -> HistoricalFeatureRow:
    return HistoricalFeatureRow(
        market=market,
        anchor_end_ms=anchor_end_ms,
        anchor_close_px=Decimal("100"),
        return_5m=None if return_5m is None else Decimal(return_5m),
        return_15m=None if return_15m is None else Decimal(return_15m),
        return_1h=None if return_1h is None else Decimal(return_1h),
        return_4h=None if return_4h is None else Decimal(return_4h),
        realized_vol_15m=Decimal("0.01"),
        range_expansion_15m=Decimal("1"),
        relative_volume_15m=Decimal("1"),
        funding_rate=Decimal("0"),
        funding_change=Decimal("0"),
        funding_premium=Decimal("0"),
        funding_premium_change=Decimal("0"),
        funding_age_ms=0,
        candle_15m_age_ms=0,
        trend_regime=TrendRegime.UP,
        availability_basis="exchange_timestamp",
        source_retrieved_at_ms=retrieved_at_ms,
        retrieved_after_anchor=retrieved_at_ms > anchor_end_ms,
        available_features=(
            "return_5m",
            "return_15m",
            "return_1h",
            "return_4h",
        ),
        unavailable_features=(),
        provenance=(source,),
        source_manifest_ids=(manifest,),
    )


def _row(feature: HistoricalFeatureRow, *, horizon_ms: int = FIVE) -> HistoricalTrainingRow:
    outcome = DirectionalOutcome(
        market=feature.market,
        interval="5m",
        anchor_end_ms=feature.anchor_end_ms,
        target_end_ms=feature.anchor_end_ms + horizon_ms,
        horizon_ms=horizon_ms,
        entry_px=Decimal("100"),
        exit_px=Decimal("101"),
        long_gross_return=Decimal("0.01"),
        short_gross_return=Decimal("-0.01"),
        provenance=("outcome-source",),
    )
    return HistoricalTrainingRow(feature=feature, outcome=outcome)


def _context_rows() -> tuple[HistoricalTrainingRow, ...]:
    anchor = 10 * FIVE
    return (
        _row(
            _feature(
                market=BTC,
                anchor_end_ms=anchor,
                return_5m="0.02",
                return_15m="0.03",
                return_1h="0.04",
                return_4h="0.05",
                source="btc-source",
                manifest="btc-manifest",
            )
        ),
        _row(
            _feature(
                market=ETH,
                anchor_end_ms=anchor,
                return_5m="-0.01",
                return_15m="0.00",
                return_1h="0.02",
                return_4h="0.01",
                source="eth-source",
                manifest="eth-manifest",
                retrieved_at_ms=100_000_000,
            )
        ),
        _row(
            _feature(
                market=SOL,
                anchor_end_ms=anchor,
                return_5m="0.04",
                return_15m="0.06",
                return_1h="0.08",
                return_4h="0.10",
                source="sol-source",
                manifest="sol-manifest",
            )
        ),
    )


def test_basket_context_is_same_anchor_deterministic_and_direction_neutral() -> None:
    rows = _context_rows()

    expected = enrich_training_rows_with_basket_context(rows)
    actual = enrich_training_rows_with_basket_context(tuple(reversed(rows)))

    assert actual == expected
    sol = next(row.feature for row in actual if row.market == SOL)
    assert sol.btc_return_5m == Decimal("0.02")
    assert sol.eth_return_5m == Decimal("-0.01")
    assert sol.basket_median_return_5m == Decimal("0.02")
    assert sol.basket_breadth_positive_5m == Decimal("2") / Decimal("3")
    assert sol.relative_return_5m_vs_basket == Decimal("0.02")
    assert sol.basket_return_count_5m == Decimal("3")
    expected_dispersion = (
        (
            (Decimal("0.02") - Decimal("0.01666666666666666666666666667"))
            ** 2
            + (
                Decimal("-0.01")
                - Decimal("0.01666666666666666666666666667")
            )
            ** 2
            + (
                Decimal("0.04")
                - Decimal("0.01666666666666666666666666667")
            )
            ** 2
        )
        / Decimal("3")
    ).sqrt()
    assert sol.basket_return_dispersion_5m == expected_dispersion
    assert sol.relative_return_zscore_5m_vs_basket == (
        Decimal("0.02") / expected_dispersion
    )
    assert sol.basket_median_return_1h == Decimal("0.04")
    assert sol.relative_return_4h_vs_basket == Decimal("0.05")
    assert sol.schema_version == 3


def test_basket_context_never_uses_future_anchor_state() -> None:
    current_anchor = 10 * FIVE
    future_anchor = 11 * FIVE
    rows = (
        _row(
            _feature(
                market=BTC,
                anchor_end_ms=current_anchor,
                return_5m="0.01",
                return_15m="0.01",
                return_1h="0.01",
                return_4h="0.01",
                source="btc-current",
                manifest="btc-current",
            )
        ),
        _row(
            _feature(
                market=ETH,
                anchor_end_ms=current_anchor,
                return_5m="0.02",
                return_15m="0.02",
                return_1h="0.02",
                return_4h="0.02",
                source="eth-current",
                manifest="eth-current",
            )
        ),
        _row(
            _feature(
                market=BTC,
                anchor_end_ms=future_anchor,
                return_5m="9.99",
                return_15m="9.99",
                return_1h="9.99",
                return_4h="9.99",
                source="btc-future",
                manifest="btc-future",
            )
        ),
    )

    enriched = enrich_training_rows_with_basket_context(rows)
    eth_now = next(
        row.feature
        for row in enriched
        if row.market == ETH and row.anchor_end_ms == current_anchor
    )

    assert eth_now.btc_return_5m == Decimal("0.01")
    assert eth_now.btc_return_1h == Decimal("0.01")
    assert "btc-future" not in eth_now.provenance
    assert "btc-future" not in eth_now.source_manifest_ids


def test_basket_context_marks_sparse_and_missing_reference_features_explicitly() -> None:
    row = _row(
        _feature(
            market=SOL,
            anchor_end_ms=10 * FIVE,
            return_5m="0.04",
            return_15m=None,
            return_1h="0.08",
            return_4h="0.10",
            source="sol-source",
            manifest="sol-manifest",
        )
    )

    enriched = enrich_training_rows_with_basket_context((row,))[0].feature

    assert enriched.btc_return_5m is None
    assert enriched.eth_return_5m is None
    assert enriched.basket_median_return_5m is None
    assert enriched.basket_breadth_positive_5m is None
    assert enriched.relative_return_5m_vs_basket is None
    assert enriched.basket_return_dispersion_5m is None
    assert enriched.relative_return_zscore_5m_vs_basket is None
    assert enriched.basket_return_count_5m == Decimal("1")
    assert "btc_return_5m" in enriched.unavailable_features
    assert "basket_median_return_5m" in enriched.unavailable_features
    assert "basket_return_dispersion_5m" in enriched.unavailable_features
    assert "relative_return_zscore_5m_vs_basket" in enriched.unavailable_features
    assert "basket_return_count_5m" in enriched.available_features


def test_basket_context_unions_same_anchor_provenance_and_manifests() -> None:
    enriched = enrich_training_rows_with_basket_context(_context_rows())
    sol = next(row.feature for row in enriched if row.market == SOL)

    assert sol.provenance == ("btc-source", "eth-source", "sol-source")
    assert sol.source_manifest_ids == (
        "btc-manifest",
        "eth-manifest",
        "sol-manifest",
    )
    assert sol.source_retrieved_at_ms == 100_000_000
    assert sol.retrieved_after_anchor is True


def test_basket_context_rejects_conflicting_feature_state_for_same_market_anchor() -> None:
    first = _context_rows()[0]
    conflicting_feature = replace(first.feature, return_5m=Decimal("0.99"))
    conflicting = _row(conflicting_feature, horizon_ms=2 * FIVE)

    with pytest.raises(
        HistoricalCrossMarketError,
        match="CONFLICTING_FEATURE_STATE",
    ):
        enrich_training_rows_with_basket_context((first, conflicting))



def test_zero_basket_dispersion_is_available_but_zscore_is_unavailable() -> None:
    anchor = 10 * FIVE
    rows = tuple(
        _row(
            _feature(
                market=market,
                anchor_end_ms=anchor,
                return_5m="0.01",
                return_15m="0.01",
                return_1h="0.01",
                return_4h="0.01",
                source=f"{market.canonical.lower()}-source",
                manifest=f"{market.canonical.lower()}-manifest",
            )
        )
        for market in (BTC, ETH, SOL)
    )

    enriched = enrich_training_rows_with_basket_context(rows)
    sol = next(row.feature for row in enriched if row.market == SOL)

    assert sol.basket_return_dispersion_5m == Decimal("0")
    assert sol.relative_return_zscore_5m_vs_basket is None
    assert "basket_return_dispersion_5m" in sol.available_features
    assert "relative_return_zscore_5m_vs_basket" in sol.unavailable_features
