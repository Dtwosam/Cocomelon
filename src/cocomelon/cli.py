from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    OpportunityRank,
)
from cocomelon.domain.market import MarketId, PerpMarketSnapshot
from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.registry import (
    InfoReader,
    MarketRegistry,
    MarketRegistrySnapshot,
)
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.hyperliquid.ws_client import WsConnection, connect_mainnet_ws
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor
from cocomelon.scanner.eligibility import (
    EligibilityConfig,
    derive_eligibility_thresholds,
    evaluate_eligibility,
)
from cocomelon.scanner.ranker import rank_opportunities
from cocomelon.util.time import utc_now_ms

DEFAULT_SCAN_LIMIT = 20
MAX_SCAN_LIMIT = 100
DEFAULT_SMOKE_MARKETS = ("BTC",)
DEFAULT_SMOKE_SECONDS = 5.0
MAX_SMOKE_SECONDS = 30.0
MAX_SMOKE_MARKETS = 20

SmokeResult = dict[str, object]
SmokeRunner = Callable[[Settings, float, tuple[str, ...]], SmokeResult]


@dataclass(frozen=True, slots=True)
class BroadScanResult:
    features: tuple[FeatureSnapshot, ...]
    decisions: tuple[EligibilityDecision, ...]
    ranks: tuple[OpportunityRank, ...]


class RegistryReader(Protocol):
    def refresh(self) -> MarketRegistrySnapshot: ...


class BroadScanRunner(Protocol):
    def __call__(
        self,
        markets: Mapping[str, PerpMarketSnapshot],
        *,
        as_of_ms: int,
    ) -> BroadScanResult: ...


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


def run_broad_scan(
    markets: Mapping[str, PerpMarketSnapshot],
    *,
    as_of_ms: int,
) -> BroadScanResult:
    current_by_market: dict[str, PerpMarketSnapshot] = {}
    features: list[FeatureSnapshot] = []

    for current in sorted(
        markets.values(),
        key=lambda item: item.meta.market.canonical,
    ):
        market = current.meta.market
        key = market.canonical
        if key in current_by_market:
            raise ValueError(f"duplicate current market snapshot: {key}")
        if current.context.market != market or current.received_at_ms > as_of_ms:
            continue

        current_by_market[key] = current
        broad = calculate_broad_features(current, None, as_of_ms=as_of_ms)
        features.append(
            assemble_feature_snapshot(
                market,
                broad,
                as_of_ms=as_of_ms,
                provenance=(current.source,),
            )
        )

    feature_tuple = tuple(features)
    if not feature_tuple:
        return BroadScanResult(features=(), decisions=(), ranks=())

    config = EligibilityConfig()
    thresholds = derive_eligibility_thresholds(feature_tuple, config)
    decisions = tuple(
        evaluate_eligibility(
            current_by_market[feature.market.canonical],
            feature,
            thresholds,
            config,
        )
        for feature in feature_tuple
    )
    ranks = rank_opportunities(feature_tuple, decisions, mode="coarse")
    return BroadScanResult(
        features=feature_tuple,
        decisions=decisions,
        ranks=ranks,
    )


def scan_once_payload(
    settings: Settings,
    *,
    limit: int = DEFAULT_SCAN_LIMIT,
    registry: RegistryReader | None = None,
    scanner: BroadScanRunner = run_broad_scan,
) -> dict[str, object]:
    if limit <= 0 or limit > MAX_SCAN_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SCAN_LIMIT}")

    registry_reader = registry or MarketRegistry(InfoClient(settings))
    registry_snapshot = registry_reader.refresh()
    scan = scanner(
        registry_snapshot.markets,
        as_of_ms=registry_snapshot.received_at_ms,
    )

    features = {item.market.canonical: item for item in scan.features}
    decisions = {item.market.canonical: item for item in scan.decisions}
    results: list[dict[str, object]] = []
    for rank in scan.ranks[:limit]:
        key = rank.market.canonical
        feature = features[key]
        decision = decisions[key]
        results.append(
            {
                "market": key,
                "ordinal": rank.ordinal,
                "score": float(rank.score),
                "reasons": list(decision.reasons),
                "feature_snapshot_id": feature.snapshot_id,
            }
        )

    rankable_count = sum(1 for item in scan.decisions if item.rankable)
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "market_count": len(registry_snapshot.markets),
        "feature_count": len(scan.features),
        "rankable_count": rankable_count,
        "rejected_count": len(scan.decisions) - rankable_count,
        "skipped_count": len(registry_snapshot.markets) - len(scan.features),
        "result_limit": limit,
        "results": results,
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


def _scan_limit(value: str) -> int:
    try:
        resolved = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if resolved <= 0 or resolved > MAX_SCAN_LIMIT:
        raise argparse.ArgumentTypeError(
            f"limit must be between 1 and {MAX_SCAN_LIMIT}"
        )
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("markets")

    scan = subparsers.add_parser("scan-once")
    scan.add_argument("--limit", type=_scan_limit, default=DEFAULT_SCAN_LIMIT)

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
    elif args.command == "scan-once":
        payload = scan_once_payload(settings, limit=args.limit)
    else:
        markets = tuple(args.market) if args.market else DEFAULT_SMOKE_MARKETS
        payload = stream_smoke_payload(
            settings,
            seconds=args.seconds,
            markets=markets,
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
