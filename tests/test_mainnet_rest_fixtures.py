from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.normalize import (
    normalize_candles,
    normalize_funding_history,
    normalize_meta_and_asset_ctxs,
    normalize_perp_dexs,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hyperliquid"
CAPTURED_AT_MS = 1_787_497_992_717


def load_fixture(name: str) -> object:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_real_perp_dex_fixture_normalizes_discovered_namespaces() -> None:
    dexes = normalize_perp_dexs(load_fixture("perp_dexs.json"))
    assert len(dexes) >= 1
    assert dexes[0].name == "xyz"
    assert all(dex.name for dex in dexes)


def test_real_native_meta_context_fixture_normalizes_financial_context() -> None:
    snapshots = normalize_meta_and_asset_ctxs(
        "",
        load_fixture("meta_and_asset_ctxs_main.json"),
        received_at_ms=CAPTURED_AT_MS,
    )
    assert [snapshot.meta.market.canonical for snapshot in snapshots] == ["BTC", "ETH", "ATOM"]
    assert snapshots[0].context.mark_px is not None
    assert snapshots[0].context.mark_px > Decimal("0")
    assert snapshots[0].context.open_interest > Decimal("0")


def test_real_hip3_fixture_preserves_single_namespace_prefix() -> None:
    snapshots = normalize_meta_and_asset_ctxs(
        "xyz",
        load_fixture("meta_and_asset_ctxs_hip3.json"),
        received_at_ms=CAPTURED_AT_MS,
    )
    assert [snapshot.meta.market.canonical for snapshot in snapshots] == [
        "xyz:XYZ100",
        "xyz:TSLA",
        "xyz:NVDA",
    ]
    assert all(not item.meta.market.coin.startswith("xyz:") for item in snapshots)


def test_real_btc_candle_fixture_is_strictly_time_ordered() -> None:
    candles = normalize_candles(
        MarketId(dex="", coin="BTC"),
        load_fixture("candles_btc_15m.json"),
        received_at_ms=CAPTURED_AT_MS,
    )
    assert len(candles) >= 20
    assert candles[0].start_ms < candles[-1].start_ms
    assert candles[0].volume > Decimal("0")


def test_real_btc_funding_fixture_is_strictly_time_ordered() -> None:
    funding = normalize_funding_history(
        MarketId(dex="", coin="BTC"),
        load_fixture("funding_btc.json"),
        received_at_ms=CAPTURED_AT_MS,
    )
    assert len(funding) >= 60
    assert funding[0].time_ms < funding[-1].time_ms
