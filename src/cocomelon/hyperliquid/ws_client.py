from __future__ import annotations

import asyncio
import json
import math
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

from cocomelon.config import MAINNET_WS_URL, Settings

CONNECT_SPACING_ENV = "COCOMELON_WS_CONNECT_SPACING_SECONDS"


class WsTransportError(RuntimeError):
    pass


class RawWebSocket(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


class WsConnection(Protocol):
    async def send_json(self, message: Mapping[str, object]) -> None: ...

    async def recv_json(self) -> dict[str, object]: ...

    async def close(self) -> None: ...


class JsonWsConnection:
    def __init__(self, socket: RawWebSocket) -> None:
        self._socket = socket

    async def send_json(self, message: Mapping[str, object]) -> None:
        await self._socket.send(json.dumps(dict(message), separators=(",", ":")))

    async def recv_json(self) -> dict[str, object]:
        raw = await self._socket.recv()
        if not isinstance(raw, str):
            raise WsTransportError("binary websocket messages are not supported")
        try:
            decoded: object = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WsTransportError("websocket returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise WsTransportError("websocket message must be a JSON object")
        return cast(dict[str, object], decoded)

    async def close(self) -> None:
        await self._socket.close()


Connector = Callable[[str], Awaitable[RawWebSocket]]
Sleep = Callable[[float], Awaitable[None]]
Monotonic = Callable[[], float]


class ConnectionSpacingGate:
    """Serialize new websocket connection slots with a minimum time separation."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last_slot_at: float | None = None

    async def wait(
        self,
        spacing_seconds: float,
        *,
        sleep: Sleep = asyncio.sleep,
        monotonic: Monotonic | None = None,
    ) -> None:
        if not math.isfinite(spacing_seconds):
            raise ValueError("connection spacing must be a finite number")
        if spacing_seconds < 0:
            raise ValueError("connection spacing must be non-negative")
        if spacing_seconds == 0:
            return

        clock = monotonic or asyncio.get_running_loop().time
        async with self._lock:
            now = clock()
            if self._last_slot_at is not None:
                remaining = spacing_seconds - (now - self._last_slot_at)
                if remaining > 0:
                    await sleep(remaining)
            self._last_slot_at = clock()


def _connect_spacing_seconds() -> float:
    raw = os.environ.get(CONNECT_SPACING_ENV)
    if raw is None or not raw.strip():
        return 0.0
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{CONNECT_SPACING_ENV} must be a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{CONNECT_SPACING_ENV} must be a finite number")
    if value < 0:
        raise ValueError(f"{CONNECT_SPACING_ENV} must be non-negative")
    return value


async def _default_connector(url: str) -> RawWebSocket:
    from websockets.asyncio.client import connect

    # Hyperliquid application ping/pong is handled by the supervisor.
    return cast(RawWebSocket, await connect(url, ping_interval=None, ping_timeout=None))


_MAINNET_CONNECTION_GATE = ConnectionSpacingGate()


async def connect_mainnet_ws(
    settings: Settings,
    *,
    connector: Connector = _default_connector,
) -> WsConnection:
    if settings.ws_url.rstrip("/") != MAINNET_WS_URL:
        raise ValueError("Phase 3 WebSocket reads require the canonical Hyperliquid mainnet URL")
    await _MAINNET_CONNECTION_GATE.wait(_connect_spacing_seconds())
    socket = await connector(MAINNET_WS_URL)
    return JsonWsConnection(socket)
