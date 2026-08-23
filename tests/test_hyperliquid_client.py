from __future__ import annotations

import pytest

from cocomelon.config import Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import InfoClient, InfoHttpError, TransportError
from cocomelon.hyperliquid.rate_limit import RollingRateBudget


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_rate_budget_waits_until_weight_expires() -> None:
    clock = FakeClock()
    budget = RollingRateBudget(
        limit=100,
        window_seconds=60.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    budget.acquire(80)
    budget.acquire(30)

    assert clock.sleeps == [60.0]
    assert budget.used_weight == 30


def test_rate_budget_rejects_single_request_over_limit() -> None:
    budget = RollingRateBudget(limit=100)
    with pytest.raises(ValueError, match="exceeds"):
        budget.acquire(101)


def test_meta_and_asset_ctxs_sends_explicit_dex() -> None:
    calls: list[tuple[str, dict[str, object], float]] = []

    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        calls.append((url, payload, timeout))
        return [{"universe": []}, []]

    client = InfoClient(Settings(), transport=transport)
    result = client.meta_and_asset_ctxs("xyz")

    assert result == [{"universe": []}, []]
    assert calls == [
        (
            "https://api.hyperliquid.xyz/info",
            {"type": "metaAndAssetCtxs", "dex": "xyz"},
            10.0,
        )
    ]


def test_perp_dexs_uses_mainnet_info_endpoint() -> None:
    calls: list[dict[str, object]] = []

    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        assert url == "https://api.hyperliquid.xyz/info"
        calls.append(payload)
        return [None]

    client = InfoClient(Settings(), transport=transport)
    assert client.perp_dexs() == [None]
    assert calls == [{"type": "perpDexs"}]


def test_client_retries_429_and_server_errors() -> None:
    attempts = 0
    sleeps: list[float] = []

    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise InfoHttpError(429, "rate limited")
        if attempts == 2:
            raise InfoHttpError(503, "unavailable")
        return [None]

    client = InfoClient(
        Settings(),
        transport=transport,
        sleep=sleeps.append,
        backoff_base=0.25,
        max_attempts=3,
    )
    assert client.perp_dexs() == [None]
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_client_retries_transport_error() -> None:
    attempts = 0

    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransportError("temporary")
        return [None]

    client = InfoClient(Settings(), transport=transport, sleep=lambda _: None)
    assert client.perp_dexs() == [None]
    assert attempts == 2


def test_client_does_not_retry_regular_4xx() -> None:
    attempts = 0

    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        nonlocal attempts
        attempts += 1
        raise InfoHttpError(400, "bad request")

    client = InfoClient(Settings(), transport=transport, sleep=lambda _: None)
    with pytest.raises(InfoHttpError) as exc_info:
        client.perp_dexs()
    assert exc_info.value.status == 400
    assert attempts == 1


def test_candle_request_uses_canonical_wire_name_and_weight_budget() -> None:
    payloads: list[dict[str, object]] = []
    weights: list[int] = []

    class Budget:
        def acquire(self, weight: int) -> None:
            weights.append(weight)

    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        payloads.append(payload)
        return []

    client = InfoClient(Settings(), transport=transport, budget=Budget())
    market = MarketId(dex="xyz", coin="NVDA")
    client.candles(market, "15m", start_ms=0, end_ms=3_600_000)

    assert payloads == [
        {
            "type": "candleSnapshot",
            "req": {
                "coin": "xyz:NVDA",
                "interval": "15m",
                "startTime": 0,
                "endTime": 3_600_000,
            },
        }
    ]
    assert weights == [21]


def test_funding_history_reserves_conservative_page_weight() -> None:
    weights: list[int] = []

    class Budget:
        def acquire(self, weight: int) -> None:
            weights.append(weight)

    def transport(url: str, payload: dict[str, object], timeout: float) -> object:
        return []

    client = InfoClient(Settings(), transport=transport, budget=Budget())
    client.funding_history(MarketId(dex="", coin="BTC"), start_ms=1, end_ms=2)
    assert weights == [45]


def test_info_client_rejects_noncanonical_mainnet_api_url() -> None:
    settings = Settings(api_url="https://example.com")
    with pytest.raises(ValueError, match="canonical Hyperliquid mainnet"):
        InfoClient(settings, transport=lambda *_: [])
