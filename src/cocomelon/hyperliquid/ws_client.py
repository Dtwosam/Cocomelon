from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

from cocomelon.config import MAINNET_WS_URL, Settings


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


async def _default_connector(url: str) -> RawWebSocket:
    from websockets.asyncio.client import connect

    # Hyperliquid application ping/pong is handled by the supervisor.
    return cast(RawWebSocket, await connect(url, ping_interval=None, ping_timeout=None))


async def connect_mainnet_ws(
    settings: Settings,
    *,
    connector: Connector = _default_connector,
) -> WsConnection:
    if settings.ws_url.rstrip("/") != MAINNET_WS_URL:
        raise ValueError("Phase 3 WebSocket reads require the canonical Hyperliquid mainnet URL")
    socket = await connector(MAINNET_WS_URL)
    return JsonWsConnection(socket)
