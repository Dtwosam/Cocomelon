from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.domain.market import Candle, MarketId
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.research.historical_backfill import HistoricalCandleManifest

ARCHIVE_SOURCE = "hyperliquid-mainnet-node-fills-by-block"
ARCHIVE_SCHEMA_VERSION = 1


class HistoricalTradeArchiveError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalTradeArchiveError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise HistoricalTradeArchiveError(f"{field} must be an array")
    return cast(list[object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalTradeArchiveError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalTradeArchiveError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalTradeArchiveError(f"{field} must be a boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise HistoricalTradeArchiveError(f"{field} must be numeric")
    try:
        resolved = Decimal(str(value))
    except InvalidOperation as exc:
        raise HistoricalTradeArchiveError(f"{field} must be numeric") from exc
    if not resolved.is_finite():
        raise HistoricalTradeArchiveError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class ArchivedTrade:
    market: MarketId
    time_ms: int
    px: Decimal
    sz: Decimal
    tid: int
    side: str
    crossed: bool
    source: str = ARCHIVE_SOURCE
    schema_version: int = ARCHIVE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.time_ms < 0:
            raise ValueError("time_ms must be non-negative")
        if self.px <= 0 or not self.px.is_finite():
            raise ValueError("px must be positive and finite")
        if self.sz <= 0 or not self.sz.is_finite():
            raise ValueError("sz must be positive and finite")
        if self.tid < 0:
            raise ValueError("tid must be non-negative")
        if self.side not in {"A", "B"}:
            raise ValueError("side must be A or B")
        if not self.source.strip():
            raise ValueError("source must not be empty")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")


def _same_trade_identity(first: ArchivedTrade, second: ArchivedTrade) -> bool:
    return (
        first.market == second.market
        and first.time_ms == second.time_ms
        and first.px == second.px
        and first.sz == second.sz
        and first.tid == second.tid
    )


def _prefer_trade(first: ArchivedTrade, second: ArchivedTrade) -> ArchivedTrade:
    if not _same_trade_identity(first, second):
        raise HistoricalTradeArchiveError("CONFLICTING_TRADE_DUPLICATE")
    if first.crossed == second.crossed:
        if first.side != second.side:
            raise HistoricalTradeArchiveError("CONFLICTING_TRADE_SIDE")
        return first
    return first if first.crossed else second


def parse_node_fills_by_block_lines(
    lines: Iterable[str],
    *,
    markets: Sequence[MarketId],
) -> tuple[ArchivedTrade, ...]:
    requested = {market.canonical: market for market in markets}
    if not requested:
        raise ValueError("markets must not be empty")

    by_tid: dict[tuple[str, int], ArchivedTrade] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            envelope = _mapping(json.loads(line), f"archive[{line_number}]")
        except json.JSONDecodeError as exc:
            raise HistoricalTradeArchiveError(
                f"ARCHIVE_INVALID_JSON_LINE:{line_number}"
            ) from exc

        events = _sequence(envelope.get("events"), f"archive[{line_number}].events")
        for event_index, event in enumerate(events):
            pair = _sequence(event, f"archive[{line_number}].events[{event_index}]")
            if len(pair) != 2:
                raise HistoricalTradeArchiveError("ARCHIVE_EVENT_PAIR_INVALID")
            _string(pair[0], f"archive[{line_number}].events[{event_index}].address")
            fill = _mapping(
                pair[1],
                f"archive[{line_number}].events[{event_index}].fill",
            )
            coin = _string(fill.get("coin"), "fill.coin")
            market = requested.get(coin)
            if market is None:
                continue

            trade = ArchivedTrade(
                market=market,
                time_ms=_integer(fill.get("time"), "fill.time"),
                px=_decimal(fill.get("px"), "fill.px"),
                sz=_decimal(fill.get("sz"), "fill.sz"),
                tid=_integer(fill.get("tid"), "fill.tid"),
                side=_string(fill.get("side"), "fill.side"),
                crossed=_boolean(fill.get("crossed"), "fill.crossed"),
            )
            key = (trade.market.canonical, trade.tid)
            existing = by_tid.get(key)
            by_tid[key] = trade if existing is None else _prefer_trade(existing, trade)

    return tuple(
        sorted(
            by_tid.values(),
            key=lambda item: (
                item.time_ms,
                item.tid,
                item.market.canonical,
            ),
        )
    )


def parse_node_fills_by_block_jsonl(
    data: bytes,
    *,
    markets: Sequence[MarketId],
) -> tuple[ArchivedTrade, ...]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HistoricalTradeArchiveError("ARCHIVE_NOT_UTF8") from exc
    return parse_node_fills_by_block_lines(text.splitlines(), markets=markets)


def merge_archived_trades(
    groups: Iterable[Sequence[ArchivedTrade]],
) -> tuple[ArchivedTrade, ...]:
    by_tid: dict[tuple[str, int], ArchivedTrade] = {}
    for group in groups:
        for trade in group:
            key = (trade.market.canonical, trade.tid)
            existing = by_tid.get(key)
            by_tid[key] = trade if existing is None else _prefer_trade(existing, trade)
    return tuple(
        sorted(
            by_tid.values(),
            key=lambda item: (
                item.time_ms,
                item.tid,
                item.market.canonical,
            ),
        )
    )


def aggregate_trades_to_candles(
    trades: Sequence[ArchivedTrade],
    *,
    market: MarketId,
    interval: str,
    start_ms: int,
    end_ms: int,
    received_at_ms: int,
) -> tuple[Candle, ...]:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval: {interval}")
    interval_ms = INTERVAL_MS[interval]
    if start_ms < 0 or end_ms < start_ms:
        raise ValueError("invalid requested range")
    if start_ms % interval_ms != 0 or end_ms % interval_ms != 0:
        raise HistoricalTradeArchiveError("REQUEST_GRID_MISALIGNED")
    if received_at_ms < 0:
        raise ValueError("received_at_ms must be non-negative")

    buckets: dict[int, list[ArchivedTrade]] = {}
    for trade in trades:
        if trade.market != market:
            continue
        if trade.time_ms < start_ms or trade.time_ms >= end_ms + interval_ms:
            continue
        bucket_start = (trade.time_ms // interval_ms) * interval_ms
        if bucket_start < start_ms or bucket_start > end_ms:
            continue
        buckets.setdefault(bucket_start, []).append(trade)

    candles: list[Candle] = []
    for bucket_start in sorted(buckets):
        bucket = tuple(sorted(buckets[bucket_start], key=lambda item: (item.time_ms, item.tid)))
        prices = tuple(item.px for item in bucket)
        candles.append(
            Candle(
                market=market,
                interval=interval,
                start_ms=bucket_start,
                end_ms=bucket_start + interval_ms - 1,
                open_px=prices[0],
                high_px=max(prices),
                low_px=min(prices),
                close_px=prices[-1],
                volume=sum((item.sz for item in bucket), Decimal("0")),
                trade_count=len(bucket),
                source=ARCHIVE_SOURCE,
                received_at_ms=received_at_ms,
                schema_version=ARCHIVE_SCHEMA_VERSION,
            )
        )
    return tuple(candles)


def _candle_payload(candle: Candle) -> dict[str, object]:
    return {
        "market": candle.market.canonical,
        "interval": candle.interval,
        "start_ms": candle.start_ms,
        "end_ms": candle.end_ms,
        "open_px": str(candle.open_px),
        "high_px": str(candle.high_px),
        "low_px": str(candle.low_px),
        "close_px": str(candle.close_px),
        "volume": str(candle.volume),
        "trade_count": candle.trade_count,
        "source": candle.source,
        "received_at_ms": candle.received_at_ms,
        "schema_version": candle.schema_version,
    }


def _gap_ranges(
    candles: Sequence[Candle],
    *,
    start_ms: int,
    end_ms: int,
    interval_ms: int,
) -> tuple[tuple[int, int], ...]:
    observed = {candle.start_ms for candle in candles}
    missing = tuple(
        timestamp
        for timestamp in range(start_ms, end_ms + 1, interval_ms)
        if timestamp not in observed
    )
    if not missing:
        return ()

    result: list[tuple[int, int]] = []
    range_start = missing[0]
    previous = missing[0]
    for timestamp in missing[1:]:
        if timestamp != previous + interval_ms:
            result.append((range_start, previous))
            range_start = timestamp
        previous = timestamp
    result.append((range_start, previous))
    return tuple(result)


def write_archive_candle_source(
    root: Path,
    *,
    candles: Sequence[Candle],
    market: MarketId,
    interval: str,
    start_ms: int,
    end_ms: int,
    raw_archive_digests: Sequence[str],
) -> HistoricalCandleManifest:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval: {interval}")
    ordered = tuple(sorted(candles, key=lambda item: item.start_ms))
    if any(item.market != market for item in ordered):
        raise HistoricalTradeArchiveError("MIXED_CANDLE_MARKETS")
    if any(item.interval != interval for item in ordered):
        raise HistoricalTradeArchiveError("MIXED_CANDLE_INTERVALS")
    if any(item.source != ARCHIVE_SOURCE for item in ordered):
        raise HistoricalTradeArchiveError("UNEXPECTED_CANDLE_SOURCE")

    digests = tuple(raw_archive_digests)
    if any(
        len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        for value in digests
    ):
        raise ValueError("raw_archive_digests must be lowercase SHA-256 digests")

    data = "".join(
        _canonical_json(_candle_payload(candle)) + "\n"
        for candle in ordered
    ).encode("utf-8")
    normalized_sha256 = _sha256_bytes(data)
    _atomic_write(root / "candles.jsonl", data)

    gaps = _gap_ranges(
        ordered,
        start_ms=start_ms,
        end_ms=end_ms,
        interval_ms=INTERVAL_MS[interval],
    )
    manifest = HistoricalCandleManifest(
        market=market.canonical,
        interval=interval,
        requested_start_ms=start_ms,
        requested_end_ms=end_ms,
        page_count=len(digests),
        candle_count=len(ordered),
        gap_ranges=gaps,
        complete_requested_grid=not gaps,
        raw_page_digests=digests,
        normalized_sha256=normalized_sha256,
    )
    _atomic_write(
        root / "manifest.json",
        (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8"),
    )
    return manifest


@dataclass(frozen=True, slots=True)
class CandleOverlapMismatch:
    start_ms: int
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        normalized = tuple(sorted(set(self.fields)))
        if not normalized or any(not field.strip() for field in normalized):
            raise ValueError("fields must contain non-empty values")
        object.__setattr__(self, "fields", normalized)


@dataclass(frozen=True, slots=True)
class CandleOverlapReconciliation:
    compared_count: int
    exact_match_count: int
    missing_archive_starts: tuple[int, ...]
    missing_api_starts: tuple[int, ...]
    mismatches: tuple[CandleOverlapMismatch, ...]

    def __post_init__(self) -> None:
        if self.compared_count < 0 or self.exact_match_count < 0:
            raise ValueError("overlap counts must be non-negative")
        if self.exact_match_count > self.compared_count:
            raise ValueError("exact_match_count cannot exceed compared_count")

    @property
    def exact(self) -> bool:
        return (
            self.compared_count > 0
            and self.exact_match_count == self.compared_count
            and not self.missing_archive_starts
            and not self.missing_api_starts
            and not self.mismatches
        )


def reconcile_archive_candles_with_api(
    archive_candles: Sequence[Candle],
    api_candles: Sequence[Candle],
) -> CandleOverlapReconciliation:
    if not archive_candles or not api_candles:
        raise ValueError("archive_candles and api_candles must not be empty")

    archive_market = archive_candles[0].market
    archive_interval = archive_candles[0].interval
    api_market = api_candles[0].market
    api_interval = api_candles[0].interval
    if archive_market != api_market:
        raise HistoricalTradeArchiveError("OVERLAP_MARKET_MISMATCH")
    if archive_interval != api_interval:
        raise HistoricalTradeArchiveError("OVERLAP_INTERVAL_MISMATCH")
    if any(
        candle.market != archive_market or candle.interval != archive_interval
        for candle in archive_candles
    ):
        raise HistoricalTradeArchiveError("ARCHIVE_OVERLAP_MIXED_SERIES")
    if any(
        candle.market != api_market or candle.interval != api_interval
        for candle in api_candles
    ):
        raise HistoricalTradeArchiveError("API_OVERLAP_MIXED_SERIES")

    archive_by_start = {candle.start_ms: candle for candle in archive_candles}
    api_by_start = {candle.start_ms: candle for candle in api_candles}
    shared = tuple(sorted(set(archive_by_start) & set(api_by_start)))
    missing_archive = tuple(sorted(set(api_by_start) - set(archive_by_start)))
    missing_api = tuple(sorted(set(archive_by_start) - set(api_by_start)))

    mismatches: list[CandleOverlapMismatch] = []
    exact = 0
    fields = (
        "start_ms",
        "end_ms",
        "open_px",
        "high_px",
        "low_px",
        "close_px",
        "volume",
        "trade_count",
    )
    for start_ms in shared:
        archive = archive_by_start[start_ms]
        api = api_by_start[start_ms]
        differing = tuple(
            field
            for field in fields
            if getattr(archive, field) != getattr(api, field)
        )
        if differing:
            mismatches.append(
                CandleOverlapMismatch(
                    start_ms=start_ms,
                    fields=differing,
                )
            )
        else:
            exact += 1

    return CandleOverlapReconciliation(
        compared_count=len(shared),
        exact_match_count=exact,
        missing_archive_starts=missing_archive,
        missing_api_starts=missing_api,
        mismatches=tuple(mismatches),
    )
