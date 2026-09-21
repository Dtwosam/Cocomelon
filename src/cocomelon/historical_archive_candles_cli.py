from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import quote

from cocomelon.domain.market import Candle, MarketId
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.research.historical_backfill import (
    HistoricalFundingManifest,
    build_coverage_report,
    write_coverage_report,
)
from cocomelon.research.historical_dataset import load_funding_source
from cocomelon.research.historical_trade_archive import (
    HistoricalTradeArchiveError,
    aggregate_trades_to_candles,
    parse_node_fills_by_block_lines,
    write_archive_candle_source,
)


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


def _lz4_frame() -> Any:
    try:
        return importlib.import_module("lz4.frame")
    except ModuleNotFoundError as exc:
        raise HistoricalTradeArchiveError(
            "lz4 is required for archive import; install the research extra"
        ) from exc


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_funding_manifests(
    source_root: Path,
    markets: Sequence[MarketId],
) -> tuple[HistoricalFundingManifest, ...]:
    manifests: list[HistoricalFundingManifest] = []
    for market in markets:
        root = source_root / _market_path_component(market) / "funding"
        if not (root / "manifest.json").is_file():
            continue
        manifest, _ = load_funding_source(root)
        manifests.append(manifest)
    return tuple(manifests)


def ingest_archive_candles(
    *,
    archive_root: Path,
    source_root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
    start_ms: int,
    end_ms: int,
    received_at_ms: int,
) -> dict[str, object]:
    unique_markets = tuple(sorted(set(markets), key=lambda item: item.canonical))
    unique_intervals = tuple(sorted(set(intervals)))
    if not unique_markets:
        raise ValueError("at least one market is required")
    if not unique_intervals:
        raise ValueError("at least one interval is required")
    if end_ms < start_ms:
        raise ValueError("end_ms must be >= start_ms")
    if received_at_ms < 0:
        raise ValueError("received_at_ms must be non-negative")

    files = tuple(sorted(path for path in archive_root.rglob("*.lz4") if path.is_file()))
    if not files:
        raise HistoricalTradeArchiveError("NO_ARCHIVE_FILES")

    frame = _lz4_frame()
    digests: list[str] = []
    candles_by_key: dict[tuple[str, str], dict[int, Candle]] = {
        (market.canonical, interval): {}
        for market in unique_markets
        for interval in unique_intervals
    }
    parsed_trade_count = 0

    for path in files:
        digest = _file_sha256(path)
        digests.append(digest)
        with frame.open(path, mode="rt", encoding="utf-8") as handle:
            trades = parse_node_fills_by_block_lines(handle, markets=unique_markets)
        parsed_trade_count += len(trades)

        for market in unique_markets:
            for interval in unique_intervals:
                interval_ms = INTERVAL_MS[interval]
                if start_ms % interval_ms != 0:
                    raise HistoricalTradeArchiveError(
                        "REQUEST_START_GRID_MISALIGNED"
                    )
                interval_end_ms = end_ms - (end_ms % interval_ms)
                if interval_end_ms < start_ms:
                    continue
                candles = aggregate_trades_to_candles(
                    trades,
                    market=market,
                    interval=interval,
                    start_ms=start_ms,
                    end_ms=interval_end_ms,
                    received_at_ms=received_at_ms,
                )
                target = candles_by_key[(market.canonical, interval)]
                for candle in candles:
                    existing = target.get(candle.start_ms)
                    if existing is not None:
                        raise HistoricalTradeArchiveError(
                            "ARCHIVE_CANDLE_SPANS_MULTIPLE_FILES"
                        )
                    target[candle.start_ms] = candle

    candle_manifests = []
    for market in unique_markets:
        market_root = source_root / _market_path_component(market)
        for interval in unique_intervals:
            candle_map = candles_by_key[(market.canonical, interval)]
            candles = tuple(candle_map[key] for key in sorted(candle_map))
            interval_ms = INTERVAL_MS[interval]
            if start_ms % interval_ms != 0:
                raise HistoricalTradeArchiveError(
                    "REQUEST_START_GRID_MISALIGNED"
                )
            interval_end_ms = end_ms - (end_ms % interval_ms)
            if interval_end_ms < start_ms:
                continue
            manifest = write_archive_candle_source(
                market_root / "candles" / interval,
                candles=candles,
                market=market,
                interval=interval,
                start_ms=start_ms,
                end_ms=interval_end_ms,
                raw_archive_digests=digests,
            )
            candle_manifests.append(manifest)

    funding_manifests = _existing_funding_manifests(source_root, unique_markets)
    coverage = build_coverage_report(
        candle_manifests=candle_manifests,
        funding_manifests=funding_manifests,
    )
    write_coverage_report(source_root / "coverage.json", coverage)

    archive_manifest = {
        "kind": "hyperliquid-node-fills-by-block",
        "source": "s3://hl-mainnet-node-data/node_fills_by_block",
        "requested_start_ms": start_ms,
        "requested_end_ms": end_ms,
        "received_at_ms": received_at_ms,
        "files": tuple(
            {
                "relative_path": str(path.relative_to(archive_root)),
                "sha256": digest,
                "byte_count": path.stat().st_size,
            }
            for path, digest in zip(files, digests, strict=True)
        ),
        "schema_version": 1,
    }
    archive_manifest["manifest_id"] = hashlib.sha256(
        json.dumps(
            archive_manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()[:24]
    manifest_path = source_root / "archive_ingest.json"
    manifest_path.write_text(
        json.dumps(
            archive_manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "archive_file_count": len(files),
        "archive_manifest_id": archive_manifest["manifest_id"],
        "candle_manifests": len(candle_manifests),
        "coverage_report_id": coverage["report_id"],
        "funding_manifests": len(funding_manifests),
        "market_count": len(unique_markets),
        "parsed_trade_count": parsed_trade_count,
        "source_root": str(source_root),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive-candles",
        description="Reconstruct Hyperliquid candles from official node fill archives",
    )
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--market", required=True, action="append", type=_parse_market)
    parser.add_argument("--interval", required=True, action="append")
    parser.add_argument("--start-ms", required=True, type=int)
    parser.add_argument("--end-ms", required=True, type=int)
    parser.add_argument("--received-at-ms", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    received_at_ms = (
        time.time_ns() // 1_000_000
        if args.received_at_ms is None
        else args.received_at_ms
    )
    try:
        payload = ingest_archive_candles(
            archive_root=args.archive_root,
            source_root=args.source_root,
            markets=args.market,
            intervals=args.interval,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            received_at_ms=received_at_ms,
        )
    except (OSError, ValueError, HistoricalTradeArchiveError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
