from __future__ import annotations

from cocomelon.cli import markets_payload
from cocomelon.config import Settings

from test_hyperliquid_normalize import HIP3_META_CTX, MAIN_META_CTX, PERP_DEXS


class FakeInfoClient:
    def perp_dexs(self) -> object:
        return PERP_DEXS

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        if dex == "":
            return MAIN_META_CTX
        if dex == "xyz":
            return HIP3_META_CTX
        raise AssertionError(f"unexpected dex {dex}")


def test_markets_payload_is_read_only_safe_and_dynamic() -> None:
    settings = Settings(live_ack="SHOULD_NOT_LEAK")
    payload = markets_payload(settings, client=FakeInfoClient())

    assert payload["execution_mode"] == "paper"
    assert payload["api_url"] == "https://api.hyperliquid.xyz"
    assert payload["live_activation_valid"] is False
    assert payload["perp_dex_count"] == 2
    assert payload["hip3_dex_count"] == 1
    assert payload["market_count"] == 3
    assert payload["active_market_count"] == 2
    assert payload["delisted_market_count"] == 1
    assert payload["sample_markets"] == ["BTC", "OLD", "xyz:NVDA"]
    assert "live_ack" not in payload
    assert "SHOULD_NOT_LEAK" not in repr(payload)
