from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.research.historical_backfill import (
    HistoricalCandleClient,
    backfill_candles,
)
from cocomelon.research.historical_dataset import load_candle_source
from cocomelon.research.historical_trade_archive import (
    CandleOverlapMismatch,
    reconcile_archive_candles_with_api,
)


class HistoricalArchiveOverlapError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


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


def _market_component(market: MarketId) -> str:
    return quote(market.canonical, safe="")


@dataclass(frozen=True, slots=True)
class ArchiveNativeOverlapEntry:
    market: str
    interval: str
    start_ms: int
    end_ms: int
    archive_manifest_id: str
    native_manifest_id: str
    compared_count: int
    exact_match_count: int
    missing_archive_starts: tuple[int, ...]
    missing_native_starts: tuple[int, ...]
    mismatches: tuple[CandleOverlapMismatch, ...]

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.interval not in INTERVAL_MS:
            raise ValueError("unsupported interval")
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("invalid overlap range")
        if not self.archive_manifest_id.strip() or not self.native_manifest_id.strip():
            raise ValueError("source manifest IDs must not be empty")
        if self.compared_count < 0 or self.exact_match_count < 0:
            raise ValueError("overlap counts must be non-negative")
        if self.exact_match_count > self.compared_count:
            raise ValueError("exact matches cannot exceed compared candles")

    @property
    def exact(self) -> bool:
        return (
            self.compared_count > 0
            and self.exact_match_count == self.compared_count
            and not self.missing_archive_starts
            and not self.missing_native_starts
            and not self.mismatches
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "interval": self.interval,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "archive_manifest_id": self.archive_manifest_id,
            "native_manifest_id": self.native_manifest_id,
            "compared_count": self.compared_count,
            "exact_match_count": self.exact_match_count,
            "missing_archive_starts": self.missing_archive_starts,
            "missing_native_starts": self.missing_native_starts,
            "mismatches": tuple(
                {
                    "start_ms": item.start_ms,
                    "fields": item.fields,
                }
                for item in self.mismatches
            ),
            "exact": self.exact,
        }


@dataclass(frozen=True, slots=True)
class ArchiveNativeOverlapReport:
    overlap_candles: int
    entries: tuple[ArchiveNativeOverlapEntry, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.overlap_candles <= 0:
            raise ValueError("overlap_candles must be positive")
        if not self.entries:
            raise ValueError("entries must not be empty")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def exact(self) -> bool:
        return all(item.exact for item in self.entries)

    @property
    def compared_count(self) -> int:
        return sum(item.compared_count for item in self.entries)

    def identity_payload(self) -> dict[str, object]:
        return {
            "overlap_candles": self.overlap_candles,
            "entries": tuple(item.to_dict() for item in self.entries),
            "schema_version": self.schema_version,
        }

    @property
    def report_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()[:24]

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "exact": self.exact,
            "compared_count": self.compared_count,
            "report_id": self.report_id,
        }


def validate_archive_native_overlap(
    client: HistoricalCandleClient,
    *,
    source_root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
    overlap_candles: int,
    clock_ms: Callable[[], int],
    max_candles: int = 5_000,
) -> ArchiveNativeOverlapReport:
    unique_markets = tuple(sorted(set(markets), key=lambda item: item.canonical))
    unique_intervals = tuple(sorted(set(intervals)))
    if not unique_markets:
        raise ValueError("at least one market is required")
    if not unique_intervals:
        raise ValueError("at least one interval is required")
    if overlap_candles <= 0:
        raise ValueError("overlap_candles must be positive")
    if max_candles <= 0 or overlap_candles > max_candles:
        raise ValueError("overlap_candles must fit within max_candles")
    unsupported = tuple(
        interval for interval in unique_intervals if interval not in INTERVAL_MS
    )
    if unsupported:
        raise ValueError(f"unsupported intervals: {unsupported}")

    entries: list[ArchiveNativeOverlapEntry] = []
    for market in unique_markets:
        market_component = _market_component(market)
        for interval in unique_intervals:
            archive_root = source_root / market_component / "candles" / interval
            archive_manifest, archive_candles = load_candle_source(archive_root)
            interval_ms = INTERVAL_MS[interval]
            overlap_end = archive_manifest.requested_end_ms
            overlap_start = max(
                archive_manifest.requested_start_ms,
                overlap_end - (overlap_candles - 1) * interval_ms,
            )
            archive_subset = tuple(
                candle
                for candle in archive_candles
                if overlap_start <= candle.start_ms <= overlap_end
            )
            if not archive_subset:
                raise HistoricalArchiveOverlapError(
                    f"ARCHIVE_NATIVE_OVERLAP_EMPTY_ARCHIVE:{market.canonical}:{interval}"
                )

            native_root = (
                source_root
                / "archive_native_overlap"
                / market_component
                / "candles"
                / interval
            )
            native = backfill_candles(
                client,
                market=market,
                interval=interval,
                start_ms=overlap_start,
                end_ms=overlap_end,
                root=native_root,
                clock_ms=clock_ms,
                max_candles=max_candles,
            )
            if not native.candles:
                raise HistoricalArchiveOverlapError(
                    f"ARCHIVE_NATIVE_OVERLAP_EMPTY_NATIVE:{market.canonical}:{interval}"
                )

            reconciliation = reconcile_archive_candles_with_api(
                archive_subset,
                native.candles,
            )
            entries.append(
                ArchiveNativeOverlapEntry(
                    market=market.canonical,
                    interval=interval,
                    start_ms=overlap_start,
                    end_ms=overlap_end,
                    archive_manifest_id=archive_manifest.manifest_id,
                    native_manifest_id=native.manifest.manifest_id,
                    compared_count=reconciliation.compared_count,
                    exact_match_count=reconciliation.exact_match_count,
                    missing_archive_starts=reconciliation.missing_archive_starts,
                    missing_native_starts=reconciliation.missing_api_starts,
                    mismatches=reconciliation.mismatches,
                )
            )

    report = ArchiveNativeOverlapReport(
        overlap_candles=overlap_candles,
        entries=tuple(entries),
    )
    report_path = source_root / "archive_native_overlap.json"
    _atomic_write(
        report_path,
        (_canonical_json(report.to_dict()) + "\n").encode("utf-8"),
    )
    if not report.exact:
        raise HistoricalArchiveOverlapError(
            f"ARCHIVE_NATIVE_OVERLAP_MISMATCH:{report.report_id}"
        )
    return report
