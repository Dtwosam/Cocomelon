import importlib
from decimal import Decimal

import pytest

from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.features.broad import BroadFeatureValues
from cocomelon.features.candles import CandleFeatureValues
from cocomelon.features.microstructure import MicrostructureFeatureValues

assembly_module = importlib.import_module("cocomelon.features.assemble")
assemble_feature_snapshot = assembly_module.assemble_feature_snapshot

BTC = MarketId("", "BTC")


def _broad() -> BroadFeatureValues:
    return BroadFeatureValues(
        source_received_at_ms=900,
        day_return=Decimal("0.05"),
        funding=Decimal("0.0001"),
        open_interest=Decimal("1000"),
        day_notional_volume=Decimal("10000000"),
        oi_change_fraction=Decimal("0.02"),
        funding_change=Decimal("0.00001"),
        mark_oracle_dislocation_bps=Decimal("3"),
    )


def _candle(
    *,
    return_15m: Decimal | None = Decimal("0.02"),
    return_1h: Decimal | None = Decimal("0.03"),
    return_4h: Decimal | None = Decimal("0.04"),
) -> CandleFeatureValues:
    return CandleFeatureValues(
        source_received_at_ms=950,
        return_5m=Decimal("0.01"),
        return_15m=return_15m,
        return_1h=return_1h,
        return_4h=return_4h,
        realized_vol_15m=Decimal("0.005"),
        range_expansion_15m=Decimal("1.2"),
        relative_volume_15m=Decimal("1.5"),
    )


def _microstructure() -> MicrostructureFeatureValues:
    return MicrostructureFeatureValues(
        source_received_at_ms=975,
        best_bid_px=Decimal("100"),
        best_ask_px=Decimal("100.1"),
        mid_px=Decimal("100.05"),
        spread_bps=Decimal("9.995002498750624687656171914"),
        bid_depth_25bps=Decimal("50000"),
        ask_depth_25bps=Decimal("45000"),
        book_imbalance=Decimal("0.05263157894736842105263157895"),
        book_age_ms=100,
    )


def test_assembly_combines_sources_and_uses_latest_receive_time() -> None:
    result = assemble_feature_snapshot(
        BTC,
        _broad(),
        candle=_candle(),
        microstructure=_microstructure(),
        as_of_ms=1_000,
        provenance=("hyperliquid-mainnet-ws", "hyperliquid-mainnet-info", "hyperliquid-mainnet-ws"),
    )

    assert result.market == BTC
    assert result.source_received_at_ms == 975
    assert result.return_5m == Decimal("0.01")
    assert result.return_15m == Decimal("0.02")
    assert result.realized_vol_15m == Decimal("0.005")
    assert result.spread_bps == Decimal("9.995002498750624687656171914")
    assert result.bid_depth_25bps == Decimal("50000")
    assert result.book_age_ms == 100
    assert result.trend_regime is TrendRegime.UP
    assert result.volatility_regime is VolatilityRegime.UNKNOWN
    assert result.provenance == (
        "hyperliquid-mainnet-info",
        "hyperliquid-mainnet-ws",
    )


@pytest.mark.parametrize(
    ("return_15m", "return_1h", "return_4h", "expected"),
    [
        (Decimal("0.01"), Decimal("0.02"), Decimal("0.03"), TrendRegime.UP),
        (Decimal("-0.01"), Decimal("-0.02"), Decimal("-0.03"), TrendRegime.DOWN),
        (Decimal("0.01"), Decimal("-0.02"), Decimal("0.03"), TrendRegime.MIXED),
        (Decimal("0"), Decimal("0.02"), Decimal("0.03"), TrendRegime.MIXED),
        (None, Decimal("0.02"), Decimal("0.03"), TrendRegime.UNKNOWN),
    ],
)
def test_assembly_assigns_explainable_trend_regime(
    return_15m: Decimal | None,
    return_1h: Decimal | None,
    return_4h: Decimal | None,
    expected: TrendRegime,
) -> None:
    result = assemble_feature_snapshot(
        BTC,
        _broad(),
        candle=_candle(
            return_15m=return_15m,
            return_1h=return_1h,
            return_4h=return_4h,
        ),
        as_of_ms=1_000,
        provenance=("hyperliquid-mainnet-info",),
    )

    assert result.trend_regime is expected


def test_assembly_without_enrichment_preserves_missing_values() -> None:
    result = assemble_feature_snapshot(
        BTC,
        _broad(),
        as_of_ms=1_000,
        provenance=("hyperliquid-mainnet-info",),
    )

    assert result.return_15m is None
    assert result.spread_bps is None
    assert result.book_age_ms is None
    assert result.trend_regime is TrendRegime.UNKNOWN


def test_assembly_snapshot_identity_is_independent_of_provenance_order() -> None:
    first = assemble_feature_snapshot(
        BTC,
        _broad(),
        candle=_candle(),
        as_of_ms=1_000,
        provenance=("z-source", "a-source"),
    )
    second = assemble_feature_snapshot(
        BTC,
        _broad(),
        candle=_candle(),
        as_of_ms=1_000,
        provenance=("a-source", "z-source", "a-source"),
    )

    assert first.snapshot_id == second.snapshot_id
