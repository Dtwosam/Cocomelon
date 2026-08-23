from decimal import Decimal

import pytest

from cocomelon.hyperliquid.normalize import (
    normalize_meta_and_asset_ctxs,
    normalize_perp_dexs,
)

PERP_DEXS = [
    None,
    {
        "name": "xyz",
        "fullName": "XYZ",
        "deployer": "0x88806a71D74ad0a510b350545C9aE490912F0888",
        "oracleUpdater": "0x1234567890545d1Df9EE64B35Fdd16966e08aCEC",
        "feeRecipient": None,
    },
]

MAIN_META_CTX = [
    {
        "universe": [
            {"name": "BTC", "szDecimals": 5, "maxLeverage": 40, "marginTableId": 1},
            {
                "name": "OLD",
                "szDecimals": 1,
                "maxLeverage": 3,
                "marginTableId": 2,
                "isDelisted": True,
                "onlyIsolated": True,
            },
        ],
        "marginTables": [],
        "collateralToken": 0,
    },
    [
        {
            "dayNtlVlm": "1000000.25",
            "funding": "0.00001",
            "markPx": "65000.5",
            "midPx": "65000.0",
            "openInterest": "123.4",
            "oraclePx": "64999.9",
            "premium": "0.0002",
            "prevDayPx": "64000",
        },
        {
            "dayNtlVlm": "0",
            "funding": "0",
            "markPx": None,
            "midPx": None,
            "openInterest": "0",
            "oraclePx": None,
            "premium": None,
            "prevDayPx": "1.0",
        },
    ],
]

HIP3_META_CTX = [
    {
        "universe": [
            {
                "name": "xyz:NVDA",
                "szDecimals": 2,
                "maxLeverage": 20,
                "marginTableId": 3,
                "onlyIsolated": True,
                "marginMode": "strictIsolated",
            }
        ],
        "marginTables": [],
        "collateralToken": 0,
    },
    [
        {
            "dayNtlVlm": "543210.12",
            "funding": "-0.00002",
            "markPx": "177.55",
            "midPx": "177.54",
            "openInterest": "2400",
            "oraclePx": "177.60",
            "premium": "-0.0001",
            "prevDayPx": "175.10",
        }
    ],
]


def test_normalize_perp_dexs_skips_native_null_entry() -> None:
    dexes = normalize_perp_dexs(PERP_DEXS)
    assert len(dexes) == 1
    assert dexes[0].name == "xyz"
    assert dexes[0].full_name == "XYZ"
    assert dexes[0].fee_recipient is None


def test_normalize_native_meta_and_contexts_preserves_delisted_and_decimals() -> None:
    snapshots = normalize_meta_and_asset_ctxs("", MAIN_META_CTX, received_at_ms=123)
    assert [snapshot.meta.market.canonical for snapshot in snapshots] == ["BTC", "OLD"]
    assert snapshots[0].context.mark_px == Decimal("65000.5")
    assert snapshots[0].context.open_interest == Decimal("123.4")
    assert snapshots[1].meta.is_delisted is True
    assert snapshots[1].context.mark_px is None
    assert snapshots[0].source == "hyperliquid-mainnet-info"
    assert snapshots[0].received_at_ms == 123
    assert snapshots[0].schema_version == 1


def test_normalize_hip3_avoids_double_prefix() -> None:
    snapshots = normalize_meta_and_asset_ctxs("xyz", HIP3_META_CTX, received_at_ms=456)
    snapshot = snapshots[0]
    assert snapshot.meta.market.dex == "xyz"
    assert snapshot.meta.market.coin == "NVDA"
    assert snapshot.meta.market.canonical == "xyz:NVDA"
    assert snapshot.meta.wire_name == "xyz:NVDA"
    assert snapshot.meta.margin_mode == "strictIsolated"


def test_normalize_meta_and_contexts_requires_positional_alignment() -> None:
    raw = [{"universe": MAIN_META_CTX[0]["universe"]}, [MAIN_META_CTX[1][0]]]
    with pytest.raises(ValueError, match="length"):
        normalize_meta_and_asset_ctxs("", raw, received_at_ms=1)


def test_normalize_hip3_rejects_prefix_mismatch() -> None:
    raw = [
        {"universe": [{"name": "hyna:AAPL", "szDecimals": 2, "maxLeverage": 10}]},
        [{
            "dayNtlVlm": "1",
            "funding": "0",
            "markPx": "1",
            "midPx": "1",
            "openInterest": "1",
            "oraclePx": "1",
            "premium": "0",
            "prevDayPx": "1",
        }],
    ]
    with pytest.raises(ValueError, match="prefix"):
        normalize_meta_and_asset_ctxs("xyz", raw, received_at_ms=1)
