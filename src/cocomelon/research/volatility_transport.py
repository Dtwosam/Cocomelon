"""Bounded public transport only for the frozen volatility-budget PAPER service.

No account, order, wallet or entry authority exists here. The admitted owner must
supply aggregate-IP evidence before calling ``run``. Original public wire receipts
are archived synchronously before parsing or queueing, including bad responses.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cocomelon.config import MAINNET_API_URL, Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import Budget, InfoClient, InfoHttpError, TransportError
from cocomelon.hyperliquid.ws_client import (
    RawWebSocket,
    WsConnection,
    connect_mainnet_ws,
)
from cocomelon.hyperliquid.ws_protocol import subscribe_message, unsubscribe_message
from cocomelon.research.volatility_budget import DAY_MS
from cocomelon.research.volatility_source import MARKETS

Item = tuple[str, object, int, int | None, MarketId | None]
Queue = asyncio.Queue[Item]


class PublicReader(Protocol):
    def meta_and_asset_ctxs(self) -> object: ...
    def candles(self, market: MarketId, interval: str, *, start_ms: int, end_ms: int) -> object: ...
    def funding_history(self, market: MarketId, *, start_ms: int) -> object: ...


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


class VolatilityTransport:
    """One public WS connection and bounded, nonretrying native info requests.

    Injected readers are for synthetic tests and are explicitly marked parsed-only.
    Production wire custody requires the default InfoClient with its capture
    transport. The archive callback must be thread-safe and fsync before returning.
    """

    def __init__(
        self,
        *,
        archive_ingress: Callable[[dict[str, object]], None],
        clock: Callable[[], int] = _wall_ms,
        info: PublicReader | None = None,
        budget: Budget | None = None,
        connector: Callable[[], Awaitable[WsConnection]] | None = None,
        funding_requests: Callable[[], Mapping[MarketId, int]] = dict,
        request_priority: Callable[[bool], None] = lambda _: None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_seconds: float = 0.25,
    ) -> None:
        if not 0 < poll_seconds <= 1:
            raise ValueError("transport poll must be within one second")
        self.clock = clock
        self._archive = archive_ingress
        self._injected = info is not None
        self._thread = threading.local()
        self.info = info or InfoClient(
            Settings(), transport=self._http_transport, budget=budget, max_attempts=1, timeout=3
        )
        self._injected_ws = connector is not None
        self._ws_received: int | None = None
        self._connector = connector or (
            lambda: connect_mainnet_ws(Settings(), connector=self._raw_connector)
        )
        self._funding_requests = funding_requests
        self._priority = request_priority
        self._sleep = sleep
        self._poll = poll_seconds
        self._startup_meta = False
        self._startup_attempt = -1
        self._warmup_day = -1
        self._meta_day = -1
        self._last_funding = -1
        self._last_close = -10_000
        self._sent_ms: list[int] = []
        self._inflight: set[asyncio.Task[Item]] = set()

    async def _raw_connector(self, url: str) -> RawWebSocket:
        from websockets.asyncio.client import connect

        socket = await connect(url, ping_interval=None, ping_timeout=None)
        owner = self

        class CapturedSocket:
            async def send(self, message: str) -> None:
                await socket.send(message)

            async def recv(self) -> str | bytes:
                raw = await socket.recv()
                received = owner.clock()
                owner._ws_received = received
                record: dict[str, object] = {
                    "kind": "ws_wire",
                    "source": "hyperliquid-mainnet-ws",
                    "schema_version": 1,
                    "received_at_ms": received,
                }
                if isinstance(raw, str):
                    record["raw_text"] = raw
                else:
                    record["raw_hex"] = raw.hex()
                owner._archive(record)
                return raw

            async def close(self) -> None:
                await socket.close()

        return CapturedSocket()

    def _http_transport(self, url: str, payload: dict[str, object], timeout: float) -> object:
        if url != f"{MAINNET_API_URL}/info":
            raise ValueError("only canonical mainnet public info transport is permitted")
        started = self.clock()
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "cocomelon-volatility-paper/1",
            },
            method="POST",
        )
        status = 200
        try:
            with urlopen(request, timeout=timeout) as response:
                content = response.read()
                received = self.clock()
                status = response.status
        except HTTPError as error:
            content = error.read()
            received = self.clock()
            status = error.code
        except (URLError, TimeoutError, OSError) as error:
            received = self.clock()
            self._archive(
                {
                    "kind": "http_failure",
                    "source": "hyperliquid-mainnet-info",
                    "request": payload,
                    "request_started_ms": started,
                    "received_at_ms": received,
                    "reason": type(error).__name__,
                    "schema_version": 1,
                }
            )
            raise TransportError("public info transport unavailable") from error
        self._thread.started = started
        self._thread.received = received
        # UTF-8 wire text remains original; a malformed encoding is preserved as
        # hex rather than silently replacing bytes and claiming original text.
        record: dict[str, object] = {
            "kind": "http_wire",
            "source": "hyperliquid-mainnet-info",
            "request": payload,
            "request_started_ms": started,
            "received_at_ms": received,
            "status": status,
            "schema_version": 1,
        }
        try:
            text = content.decode("utf-8")
            record["raw_text"] = text
        except UnicodeDecodeError as error:
            record["raw_hex"] = content.hex()
            self._archive(record)
            raise TransportError("public info returned invalid UTF-8") from error
        self._archive(record)  # Before any JSON interpretation or release.
        if status != 200:
            raise InfoHttpError(status, "public response retained in original ingress journal")
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise TransportError("public info returned invalid JSON") from error

    def _request_sync(self, kind: str, market: MarketId | None, start_ms: int | None) -> Item:
        self._thread.started = None
        self._thread.received = None
        started = self.clock()
        if kind == "meta":
            raw = self.info.meta_and_asset_ctxs()
        elif kind == "candles" and market in MARKETS:
            assert market is not None
            midnight = started - started % DAY_MS
            raw = self.info.candles(
                market, "8h", start_ms=midnight - 30 * DAY_MS, end_ms=midnight - 1
            )
        elif kind == "funding" and market in MARKETS and type(start_ms) is int and start_ms >= 0:
            assert market is not None
            raw = self.info.funding_history(market, start_ms=start_ms)
        else:
            raise ValueError("unsupported frozen public request")
        received = self._thread.received
        actual_started = self._thread.started
        if received is None:
            received = self.clock()  # Inside worker, never after event-loop resume.
            actual_started = started
            self._archive(
                {
                    "kind": "parsed_response",
                    "capture_mode": "parsed_injected_reader",
                    "source": "hyperliquid-mainnet-info",
                    "schema_version": 1,
                    "received_at_ms": received,
                    "request_started_ms": actual_started,
                    "request_kind": kind,
                    "market": None if market is None else market.canonical,
                    "raw": raw,
                }
            )
        return kind, raw, received, actual_started, market

    async def _enqueue(self, queue: Queue, item: Item) -> None:
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # Original receipt was already fsynced; retain explicit backpressure
            # and never discard/pretend this was an uninterrupted usable stream.
            now = self.clock()
            self._archive(
                {
                    "kind": "transport_gap",
                    "source": "hyperliquid-mainnet-ws",
                    "schema_version": 1,
                    "received_at_ms": now,
                    "reason": "original_receipt_queue_backpressure",
                }
            )
            await queue.put(item)
            await queue.put(
                ("gap", "original_receipt_queue_backpressure", self.clock(), None, None)
            )

    async def fetch(
        self,
        kind: str,
        queue: Queue,
        market: MarketId | None = None,
        *,
        start_ms: int | None = None,
    ) -> None:
        worker = asyncio.create_task(asyncio.to_thread(self._request_sync, kind, market, start_ms))
        self._inflight.add(worker)
        try:
            item = await asyncio.shield(worker)
            await self._enqueue(queue, item)
        except asyncio.CancelledError:
            # Cancelling to_thread's await does not terminate its HTTP worker.
            # Join the original capture before the owner can close its journal.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue  # Repeated owner cancellation still cannot orphan it.
                except Exception:
                    break
            dirty: Item = ("gap", "cancelled_http_tail_unprocessed", self.clock(), None, None)
            try:
                dirty = worker.result()
            except Exception:
                pass  # Wire/error capture was attempted inside the joined worker.
            try:
                queue.put_nowait(dirty)
            except asyncio.QueueFull:
                pass  # Already nonempty, so shutdown cannot acknowledge a clean tail.
            self._archive(
                {
                    "kind": "transport_gap",
                    "source": "hyperliquid-mainnet-info",
                    "schema_version": 1,
                    "received_at_ms": self.clock(),
                    "reason": "cancelled_http_tail_unprocessed",
                }
            )
            raise
        finally:
            self._inflight.discard(worker)

    async def _pause(self, seconds: float, stop: asyncio.Event) -> None:
        sleeper = asyncio.ensure_future(self._sleep(seconds))
        stopper = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait((sleeper, stopper), return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            stopper.cancel()
            await asyncio.gather(sleeper, stopper, return_exceptions=True)

    async def _gap(self, queue: Queue, error: BaseException) -> None:
        now = self.clock()
        reason = type(error).__name__
        self._archive(
            {
                "kind": "transport_gap",
                "source": "hyperliquid-mainnet-ws",
                "schema_version": 1,
                "received_at_ms": now,
                "reason": reason,
            }
        )
        await self._enqueue(queue, ("gap", reason, now, None, None))

    async def _send(self, connection: WsConnection, message: Mapping[str, object]) -> None:
        now = self.clock()
        self._sent_ms = [t for t in self._sent_ms if t > now - 60_000]
        if len(self._sent_ms) >= 100:
            raise RuntimeError("admitted websocket outbound message headroom exhausted")
        self._sent_ms.append(now)  # Failed sends remain charged.
        await connection.send_json(message)

    async def websocket(
        self,
        queue: Queue,
        stop: asyncio.Event,
        desired_markets: Callable[[], tuple[MarketId, ...]],
    ) -> None:
        while not stop.is_set():
            desired = set(desired_markets())
            if not desired <= set(MARKETS):
                raise ValueError("unsupported market subscription")
            if not desired:
                await self._pause(self._poll, stop)
                continue
            wait = 10_000 - (self.clock() - self._last_close)
            if wait > 0:
                await self._pause(wait / 1000, stop)
                continue
            connection = None
            try:
                connection = await self._connector()
                subscribed: set[MarketId] = set()
                last_message = last_ping = self.clock()
                while not stop.is_set():
                    desired = set(desired_markets())
                    if not desired <= set(MARKETS):
                        raise ValueError("unsupported market subscription")
                    for market in sorted(subscribed - desired, key=lambda m: m.canonical):
                        for kind in ("l2Book", "activeAssetCtx"):
                            await self._send(
                                connection, unsubscribe_message({"type": kind, "coin": market.coin})
                            )
                    for market in sorted(desired - subscribed, key=lambda m: m.canonical):
                        for kind in ("l2Book", "activeAssetCtx"):
                            await self._send(
                                connection, subscribe_message({"type": kind, "coin": market.coin})
                            )
                    subscribed = desired
                    if not subscribed:
                        break
                    now = self.clock()
                    if now - last_ping >= 20_000:
                        await self._send(connection, {"method": "ping"})
                        last_ping = now
                    try:
                        raw = await asyncio.wait_for(connection.recv_json(), timeout=self._poll)
                    except TimeoutError:
                        if self.clock() - last_message >= 15_000:
                            raise TimeoutError("public websocket stalled") from None
                        continue
                    received = self.clock() if self._injected_ws else self._ws_received
                    if received is None:
                        raise RuntimeError("original websocket receipt clock missing")
                    if self._injected_ws:
                        self._archive(
                            {
                                "kind": "ws_parsed",
                                "source": "hyperliquid-mainnet-ws",
                                "schema_version": 1,
                                "received_at_ms": received,
                                "raw": raw,
                                "capture_mode": "parsed_injected_reader",
                            }
                        )
                    last_message = received
                    await self._enqueue(queue, ("ws", raw, received, None, None))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await self._gap(queue, error)
            finally:
                try:
                    if connection is not None:
                        await connection.close()
                finally:
                    # Failed DNS/TLS/connect attempts consume the same bounded
                    # reconnect budget as failures after an established socket.
                    self._last_close = self.clock()

    async def rest_once(self, queue: Queue) -> None:
        if not self._startup_meta and (
            self._startup_attempt < 0 or self.clock() - self._startup_attempt >= 60_000
        ):
            self._startup_attempt = self.clock()
            self._priority(True)
            await self.fetch("meta", queue)
            self._startup_meta = True
        day, elapsed = divmod(self.clock(), DAY_MS)
        if elapsed >= 5000 and self._warmup_day != day:
            self._warmup_day = day
            self._priority(False)
            for market in MARKETS:
                await self.fetch("candles", queue, market)
        if 26_000 <= elapsed < 30_000 and self._meta_day != day:
            self._meta_day = day
            self._priority(False)
            await self.fetch("meta", queue)
        now = self.clock()
        if self._last_funding < 0 or now - self._last_funding >= 60_000:
            self._last_funding = now
            self._priority(True)
            for market, start in sorted(
                self._funding_requests().items(), key=lambda row: row[0].canonical
            ):
                await self.fetch("funding", queue, market, start_ms=start)

    async def run(
        self,
        queue: Queue,
        stop: asyncio.Event,
        desired_markets: Callable[[], tuple[MarketId, ...]],
    ) -> None:
        async def rest() -> None:
            while not stop.is_set():
                try:
                    await self.rest_once(queue)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    await self._gap(queue, error)
                await self._pause(self._poll, stop)

        tasks = [
            asyncio.create_task(self.websocket(queue, stop, desired_markets)),
            asyncio.create_task(rest()),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
