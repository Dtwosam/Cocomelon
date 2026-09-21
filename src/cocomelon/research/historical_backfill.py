from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from cocomelon.domain.market import Candle, MarketId
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.hyperliquid.normalize import normalize_candles
from cocomelon.research.historical_learning import plan_candle_windows


class HistoricalBackfillError(RuntimeError):
    pass


class HistoricalCandleClient(Protocol):
    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object: ...


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
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalBackfillError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalBackfillError(f"{field} must be an integer")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalBackfillError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class HistoricalCandleManifest:
    market: str
    interval: str
    requested_start_ms: int
    requested_end_ms: int
    page_count: int
    candle_count: int
    gap_ranges: tuple[tuple[int, int], ...]
    complete_requested_grid: bool
    raw_page_digests: tuple[str, ...]
    normalized_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.interval not in INTERVAL_MS:
            raise ValueError(f"unsupported candle interval: {self.interval}")
        if self.requested_start_ms < 0:
            raise ValueError("requested_start_ms must be non-negative")
        if self.requested_end_ms < self.requested_start_ms:
            raise ValueError("requested_end_ms must be >= requested_start_ms")
        if self.page_count < 0 or self.candle_count < 0:
            raise ValueError("page_count and candle_count must be non-negative")
        if self.page_count != len(self.raw_page_digests):
            raise ValueError("page_count must match raw_page_digests")
        if any(len(value) != 64 for value in self.raw_page_digests):
            raise ValueError("raw page digests must be SHA-256 hex strings")
        if len(self.normalized_sha256) != 64:
            raise ValueError("normalized_sha256 must be a SHA-256 hex string")
        if self.complete_requested_grid != (not self.gap_ranges):
            raise ValueError("complete_requested_grid must agree with gap_ranges")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    def identity_payload(self) -> dict[str, object]:
        return {
            "market": self.market,
            "interval": self.interval,
            "requested_start_ms": self.requested_start_ms,
            "requested_end_ms": self.requested_end_ms,
            "page_count": self.page_count,
            "candle_count": self.candle_count,
            "gap_ranges": self.gap_ranges,
            "complete_requested_grid": self.complete_requested_grid,
            "raw_page_digests": self.raw_page_digests,
            "normalized_sha256": self.normalized_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def manifest_id(self) -> str:
        encoded = _canonical_json(self.identity_payload()).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:24]

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "manifest_id": self.manifest_id}


@dataclass(frozen=True, slots=True)
class HistoricalCandleBackfillResult:
    manifest: HistoricalCandleManifest
    candles: tuple[Candle, ...]


