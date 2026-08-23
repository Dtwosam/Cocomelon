import importlib
from decimal import Decimal

import pytest

from cocomelon.domain.market import (
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)

broad_module = importlib.import_module("cocomelon.features.broad")
calculate_broad_features = broad_module.calculate_broad_features


def _snapshot(
    market: MarketId = MarketId("", "BTC"),
    *,
    received_at_ms: int = 900,
    mark_px: Decimal | None = Decimal("102"),
    mid_px: Decimal | None = Decimal("101"),
    oracle_px: Decimal | None = Decimal("100"),
    funding: Decimal = Decimal("0.0002"),
    open_interest: Decimal = Decimal("120"),
    day_ntl_vlm: Decimal = Decimal("1000000"),
    prev_day_px: Decimal = Decimal("100"),
) -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=market,
            wire_name=market.wire_name,
            sz_decimals=4,
            max_leverage=20,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=market,
            mark_px=mark_px,
            mid_px=mid_px,
            oracle_px=oracle_px,
            funding=funding,
            open_interest=open_interest,
            day_ntl_vlm=day_ntl_vlm,
            premium=None,
            prev_day_px=prev_day_px,
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def test_broad_features_prefer_mid_price_and_use_decimal_arithmetic() -> None:
    previous = _snapshot(
        received_at_ms=500,
        funding=Decimal("0.0001"),
        open_interest=Decimal("100"),
    )

    broad = calculate_broad_features(_snapshot(), previous, as_of_ms=1_000)

    assert broad.day_return == Decimal("101") / Decimal("100") - Decimal("1")
    assert broad.oi_change_fraction == Decimal("120") / Decimal("100") - Decimal("1")
    assert broad.funding_change == Decimal("0.0001")
    assert broad.mark_oracle_dislocation_bps == Decimal("200")
    assert isinstance(broad.day_return, Decimal)


def test_broad_features_fall_back_to_mark_when_mid_is_missing() -> None:
    broad = calculate_broad_features(
        _snapshot(mid_px=None, mark_px=Decimal("102")),
        None,
        as_of_ms=1_000,
    )

    assert broad.day_return == Decimal("0.02")


def test_broad_features_preserve_missing_reference_price() -> None:
    broad = calculate_broad_features(
        _snapshot(mid_px=None, mark_px=None),
        None,
        as_of_ms=1_000,
    )

    assert broad.day_return is None


def test_broad_features_require_same_market_for_previous_snapshot() -> None:
    with pytest.raises(ValueError, match="same market"):
        calculate_broad_features(
            _snapshot(),
            _snapshot(MarketId("", "ETH"), received_at_ms=500),
            as_of_ms=1_000,
        )


def test_broad_features_omit_oi_change_when_previous_oi_is_not_positive() -> None:
    broad = calculate_broad_features(
        _snapshot(),
        _snapshot(received_at_ms=500, open_interest=Decimal("0")),
        as_of_ms=1_000,
    )

    assert broad.oi_change_fraction is None


def test_broad_features_reject_future_received_inputs() -> None:
    with pytest.raises(ValueError, match="current snapshot"):
        calculate_broad_features(_snapshot(received_at_ms=1_001), None, as_of_ms=1_000)

    with pytest.raises(ValueError, match="previous snapshot"):
        calculate_broad_features(
            _snapshot(),
            _snapshot(received_at_ms=1_001),
            as_of_ms=1_000,
        )
