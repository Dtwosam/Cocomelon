from __future__ import annotations

import json
from pathlib import Path

from test_hyperliquid_normalize import HIP3_META_CTX, MAIN_META_CTX, PERP_DEXS

from cocomelon.hyperliquid.capture import capture_public_fixtures


class FakeCaptureClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def perp_dexs(self) -> object:
        self.calls.append(("perpDexs",))
        return PERP_DEXS

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        self.calls.append(("metaAndAssetCtxs", dex))
        return MAIN_META_CTX if dex == "" else HIP3_META_CTX

    def candles(self, market, interval: str, *, start_ms: int, end_ms: int) -> object:
        self.calls.append(("candleSnapshot", market.wire_name, interval, start_ms, end_ms))
        return [
            {
                "t": start_ms,
                "T": start_ms + 899_999,
                "s": "BTC",
                "i": "15m",
                "o": "100",
                "c": "101",
                "h": "102",
                "l": "99",
                "v": "10",
                "n": 5,
            }
        ]

    def funding_history(self, market, *, start_ms: int, end_ms: int | None = None) -> object:
        self.calls.append(("fundingHistory", market.wire_name, start_ms, end_ms))
        return [{"coin": "BTC", "fundingRate": "0.0001", "premium": "0", "time": start_ms}]


def test_capture_public_fixtures_only_reads_public_phase2_endpoints(tmp_path: Path) -> None:
    client = FakeCaptureClient()
    manifest = capture_public_fixtures(
        client,
        tmp_path,
        now_ms=10_000_000,
        sample_size=1,
    )

    assert client.calls == [
        ("perpDexs",),
        ("metaAndAssetCtxs", ""),
        ("metaAndAssetCtxs", "xyz"),
        ("candleSnapshot", "BTC", "15m", -11_600_000, 10_000_000),
        ("fundingHistory", "BTC", -249_200_000, 10_000_000),
    ]
    assert manifest["hip3_dex"] == "xyz"
    assert manifest["captured_at_ms"] == 10_000_000
    assert set(manifest["files"]) == {
        "perp_dexs.json",
        "meta_and_asset_ctxs_main.json",
        "meta_and_asset_ctxs_hip3.json",
        "candles_btc_15m.json",
        "funding_btc.json",
    }

    main = json.loads((tmp_path / "meta_and_asset_ctxs_main.json").read_text())
    assert len(main[0]["universe"]) == 1
    assert len(main[1]) == 1
    assert main[0]["universe"][0]["name"] == "BTC"