def _page_envelope(
    *,
    market: MarketId,
    interval: str,
    start_ms: int,
    end_ms: int,
    received_at_ms: int,
    payload: object,
) -> dict[str, object]:
    return {
        "kind": "candleSnapshot",
        "market": market.canonical,
        "interval": interval,
        "request": {
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
        "received_at_ms": received_at_ms,
        "payload": payload,
        "schema_version": 1,
    }


def _load_cached_page(
    path: Path,
    *,
    market: MarketId,
    interval: str,
    start_ms: int,
    end_ms: int,
) -> tuple[object, int, str]:
    try:
        raw_bytes = path.read_bytes()
        envelope = _mapping(json.loads(raw_bytes), "cached candle page")
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalBackfillError("CACHED_PAGE_UNREADABLE") from exc

    request = _mapping(envelope.get("request"), "cached candle page request")
    expected = {
        "kind": "candleSnapshot",
        "market": market.canonical,
        "interval": interval,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }
    actual = {
        "kind": envelope.get("kind"),
        "market": envelope.get("market"),
        "interval": envelope.get("interval"),
        "start_ms": request.get("start_ms"),
        "end_ms": request.get("end_ms"),
    }
    if actual != expected:
        raise HistoricalBackfillError("CACHED_PAGE_REQUEST_MISMATCH")

    schema_version = _integer(envelope.get("schema_version"), "cached page schema_version")
    if schema_version != 1:
        raise HistoricalBackfillError("CACHED_PAGE_SCHEMA_UNSUPPORTED")
    received_at_ms = _integer(envelope.get("received_at_ms"), "cached page received_at_ms")
    if received_at_ms < 0:
        raise HistoricalBackfillError("CACHED_PAGE_RECEIVED_AT_INVALID")
    if "payload" not in envelope:
        raise HistoricalBackfillError("CACHED_PAGE_PAYLOAD_MISSING")
    return envelope["payload"], received_at_ms, _sha256_bytes(raw_bytes)


def _write_new_page(
    path: Path,
    *,
    client: HistoricalCandleClient,
    market: MarketId,
    interval: str,
    start_ms: int,
    end_ms: int,
    clock_ms: Callable[[], int],
) -> tuple[object, int, str]:
    payload = client.candles(
        market,
        interval,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    received_at_ms = clock_ms()
    if received_at_ms < 0:
        raise HistoricalBackfillError("RECEIVED_AT_INVALID")
    envelope = _page_envelope(
        market=market,
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
        received_at_ms=received_at_ms,
        payload=payload,
    )
    raw_bytes = (_canonical_json(envelope) + "\n").encode("utf-8")
    _atomic_write(path, raw_bytes)
    return payload, received_at_ms, _sha256_bytes(raw_bytes)


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


def _same_candle(first: Candle, second: Candle) -> bool:
    return _candle_payload(first) == _candle_payload(second)


def _gap_ranges(
    *,
    observed_start_ms: set[int],
    start_ms: int,
    end_ms: int,
    interval_ms: int,
) -> tuple[tuple[int, int], ...]:
    missing = [
        timestamp
        for timestamp in range(start_ms, end_ms + 1, interval_ms)
        if timestamp not in observed_start_ms
    ]
    if not missing:
        return ()

    ranges: list[tuple[int, int]] = []
    range_start = missing[0]
    previous = missing[0]
    for timestamp in missing[1:]:
        if timestamp != previous + interval_ms:
            ranges.append((range_start, previous))
            range_start = timestamp
        previous = timestamp
    ranges.append((range_start, previous))
    return tuple(ranges)


def _write_normalized(path: Path, candles: tuple[Candle, ...]) -> str:
    data = "".join(_canonical_json(_candle_payload(candle)) + "\n" for candle in candles).encode(
        "utf-8"
    )
    _atomic_write(path, data)
    return _sha256_bytes(data)


def _write_manifest(path: Path, manifest: HistoricalCandleManifest) -> None:
    data = (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8")
    _atomic_write(path, data)


def backfill_candles(
    client: HistoricalCandleClient,
    *,
    market: MarketId,
    interval: str,
    start_ms: int,
    end_ms: int,
    root: Path,
    clock_ms: Callable[[], int],
    max_candles: int = 5_000,
) -> HistoricalCandleBackfillResult:
    windows = plan_candle_windows(
        interval=interval,
        start_ms=start_ms,
        end_ms=end_ms,
        max_candles=max_candles,
    )
    interval_ms = INTERVAL_MS[interval]
    if start_ms % interval_ms != 0 or end_ms % interval_ms != 0:
        raise HistoricalBackfillError("REQUEST_GRID_MISALIGNED")

    raw_root = root / "raw"
    by_start_ms: dict[int, Candle] = {}
    raw_page_digests: list[str] = []

    for index, window in enumerate(windows):
        page_path = raw_root / f"candles-{index:05d}.json"
        if page_path.exists():
            payload, received_at_ms, page_digest = _load_cached_page(
                page_path,
                market=market,
                interval=interval,
                start_ms=window.start_ms,
                end_ms=window.end_ms,
            )
        else:
            payload, received_at_ms, page_digest = _write_new_page(
                page_path,
                client=client,
                market=market,
                interval=interval,
                start_ms=window.start_ms,
                end_ms=window.end_ms,
                clock_ms=clock_ms,
            )
        raw_page_digests.append(page_digest)

        normalized = normalize_candles(
            market,
            payload,
            received_at_ms=received_at_ms,
        )
        for candle in normalized:
            if candle.interval != interval:
                raise HistoricalBackfillError("CANDLE_INTERVAL_MISMATCH")
            if candle.start_ms < window.start_ms or candle.start_ms > window.end_ms:
                raise HistoricalBackfillError("CANDLE_OUTSIDE_REQUEST_WINDOW")
            if candle.start_ms % interval_ms != start_ms % interval_ms:
                raise HistoricalBackfillError("CANDLE_GRID_MISALIGNED")
            existing = by_start_ms.get(candle.start_ms)
            if existing is not None:
                if not _same_candle(existing, candle):
                    raise HistoricalBackfillError("CONFLICTING_CANDLE_DUPLICATE")
                continue
            by_start_ms[candle.start_ms] = candle

    candles = tuple(by_start_ms[key] for key in sorted(by_start_ms))
    gaps = _gap_ranges(
        observed_start_ms=set(by_start_ms),
        start_ms=start_ms,
        end_ms=end_ms,
        interval_ms=interval_ms,
    )
    normalized_sha256 = _write_normalized(root / "candles.jsonl", candles)
    manifest = HistoricalCandleManifest(
        market=market.canonical,
        interval=interval,
        requested_start_ms=start_ms,
        requested_end_ms=end_ms,
        page_count=len(windows),
        candle_count=len(candles),
        gap_ranges=gaps,
        complete_requested_grid=not gaps,
        raw_page_digests=tuple(raw_page_digests),
        normalized_sha256=normalized_sha256,
    )
    _write_manifest(root / "manifest.json", manifest)
    return HistoricalCandleBackfillResult(manifest=manifest, candles=candles)
