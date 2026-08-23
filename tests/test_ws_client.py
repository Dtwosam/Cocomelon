import asyncio
import json

import pytest
from cocomelon.hyperliquid.ws_client import JsonWsConnection, WsTransportError, connect_mainnet_ws

from cocomelon.config import Settings


class FakeSocket:
    def __init__(self, incoming: list[str | bytes]) -> None:
        self.incoming = list(incoming)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        return self.incoming.pop(0)

    async def close(self) -> None:
        self.closed = True


def test_json_connection_round_trip() -> None:
    async def run() -> None:
        socket = FakeSocket(['{"channel":"pong"}'])
        connection = JsonWsConnection(socket)

        await connection.send_json({"method": "ping"})
        assert json.loads(socket.sent[0]) == {"method": "ping"}
        assert await connection.recv_json() == {"channel": "pong"}

        await connection.close()
        assert socket.closed is True

    asyncio.run(run())


def test_invalid_json_and_binary_fail_explicitly() -> None:
    async def run() -> None:
        with pytest.raises(WsTransportError, match="invalid JSON"):
            await JsonWsConnection(FakeSocket(["not-json"])).recv_json()
        with pytest.raises(WsTransportError, match="binary"):
            await JsonWsConnection(FakeSocket([b"{}"])).recv_json()

    asyncio.run(run())


def test_connect_requires_canonical_mainnet() -> None:
    async def run() -> None:
        called: list[str] = []

        async def connector(url: str) -> FakeSocket:
            called.append(url)
            return FakeSocket([])

        connection = await connect_mainnet_ws(Settings(), connector=connector)
        assert called == ["wss://api.hyperliquid.xyz/ws"]
        await connection.close()

        with pytest.raises(ValueError, match="canonical"):
            await connect_mainnet_ws(
                Settings(ws_url="wss://example.com/ws"),
                connector=connector,
            )

    asyncio.run(run())
