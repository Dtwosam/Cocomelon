from __future__ import annotations

from collections.abc import Sequence

from cocomelon.domain.features import FeatureSnapshot, TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.features.broad import BroadFeatureValues
from cocomelon.features.candles import CandleFeatureValues
from cocomelon.features.microstructure import MicrostructureFeatureValues


def _trend_regime(candle: CandleFeatureValues | None) -> TrendRegime:
    if candle is None:
        return TrendRegime.UNKNOWN
    values = (candle.return_15m, candle.return_1h, candle.return_4h)
    if any(value is None for value in values):
        return TrendRegime.UNKNOWN
    resolved = tuple(value for value in values if value is not None)
    if all(value > 0 for value in resolved):
        return TrendRegime.UP
    if all(value < 0 for value in resolved):
        return TrendRegime.DOWN
    return TrendRegime.MIXED


def assemble_feature_snapshot(
    market: MarketId,
    broad: BroadFeatureValues,
    *,
    candle: CandleFeatureValues | None = None,
    microstructure: MicrostructureFeatureValues | None = None,
    as_of_ms: int,
    provenance: Sequence[str],
    schema_version: int = 1,
) -> FeatureSnapshot:
    received_times = [broad.source_received_at_ms]
    if candle is not None and candle.source_received_at_ms is not None:
        received_times.append(candle.source_received_at_ms)
    if microstructure is not None:
        received_times.append(microstructure.source_received_at_ms)

    return FeatureSnapshot(
        market=market,
        as_of_ms=as_of_ms,
        source_received_at_ms=max(received_times),
        schema_version=schema_version,
        day_return=broad.day_return,
        funding=broad.funding,
        open_interest=broad.open_interest,
        day_notional_volume=broad.day_notional_volume,
        oi_change_fraction=broad.oi_change_fraction,
        funding_change=broad.funding_change,
        mark_oracle_dislocation_bps=broad.mark_oracle_dislocation_bps,
        return_5m=None if candle is None else candle.return_5m,
        return_15m=None if candle is None else candle.return_15m,
        return_1h=None if candle is None else candle.return_1h,
        return_4h=None if candle is None else candle.return_4h,
        realized_vol_15m=None if candle is None else candle.realized_vol_15m,
        range_expansion_15m=None if candle is None else candle.range_expansion_15m,
        relative_volume_15m=None if candle is None else candle.relative_volume_15m,
        spread_bps=None if microstructure is None else microstructure.spread_bps,
        bid_depth_25bps=(
            None if microstructure is None else microstructure.bid_depth_25bps
        ),
        ask_depth_25bps=(
            None if microstructure is None else microstructure.ask_depth_25bps
        ),
        book_imbalance=None if microstructure is None else microstructure.book_imbalance,
        book_age_ms=None if microstructure is None else microstructure.book_age_ms,
        trend_regime=_trend_regime(candle),
        volatility_regime=VolatilityRegime.UNKNOWN,
        provenance=tuple(provenance),
    )
