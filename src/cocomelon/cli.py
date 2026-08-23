from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.registry import InfoReader, MarketRegistry
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.hyperliquid.ws_client import WsConnection, connect_mainnet_ws
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor
from cocomelon.util.time import utc_now_ms

DEFAULT_SMOKE_MARKETS = ("BTC",)
DEFAULT_SMOKE_SECONDS = 5.0
MAX_SMOKE_SECONDS = 30.0
MAX_SMOKE_MARKETS = 20

SmokeResult = dict[str, object]
SmokeRunner = Callable[[Settings, float, tuple[str, ...]], SmokeResult]


def status_payload(settings: Settings) -> dict[str, Any]:
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "ws_url": settings.ws_url,
        "live_activation_valid": settings.live_activation_valid,
        "risk_per_trade": settings.risk_per_trade,
        "max_open_risk": settings.max_open_risk,
        "daily_loss_limit": settings.daily_loss_limit,
        "weekly_drawdown_limit": settings.weekly_drawdown_limit,
    }


def markets_payload(
    settings: Settings,
    *,
    client: InfoReader | None = None,
) -> dict[str, Any]:
    reader = client or InfoClient(settings)
    snapshot = MarketRegistry(reader).refresh()
    market_names = list(snapshot.markets)
    delisted_count = sum(1 for item in snapshot.markets.values() if item.meta.is_delisted)
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "live_activation_valid": settings.live_activation_valid,
        "perp_dex_count": 1 + len(snapshot.dexs),
        "hip3_dex_count": len(snapshot.dexs),
        "market_count": len(snapshot.markets),
        "active_market_count": len(snapshot.markets) - delisted_count,
        "delisted_market_count": delisted_count,
        "sample_markets": market_names[:20],
    }


def _market_id(value: str) -> MarketId:
    name = value.strip()
    if not name:
        raise ValueError("market must not be empty")
    if ":" in name:
        dex = name.split(":", 1)[0]
        return MarketId.from_wire_name(dex, name)
    return MarketId.from_wire_name("", name)


async def _stream_smoke_async(
    settings: Settings,
    seconds: float,
    markets: tuple[str, ...],
) -> SmokeResult:
    market_ids = tuple(_market_id(item) for item in markets)
    broad_dexes = tuple(sorted({item.dex for item in market_ids if item.dex}))
    plan = DeepWatchlistManager(broad_dexes=broad_dexes).reconcile(market_ids)

    event_count = 0
    gap_count = 0

    async def event_sink(_: StreamEvent) -> None:
        nonlocal event_count
        event_count += 1

    async def gap_sink(_: DataGap) -> None:
        nonlocal gap_count
        gap_count += 1

    async def connection_factory() -> WsConnection:
        return await connect_mainnet_ws(settings)

    supervisor = WebSocketSupervisor(
        connection_factory,
        plan.subscribe,
        event_sink=event_sink,
        gap_sink=gap_sink,
        clock_ms=utc_now_ms,
        utcnow=lambda: datetime.now(UTC),
    )

    try:
        await asyncio.wait_for(supervisor.run(), timeout=seconds)
    except TimeoutError:
        pass

    health = supervisor.health
    if event_count == 0:
        raise RuntimeError("stream smoke observed no market events")

    now_ms = utc_now_ms()
    return {
        "event_count": event_count,
        "gap_count": gap_count,
        "observed_server_message": health.last_server_message_ms is not None,
        "reconnect_count": health.reconnect_count,
        "duplicate_count": health.duplicate_count,
        "anomaly_count": health.anomaly_count,
        "stale_streams": list(supervisor.stale_streams(now_ms=now_ms)),
        "subscription_count": plan.desired_count,
    }


def run_stream_smoke(
    settings: Settings,
    seconds: float,
    markets: tuple[str, ...],
) -> SmokeResult:
    return asyncio.run(_stream_smoke_async(settings, seconds, markets))


def stream_smoke_payload(
    settings: Settings,
    *,
    seconds: float = DEFAULT_SMOKE_SECONDS,
    markets: tuple[str, ...] = DEFAULT_SMOKE_MARKETS,
    runner: SmokeRunner = run_stream_smoke,
) -> dict[str, object]:
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise ValueError("stream-smoke is available only in paper mode")
    if seconds <= 0 or seconds > MAX_SMOKE_SECONDS:
        raise ValueError(f"seconds must be > 0 and <= {MAX_SMOKE_SECONDS:g}")
    if not markets:
        raise ValueError("at least one market is required")
    if len(markets) > MAX_SMOKE_MARKETS:
        raise ValueError(f"stream-smoke accepts at most {MAX_SMOKE_MARKETS} markets")

    normalized_markets = tuple(_market_id(item).canonical for item in markets)
    result = runner(settings, seconds, normalized_markets)
    return {
        "execution_mode": settings.execution_mode.value,
        "ws_url": settings.ws_url,
        "seconds": seconds,
        "markets": list(normalized_markets),
        **result,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("markets")

    smoke = subparsers.add_parser("stream-smoke")
    smoke.add_argument("--seconds", type=float, default=DEFAULT_SMOKE_SECONDS)
    smoke.add_argument("--market", action="append")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()

    if args.command == "status":
        payload: dict[str, object] = status_payload(settings)
    elif args.command == "markets":
        payload = markets_payload(settings)
    else:
        markets = tuple(args.market) if args.market else DEFAULT_SMOKE_MARKETS
        payload = stream_smoke_payload(
            settings,
            seconds=args.seconds,
            markets=markets,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
