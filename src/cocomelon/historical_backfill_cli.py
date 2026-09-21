from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, TextIO
from urllib.parse import quote

from cocomelon.config import Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.research.historical_backfill import (
    HistoricalBackfillError,
    HistoricalCandleClient,
    HistoricalFundingClient,
    backfill_candles,
    backfill_funding,
    build_coverage_report,
    write_coverage_report,
)


class HistoricalDataClient(HistoricalCandleClient, HistoricalFundingClient, Protocol):
    pass


def _emit(payload: dict[str, object], *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=target,
    )


def _parse_market(value: str) -> MarketId:
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("market must not be empty")
    if ":" not in stripped:
        return MarketId(dex="", coin=stripped)
    dex, coin = stripped.split(":", 1)
    if not dex or not coin or ":" in coin:
        raise argparse.ArgumentTypeError(f"invalid canonical market: {value!r}")
    return MarketId(dex=dex, coin=coin)


def _market_path_component(market: MarketId) -> str:
    return quote(market.canonical, safe="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-backfill",
        description="Offline mainnet historical candle and funding acquisition",
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--market", required=True, action="append", type=_parse_market)
    parser.add_argument("--interval", required=True, action="append")
    parser.add_argument("--start-ms", required=True, type=int)
    parser.add_argument("--end-ms", required=True, type=int)
    parser.add_argument("--max-candles", type=int, default=5_000)
    parser.add_argument("--max-funding-items", type=int, default=500)
    parser.add_argument("--skip-funding", action="store_true")
    return parser


def acquire_historical_sources(
    client: HistoricalDataClient,
    *,
    root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
    start_ms: int,
    end_ms: int,
    clock_ms: Callable[[], int],
    max_candles: int = 5_000,
    max_funding_items: int = 500,
    include_funding: bool = True,
) -> dict[str, object]:
    if end_ms < start_ms:
        raise ValueError("end_ms must be >= start_ms")
    unique_markets = tuple(sorted(set(markets), key=lambda item: item.canonical))
    unique_intervals = tuple(sorted(set(intervals)))
    if not unique_markets:
        raise ValueError("at least one market is required")
    if not unique_intervals:
        raise ValueError("at least one candle interval is required")

    candle_manifests = []
    funding_manifests = []
    for market in unique_markets:
        market_root = root / _market_path_component(market)
        for interval in unique_intervals:
            result = backfill_candles(
                client,
                market=market,
                interval=interval,
                start_ms=start_ms,
                end_ms=end_ms,
                root=market_root / "candles" / interval,
                clock_ms=clock_ms,
                max_candles=max_candles,
            )
            candle_manifests.append(result.manifest)
        if include_funding:
            funding_result = backfill_funding(
                client,
                market=market,
                start_ms=start_ms,
                end_ms=end_ms,
                root=market_root / "funding",
                clock_ms=clock_ms,
                max_items=max_funding_items,
            )
            funding_manifests.append(funding_result.manifest)

    report = build_coverage_report(
        candle_manifests=candle_manifests,
        funding_manifests=funding_manifests,
    )
    coverage_path = root / "coverage.json"
    write_coverage_report(coverage_path, report)
    return {
        "candle_manifests": len(candle_manifests),
        "coverage_path": str(coverage_path),
        "funding_manifests": len(funding_manifests),
        "market_count": len(unique_markets),
        "report_id": report["report_id"],
        "source_count": len(candle_manifests) + len(funding_manifests),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        client = InfoClient(settings)
        payload = acquire_historical_sources(
            client,
            root=args.root,
            markets=args.market,
            intervals=args.interval,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            clock_ms=lambda: time.time_ns() // 1_000_000,
            max_candles=args.max_candles,
            max_funding_items=args.max_funding_items,
            include_funding=not args.skip_funding,
        )
    except (OSError, ValueError, HistoricalBackfillError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
