"""Synthetic wire/clock/connection fixtures, never authentic prospective evidence."""

import asyncio

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import InfoHttpError, TransportError
from cocomelon.research.volatility_transport import VolatilityTransport

BTC = MarketId("", "BTC")
DAY = 86_400_000


class Clock:
    now = 100 * DAY + 50_000

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += round(seconds * 1000)
        await asyncio.sleep(0)


class Reader:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []

    def meta_and_asset_ctxs(self):
        self.calls.append(("meta", self.clock()))
        self.clock.now += 123
        return {"synthetic": True}

    def candles(self, market, interval, *, start_ms, end_ms):
        self.calls.append(("candles", self.clock(), market, interval, start_ms, end_ms))
        return []

    def funding_history(self, market, *, start_ms):
        self.calls.append(("funding", self.clock(), market, start_ms))
        return []


def test_worker_stamps_actual_receipt_inside_thread_before_eventloop_resumes():
    async def scenario():
        clock = Clock()
        reader = Reader(clock)
        records = []
        transport = VolatilityTransport(clock=clock, info=reader, archive_ingress=records.append)
        queue = asyncio.Queue()
        await transport.fetch("meta", queue)
        kind, raw, received, started, market = queue.get_nowait()
        assert (kind, raw, market) == ("meta", {"synthetic": True}, None)
        assert received == started + 123
        assert records[-1]["received_at_ms"] == received
        assert records[-1]["capture_mode"] == "parsed_injected_reader"

    asyncio.run(scenario())


def test_real_http_wire_is_archived_before_invalid_json_is_parsed(monkeypatch):
    from cocomelon.research import volatility_transport as module

    clock = Clock()
    records = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            clock.now += 37
            return b"{invalid genuine shape"

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: Response())
    transport = VolatilityTransport(clock=clock, archive_ingress=records.append)
    with pytest.raises(TransportError, match="invalid JSON"):
        transport._request_sync("meta", None, None)
    record = records[0]
    assert record["raw_text"] == "{invalid genuine shape"
    assert record["status"] == 200 and record["received_at_ms"] == clock()
    assert record["received_at_ms"] - record["request_started_ms"] == 37


