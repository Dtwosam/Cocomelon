from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from cocomelon.domain.market import Candle, FundingRate, MarketId
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.hyperliquid.normalize import SOURCE, normalize_candles, normalize_funding_history
from cocomelon.research.historical_learning import (
    FUNDING_INTERVAL_MS,
    plan_candle_windows,
    plan_funding_windows,
)


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


class HistoricalFundingClient(Protocol):
    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class HistoricalFundingManifest:
    market: str
    requested_start_ms: int
    requested_end_ms: int
    expected_interval_ms: int
    page_count: int
    funding_count: int
    observed_start_ms: int | None
    observed_end_ms: int | None
    gap_ranges: tuple[tuple[int, int], ...]
    continuous_observed_grid: bool
    raw_page_digests: tuple[str, ...]
    normalized_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.requested_start_ms < 0:
            raise ValueError("requested_start_ms must be non-negative")
        if self.requested_end_ms < self.requested_start_ms:
            raise ValueError("requested_end_ms must be >= requested_start_ms")
        if self.expected_interval_ms <= 0:
            raise ValueError("expected_interval_ms must be positive")
        if self.page_count < 0 or self.funding_count < 0:
            raise ValueError("page_count and funding_count must be non-negative")
        if self.page_count != len(self.raw_page_digests):
            raise ValueError("page_count must match raw_page_digests")
        if any(len(value) != 64 for value in self.raw_page_digests):
            raise ValueError("raw page digests must be SHA-256 hex strings")
        if len(self.normalized_sha256) != 64:
            raise ValueError("normalized_sha256 must be a SHA-256 hex string")
        if self.funding_count == 0:
            if self.observed_start_ms is not None or self.observed_end_ms is not None:
                raise ValueError("empty funding history must not have observed bounds")
        else:
            if self.observed_start_ms is None or self.observed_end_ms is None:
                raise ValueError("non-empty funding history requires observed bounds")
            if self.observed_end_ms < self.observed_start_ms:
                raise ValueError("observed_end_ms must be >= observed_start_ms")
        if self.continuous_observed_grid != (not self.gap_ranges):
            raise ValueError("continuous_observed_grid must agree with gap_ranges")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    def identity_payload(self) -> dict[str, object]:
        return {
            "market": self.market,
            "requested_start_ms": self.requested_start_ms,
            "requested_end_ms": self.requested_end_ms,
            "expected_interval_ms": self.expected_interval_ms,
            "page_count": self.page_count,
            "funding_count": self.funding_count,
            "observed_start_ms": self.observed_start_ms,
            "observed_end_ms": self.observed_end_ms,
            "gap_ranges": self.gap_ranges,
            "continuous_observed_grid": self.continuous_observed_grid,
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
class HistoricalFundingBackfillResult:
    manifest: HistoricalFundingManifest
    funding_rates: tuple[FundingRate, ...]


def _funding_page_envelope(
    *,
    market: MarketId,
    start_ms: int,
    end_ms: int,
    received_at_ms: int,
    payload: object,
) -> dict[str, object]:
    return {
        "kind": "fundingHistory",
        "market": market.canonical,
        "request": {
            "start_ms": start_ms,
            "end_ms": end_ms,
        },
        "received_at_ms": received_at_ms,
        "payload": payload,
        "schema_version": 1,
    }


def _load_cached_funding_page(
    path: Path,
    *,
    market: MarketId,
    start_ms: int,
    end_ms: int,
) -> tuple[object, int, str]:
    try:
        raw_bytes = path.read_bytes()
        envelope = _mapping(json.loads(raw_bytes), "cached funding page")
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalBackfillError("CACHED_FUNDING_PAGE_UNREADABLE") from exc

    request = _mapping(envelope.get("request"), "cached funding page request")
    expected = {
        "kind": "fundingHistory",
        "market": market.canonical,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }
    actual = {
        "kind": envelope.get("kind"),
        "market": envelope.get("market"),
        "start_ms": request.get("start_ms"),
        "end_ms": request.get("end_ms"),
    }
    if actual != expected:
        raise HistoricalBackfillError("CACHED_FUNDING_PAGE_REQUEST_MISMATCH")

    schema_version = _integer(envelope.get("schema_version"), "cached funding schema_version")
    if schema_version != 1:
        raise HistoricalBackfillError("CACHED_FUNDING_PAGE_SCHEMA_UNSUPPORTED")
    received_at_ms = _integer(
        envelope.get("received_at_ms"),
        "cached funding received_at_ms",
    )
    if received_at_ms < 0:
        raise HistoricalBackfillError("CACHED_FUNDING_PAGE_RECEIVED_AT_INVALID")
    if "payload" not in envelope:
        raise HistoricalBackfillError("CACHED_FUNDING_PAGE_PAYLOAD_MISSING")
    return envelope["payload"], received_at_ms, _sha256_bytes(raw_bytes)


def _write_new_funding_page(
    path: Path,
    *,
    client: HistoricalFundingClient,
    market: MarketId,
    start_ms: int,
    end_ms: int,
    clock_ms: Callable[[], int],
) -> tuple[object, int, str]:
    payload = client.funding_history(
        market,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    received_at_ms = clock_ms()
    if received_at_ms < 0:
        raise HistoricalBackfillError("RECEIVED_AT_INVALID")
    envelope = _funding_page_envelope(
        market=market,
        start_ms=start_ms,
        end_ms=end_ms,
        received_at_ms=received_at_ms,
        payload=payload,
    )
    raw_bytes = (_canonical_json(envelope) + "\n").encode("utf-8")
    _atomic_write(path, raw_bytes)
    return payload, received_at_ms, _sha256_bytes(raw_bytes)


def _funding_payload(rate: FundingRate) -> dict[str, object]:
    return {
        "market": rate.market.canonical,
        "time_ms": rate.time_ms,
        "funding_rate": str(rate.funding_rate),
        "premium": str(rate.premium),
        "source": rate.source,
        "received_at_ms": rate.received_at_ms,
        "schema_version": rate.schema_version,
    }


def _same_funding_rate(first: FundingRate, second: FundingRate) -> bool:
    return (
        first.market == second.market
        and first.time_ms == second.time_ms
        and first.funding_rate == second.funding_rate
        and first.premium == second.premium
        and first.source == second.source
        and first.schema_version == second.schema_version
    )


def _funding_gap_ranges(
    funding_rates: Sequence[FundingRate],
    *,
    expected_interval_ms: int,
) -> tuple[tuple[int, int], ...]:
    if expected_interval_ms <= 0:
        raise ValueError("expected_interval_ms must be positive")
    gaps: list[tuple[int, int]] = []
    for previous, current in zip(funding_rates, funding_rates[1:], strict=False):
        if current.time_ms - previous.time_ms > expected_interval_ms:
            gaps.append((previous.time_ms, current.time_ms))
    return tuple(gaps)


def _write_normalized_funding(path: Path, funding_rates: tuple[FundingRate, ...]) -> str:
    data = "".join(
        _canonical_json(_funding_payload(rate)) + "\n" for rate in funding_rates
    ).encode("utf-8")
    _atomic_write(path, data)
    return _sha256_bytes(data)


def _write_funding_manifest(path: Path, manifest: HistoricalFundingManifest) -> None:
    data = (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8")
    _atomic_write(path, data)


def backfill_funding(
    client: HistoricalFundingClient,
    *,
    market: MarketId,
    start_ms: int,
    end_ms: int,
    root: Path,
    clock_ms: Callable[[], int],
    max_items: int = 500,
    expected_interval_ms: int = FUNDING_INTERVAL_MS,
) -> HistoricalFundingBackfillResult:
    windows = plan_funding_windows(
        start_ms=start_ms,
        end_ms=end_ms,
        max_items=max_items,
        expected_interval_ms=expected_interval_ms,
    )
    raw_root = root / "raw"
    by_time_ms: dict[int, FundingRate] = {}
    raw_page_digests: list[str] = []

    for index, window in enumerate(windows):
        page_path = raw_root / f"funding-{index:05d}.json"
        if page_path.exists():
            payload, received_at_ms, page_digest = _load_cached_funding_page(
                page_path,
                market=market,
                start_ms=window.start_ms,
                end_ms=window.end_ms,
            )
        else:
            payload, received_at_ms, page_digest = _write_new_funding_page(
                page_path,
                client=client,
                market=market,
                start_ms=window.start_ms,
                end_ms=window.end_ms,
                clock_ms=clock_ms,
            )
        raw_page_digests.append(page_digest)

        normalized = normalize_funding_history(
            market,
            payload,
            received_at_ms=received_at_ms,
        )
        for rate in normalized:
            if rate.time_ms < window.start_ms or rate.time_ms > window.end_ms:
                raise HistoricalBackfillError("FUNDING_OUTSIDE_REQUEST_WINDOW")
            existing = by_time_ms.get(rate.time_ms)
            if existing is not None:
                if not _same_funding_rate(existing, rate):
                    raise HistoricalBackfillError("CONFLICTING_FUNDING_DUPLICATE")
                continue
            by_time_ms[rate.time_ms] = rate

    funding_rates = tuple(by_time_ms[key] for key in sorted(by_time_ms))
    gaps = _funding_gap_ranges(
        funding_rates,
        expected_interval_ms=expected_interval_ms,
    )
    normalized_sha256 = _write_normalized_funding(root / "funding.jsonl", funding_rates)
    manifest = HistoricalFundingManifest(
        market=market.canonical,
        requested_start_ms=start_ms,
        requested_end_ms=end_ms,
        expected_interval_ms=expected_interval_ms,
        page_count=len(windows),
        funding_count=len(funding_rates),
        observed_start_ms=funding_rates[0].time_ms if funding_rates else None,
        observed_end_ms=funding_rates[-1].time_ms if funding_rates else None,
        gap_ranges=gaps,
        continuous_observed_grid=not gaps,
        raw_page_digests=tuple(raw_page_digests),
        normalized_sha256=normalized_sha256,
    )
    _write_funding_manifest(root / "manifest.json", manifest)
    return HistoricalFundingBackfillResult(
        manifest=manifest,
        funding_rates=funding_rates,
    )


def build_coverage_report(
    *,
    candle_manifests: Sequence[HistoricalCandleManifest],
    funding_manifests: Sequence[HistoricalFundingManifest],
) -> dict[str, object]:
    sources: list[dict[str, object]] = []
    for candle_manifest in sorted(
        candle_manifests,
        key=lambda item: (
            item.market,
            item.interval,
            item.requested_start_ms,
            item.requested_end_ms,
        ),
    ):
        sources.append(
            {
                "kind": "candles",
                "source": SOURCE,
                "market": candle_manifest.market,
                "interval": candle_manifest.interval,
                "requested_start_ms": candle_manifest.requested_start_ms,
                "requested_end_ms": candle_manifest.requested_end_ms,
                "record_count": candle_manifest.candle_count,
                "gap_ranges": candle_manifest.gap_ranges,
                "complete_requested_grid": candle_manifest.complete_requested_grid,
                "manifest_id": candle_manifest.manifest_id,
                "normalized_sha256": candle_manifest.normalized_sha256,
            }
        )
    for funding_manifest in sorted(
        funding_manifests,
        key=lambda item: (
            item.market,
            item.requested_start_ms,
            item.requested_end_ms,
        ),
    ):
        sources.append(
            {
                "kind": "funding",
                "source": SOURCE,
                "market": funding_manifest.market,
                "expected_interval_ms": funding_manifest.expected_interval_ms,
                "requested_start_ms": funding_manifest.requested_start_ms,
                "requested_end_ms": funding_manifest.requested_end_ms,
                "observed_start_ms": funding_manifest.observed_start_ms,
                "observed_end_ms": funding_manifest.observed_end_ms,
                "record_count": funding_manifest.funding_count,
                "gap_ranges": funding_manifest.gap_ranges,
                "continuous_observed_grid": funding_manifest.continuous_observed_grid,
                "manifest_id": funding_manifest.manifest_id,
                "normalized_sha256": funding_manifest.normalized_sha256,
            }
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "sources": sources,
    }
    report_id = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]
    return {**payload, "report_id": report_id}


def write_coverage_report(path: Path, report: dict[str, object]) -> None:
    report_id = report.get("report_id")
    if not isinstance(report_id, str) or not report_id:
        raise HistoricalBackfillError("coverage report must contain report_id")
    data = (_canonical_json(report) + "\n").encode("utf-8")
    _atomic_write(path, data)
