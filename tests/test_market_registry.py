from __future__ import annotations

from test_hyperliquid_normalize import HIP3_META_CTX, MAIN_META_CTX, PERP_DEXS

from cocomelon.hyperliquid.registry import MarketRegistry


class FakeInfoClient:
    def __init__(self) -> None:
        self.dex_calls: list[str] = []

    def perp_dexs(self) -> object:
        return PERP_DEXS

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        self.dex_calls.append(dex)
        if dex == "":
            return MAIN_META_CTX
        if dex == "xyz":
            return HIP3_META_CTX
        raise AssertionError(f"unexpected dex {dex}")


def test_registry_discovers_native_and_every_returned_hip3_dex() -> None:
    client = FakeInfoClient()
    registry = MarketRegistry(client, now_ms=lambda: 999)

    snapshot = registry.refresh()

    assert client.dex_calls == ["", "xyz"]
    assert tuple(snapshot.markets) == ("BTC", "OLD", "xyz:NVDA")
    assert snapshot.markets["xyz:NVDA"].meta.market.coin == "NVDA"
    assert [dex.name for dex in snapshot.dexs] == ["xyz"]
    assert snapshot.received_at_ms == 999


def test_registry_lookup_uses_latest_immutable_snapshot() -> None:
    registry = MarketRegistry(FakeInfoClient(), now_ms=lambda: 111)
    registry.refresh()
    btc = registry.get("BTC")
    assert btc.meta.market.canonical == "BTC"
    assert registry.get("xyz:NVDA").meta.market.dex == "xyz"
