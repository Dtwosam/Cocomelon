from __future__ import annotations

import json
import math
from collections.abc import Callable
from http.client import HTTPResponse
from time import sleep
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cocomelon.config import MAINNET_API_URL, Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.rate_limit import RollingRateBudget

JsonTransport = Callable[[str, dict[str, object], float], object]

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
    "1M": 2_592_000_000,
}


class Budget(Protocol):
    def acquire(self, weight: int) -> None: ...


class InfoHttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Hyperliquid info HTTP {status}: {body}")


class TransportError(RuntimeError):
    pass


def _stdlib_transport(url: str, payload: dict[str, object], timeout: float) -> object:
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "cocomelon-trader/0.1"},
        method="POST",
    )
    try:
        response: HTTPResponse
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise InfoHttpError(exc.code, body) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TransportError(str(exc)) from exc

    try:
        parsed: object = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TransportError("Hyperliquid returned invalid JSON") from exc
    return parsed


class InfoClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: JsonTransport | None = None,
        budget: Budget | None = None,
        timeout: float = 10.0,
        sleep: Callable[[float], None] = sleep,
        backoff_base: float = 0.25,
        max_attempts: int = 3,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if backoff_base < 0:
            raise ValueError("backoff_base must not be negative")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if settings.api_url.rstrip("/") != MAINNET_API_URL:
            raise ValueError(
                "Phase 2 public-data reads require the canonical Hyperliquid mainnet API URL"
            )
        self._endpoint = f"{MAINNET_API_URL}/info"
        self._transport = transport or _stdlib_transport
        self._budget = budget or RollingRateBudget()
        self._timeout = timeout
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._max_attempts = max_attempts

    def post_info(self, payload: dict[str, object], *, weight: int) -> object:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            self._budget.acquire(weight)
            try:
                result = self._transport(self._endpoint, payload, self._timeout)
                if not isinstance(result, (dict, list)):
                    raise TransportError("Hyperliquid info response must be a JSON object or array")
                return result
            except InfoHttpError as exc:
                if exc.status != 429 and not 500 <= exc.status < 600:
                    raise
                last_error = exc
            except TransportError as exc:
                last_error = exc

            if attempt < self._max_attempts:
                self._sleep(self._backoff_base * (2 ** (attempt - 1)))

        if last_error is None:
            raise RuntimeError("unreachable retry state")
        raise last_error

    def perp_dexs(self) -> object:
        return self.post_info({"type": "perpDexs"}, weight=20)

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        return self.post_info({"type": "metaAndAssetCtxs", "dex": dex}, weight=20)

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        if end_ms < start_ms:
            raise ValueError("end_ms must be >= start_ms")
        interval_ms = INTERVAL_MS.get(interval)
        if interval_ms is None:
            raise ValueError(f"unsupported candle interval: {interval}")
        count = min(5000, ((end_ms - start_ms) // interval_ms) + 1)
        weight = 20 + math.ceil(count / 60)
        return self.post_info(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": market.wire_name,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            },
            weight=weight,
        )

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        if end_ms is not None and end_ms < start_ms:
            raise ValueError("end_ms must be >= start_ms")
        payload: dict[str, object] = {
            "type": "fundingHistory",
            "coin": market.wire_name,
            "startTime": start_ms,
        }
        if end_ms is not None:
            payload["endTime"] = end_ms
        # fundingHistory has a base weight of 20 plus one per 20 returned items.
        # Reserve the documented 500-item page maximum conservatively.
        return self.post_info(payload, weight=45)
