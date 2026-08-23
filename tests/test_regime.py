import importlib
from decimal import Decimal

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId

regime_module = importlib.import_module("cocomelon.features.regime")
assign_volatility_regimes = regime_module.assign_volatility_regimes


def _snapshot(coin: str, realized_vol: Decimal | None) -> FeatureSnapshot:
    return FeatureSnapshot(
        market=MarketId("", coin),
        as_of_ms=1_000,
        source_received_at_ms=900,
        schema_version=1,
        day_return=Decimal("0.01"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("100"),
        day_notional_volume=Decimal("1000000"),
        oi_change_fraction=None,
        funding_change=None,
        mark_oracle_dislocation_bps=Decimal("1"),
        return_5m=Decimal("0.01"),
        return_15m=Decimal("0.01"),
        return_1h=Decimal("0.01"),
        return_4h=Decimal("0.01"),
        realized_vol_15m=realized_vol,
        range_expansion_15m=Decimal("1"),
        relative_volume_15m=Decimal("1"),
        spread_bps=None,
        bid_depth_25bps=None,
        ask_depth_25bps=None,
        book_imbalance=None,
        book_age_ms=None,
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=("hyperliquid-mainnet-info",),
    )


def test_volatility_regime_uses_current_cross_section_quantiles() -> None:
    original = (
        _snapshot("A", Decimal("1")),
        _snapshot("B", Decimal("2")),
        _snapshot("C", Decimal("3")),
        _snapshot("D", Decimal("4")),
        _snapshot("E", Decimal("5")),
        _snapshot("MISSING", None),
    )

    assigned = assign_volatility_regimes(original)

    assert tuple(item.volatility_regime for item in assigned) == (
        VolatilityRegime.LOW,
        VolatilityRegime.NORMAL,
        VolatilityRegime.NORMAL,
        VolatilityRegime.NORMAL,
        VolatilityRegime.HIGH,
        VolatilityRegime.UNKNOWN,
    )
    assert all(item.volatility_regime is VolatilityRegime.UNKNOWN for item in original)


def test_volatility_regime_requires_five_non_missing_markets() -> None:
    original = (
        _snapshot("A", Decimal("1")),
        _snapshot("B", Decimal("2")),
        _snapshot("C", Decimal("3")),
        _snapshot("D", Decimal("4")),
        _snapshot("MISSING", None),
    )

    assigned = assign_volatility_regimes(original)

    assert all(item.volatility_regime is VolatilityRegime.UNKNOWN for item in assigned)


def test_volatility_regime_preserves_input_order() -> None:
    original = (
        _snapshot("E", Decimal("5")),
        _snapshot("A", Decimal("1")),
        _snapshot("C", Decimal("3")),
        _snapshot("B", Decimal("2")),
        _snapshot("D", Decimal("4")),
    )

    assigned = assign_volatility_regimes(original)

    assert tuple(item.market.coin for item in assigned) == ("E", "A", "C", "B", "D")