def test_http_429_is_archived_and_never_automatically_retried(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError

    from cocomelon.research import volatility_transport as module

    calls = []
    records = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise HTTPError(
            "https://api.hyperliquid.xyz/info", 429, "rate limited", {}, BytesIO(b"limit")
        )

    monkeypatch.setattr(module, "urlopen", fail)
    transport = VolatilityTransport(clock=Clock(), archive_ingress=records.append)
    with pytest.raises(InfoHttpError):
        transport._request_sync("meta", None, None)
    assert len(calls) == 1
    assert records[0]["status"] == 429 and records[0]["raw_text"] == "limit"


def test_websocket_receipt_archives_before_queue_and_closes_on_stop():
    async def scenario():
        clock = Clock()
        stop = asyncio.Event()
        records = []
        queue = asyncio.Queue()

        class Connection:
            closed = False
            sent = []

            async def send_json(self, message):
                self.sent.append(message)

            async def recv_json(self):
                clock.now += 19
                stop.set()
                return {"channel": "pong"}

            async def close(self):
                self.closed = True

        conn = Connection()

        async def connect():
            return conn

        transport = VolatilityTransport(
            clock=clock, connector=connect, info=Reader(clock), archive_ingress=records.append
        )
        await transport.websocket(queue, stop, lambda: (BTC,))
        assert conn.closed
        assert len(conn.sent) == 2
        item = queue.get_nowait()
        assert item[:2] == ("ws", {"channel": "pong"})
        assert records[0]["raw"] == {"channel": "pong"}
        assert records[0]["received_at_ms"] == item[2]

    asyncio.run(scenario())


def test_reconnect_closes_old_socket_and_waits_ten_seconds():
    async def scenario():
        clock = Clock()
        stop = asyncio.Event()
        connections = []
        times = []

        class Connection:
            closed = False

            async def send_json(self, message):
                pass

            async def recv_json(self):
                raise OSError("synthetic outage")

            async def close(self):
                self.closed = True

        async def connect():
            assert all(c.closed for c in connections)
            times.append(clock())
            conn = Connection()
            connections.append(conn)
            if len(connections) == 2:
                stop.set()
            return conn

        transport = VolatilityTransport(
            clock=clock,
            connector=connect,
            info=Reader(clock),
            archive_ingress=lambda _: None,
            sleep=clock.sleep,
        )
        await transport.websocket(asyncio.Queue(), stop, lambda: (BTC,))
        assert len(times) == 2 and times[1] - times[0] >= 10_000
        assert all(c.closed for c in connections)

    asyncio.run(scenario())


def test_daily_rest_requests_are_bounded_and_funding_preserves_outstanding_start():
    async def scenario():
        clock = Clock()
        clock.now = 100 * DAY + 5000
        reader = Reader(clock)
        priorities = []
        transport = VolatilityTransport(
            clock=clock,
            info=reader,
            archive_ingress=lambda _: None,
            request_priority=priorities.append,
            funding_requests=lambda: {BTC: 99 * DAY},
        )
        queue = asyncio.Queue()
        await transport.rest_once(queue)
        assert [c[0] for c in reader.calls].count("meta") == 1  # startup instruments
        assert [c[0] for c in reader.calls].count("candles") == 4
        assert reader.calls[-1] == ("funding", clock(), BTC, 99 * DAY)
        clock.now = 100 * DAY + 26_000
        await transport.rest_once(queue)
        clock.now = 100 * DAY + 28_000
        await transport.rest_once(queue)
        assert [c[0] for c in reader.calls].count("meta") == 2  # only one daily freshness refresh
        assert [c[0] for c in reader.calls].count("candles") == 4
        assert priorities[0] is True

    asyncio.run(scenario())


def test_ingress_archive_failure_releases_no_unarchived_observation():
    async def scenario():
        clock = Clock()

        def fail(_):
            raise OSError("synthetic archive failure")

        transport = VolatilityTransport(clock=clock, info=Reader(clock), archive_ingress=fail)
        queue = asyncio.Queue()
        with pytest.raises(OSError):
            await transport.fetch("meta", queue)
        assert queue.empty()

    asyncio.run(scenario())


def test_failed_connection_attempts_are_also_spaced_by_ten_seconds():
    async def scenario():
        clock = Clock()
        stop = asyncio.Event()
        attempts = []

        async def fail_connect():
            attempts.append(clock())
            if len(attempts) == 2:
                stop.set()
            raise OSError("synthetic TLS refusal")

        transport = VolatilityTransport(
            clock=clock,
            connector=fail_connect,
            archive_ingress=lambda _: None,
            info=Reader(clock),
            sleep=clock.sleep,
        )
        await transport.websocket(asyncio.Queue(), stop, lambda: (BTC,))
        assert len(attempts) == 2 and attempts[1] - attempts[0] >= 10_000

    asyncio.run(scenario())


def test_failed_rest_step_is_not_retried_at_poll_frequency():
    async def scenario():
        clock = Clock()
        calls = []

        class Failing(Reader):
            def meta_and_asset_ctxs(self):
                calls.append(clock())
                raise InfoHttpError(429, "synthetic")

        transport = VolatilityTransport(
            clock=clock, info=Failing(clock), archive_ingress=lambda _: None
        )
        with pytest.raises(InfoHttpError):
            await transport.rest_once(asyncio.Queue())
        clock.now += 250
        await transport.rest_once(asyncio.Queue())
        assert len(calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("wire,field", [("{bad-json", "raw_text"), (b"\x00\xff", "raw_hex")])
def test_default_ws_archives_original_wire_before_json_rejection(monkeypatch, wire, field):
    import websockets.asyncio.client

    from cocomelon.hyperliquid.ws_client import WsTransportError

    async def scenario():
        clock = Clock()
        records = []

        class RawSocket:
            async def send(self, message):
                pass

            async def recv(self):
                clock.now += 17
                return wire

            async def close(self):
                pass

        async def connect(*args, **kwargs):
            return RawSocket()

        monkeypatch.setattr(websockets.asyncio.client, "connect", connect)
        transport = VolatilityTransport(clock=clock, archive_ingress=records.append)
        connection = await transport._connector()
        with pytest.raises(WsTransportError):
            await connection.recv_json()
        assert records[0][field] == (wire if isinstance(wire, str) else wire.hex())
        assert records[0]["received_at_ms"] == clock()
        await connection.close()

    asyncio.run(scenario())


def test_application_ping_is_sent_after_twenty_seconds_without_extra_connection():
    async def scenario():
        clock = Clock()
        stop = asyncio.Event()
        sent = []
        count = 0

        class Connection:
            async def send_json(self, message):
                sent.append(message)

            async def recv_json(self):
                nonlocal count
                count += 1
                clock.now += 20_000
                if count == 2:
                    stop.set()
                return {"channel": "pong"}

            async def close(self):
                pass

        async def connect():
            return Connection()

        transport = VolatilityTransport(
            clock=clock, connector=connect, info=Reader(clock), archive_ingress=lambda _: None
        )
        await transport.websocket(asyncio.Queue(), stop, lambda: (BTC,))
        assert {"method": "ping"} in sent
        assert len([s for s in sent if s["method"] == "subscribe"]) == 2

    asyncio.run(scenario())


def test_outbound_ws_messages_are_charged_before_send_and_capped_at_reserved_headroom():
    async def scenario():
        calls = []

        class Connection:
            async def send_json(self, value):
                calls.append(value)

        transport = VolatilityTransport(clock=Clock(), archive_ingress=lambda _: None)
        for _ in range(100):
            await transport._send(Connection(), {"method": "ping"})
        with pytest.raises(RuntimeError, match="outbound message"):
            await transport._send(Connection(), {"method": "ping"})
        assert len(calls) == 100

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel_count", [1, 2])
def test_cancellation_joins_inflight_http_before_journal_close_and_retains_dirty_tail(cancel_count):
    import threading

    async def scenario():
        clock = Clock()
        started, release = threading.Event(), threading.Event()
        records = []
        archive_open = True

        class BlockingReader(Reader):
            def meta_and_asset_ctxs(self):
                started.set()
                assert release.wait(3)
                clock.now += 23
                return {"late_original_receipt": True}

        def archive(record):
            assert archive_open, "worker must not outlive open ingress journal"
            records.append(record)

        transport = VolatilityTransport(
            clock=clock, info=BlockingReader(clock), archive_ingress=archive
        )
        queue = asyncio.Queue()
        task = asyncio.create_task(transport.run(queue, asyncio.Event(), lambda: ()))
        assert await asyncio.to_thread(started.wait, 1)
        for _ in range(cancel_count):
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done(), "shutdown must join the still-running public request worker"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        archive_open = False
        assert any(r.get("raw") == {"late_original_receipt": True} for r in records)
        assert any(r.get("reason") == "cancelled_http_tail_unprocessed" for r in records)
        assert not queue.empty(), "unprocessed actual receipt cannot be acknowledged as clean"
        await asyncio.sleep(0.01)

    asyncio.run(scenario())
