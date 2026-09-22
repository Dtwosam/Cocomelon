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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveOverlapError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise HistoricalArchiveOverlapError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveOverlapError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveOverlapError(f"{field} must be an integer")
    return value


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


def load_archive_native_overlap_report(
    path: Path,
) -> ArchiveNativeOverlapReport:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive native overlap report",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveOverlapError(
            "ARCHIVE_NATIVE_OVERLAP_REPORT_INVALID"
        ) from exc

    raw_entries = _sequence(raw.get("entries"), "archive native overlap entries")
    entries: list[ArchiveNativeOverlapEntry] = []
    for index, raw_entry in enumerate(raw_entries):
        item = _mapping(raw_entry, f"archive native overlap entries[{index}]")
        raw_mismatches = _sequence(
            item.get("mismatches"),
            f"archive native overlap entries[{index}].mismatches",
        )
        mismatches: list[CandleOverlapMismatch] = []
        for mismatch_index, raw_mismatch in enumerate(raw_mismatches):
            mismatch = _mapping(
                raw_mismatch,
                (
                    f"archive native overlap entries[{index}]"
                    f".mismatches[{mismatch_index}]"
                ),
            )
            raw_fields = _sequence(
                mismatch.get("fields"),
                (
                    f"archive native overlap entries[{index}]"
                    f".mismatches[{mismatch_index}].fields"
                ),
            )
            fields = tuple(
                _string(
                    value,
                    (
                        f"archive native overlap entries[{index}]"
                        f".mismatches[{mismatch_index}].fields"
                    ),
                )
                for value in raw_fields
            )
            mismatches.append(
                CandleOverlapMismatch(
                    start_ms=_integer(
                        mismatch.get("start_ms"),
                        (
                            f"archive native overlap entries[{index}]"
                            f".mismatches[{mismatch_index}].start_ms"
                        ),
                    ),
                    fields=fields,
                )
            )

        entry = ArchiveNativeOverlapEntry(
            market=_string(item.get("market"), f"entries[{index}].market"),
            interval=_string(item.get("interval"), f"entries[{index}].interval"),
            start_ms=_integer(item.get("start_ms"), f"entries[{index}].start_ms"),
            end_ms=_integer(item.get("end_ms"), f"entries[{index}].end_ms"),
            archive_manifest_id=_string(
                item.get("archive_manifest_id"),
                f"entries[{index}].archive_manifest_id",
            ),
            native_manifest_id=_string(
                item.get("native_manifest_id"),
                f"entries[{index}].native_manifest_id",
            ),
            compared_count=_integer(
                item.get("compared_count"),
                f"entries[{index}].compared_count",
            ),
            exact_match_count=_integer(
                item.get("exact_match_count"),
                f"entries[{index}].exact_match_count",
            ),
            missing_archive_starts=tuple(
                _integer(value, f"entries[{index}].missing_archive_starts")
                for value in _sequence(
                    item.get("missing_archive_starts"),
                    f"entries[{index}].missing_archive_starts",
                )
            ),
            missing_native_starts=tuple(
                _integer(value, f"entries[{index}].missing_native_starts")
                for value in _sequence(
                    item.get("missing_native_starts"),
                    f"entries[{index}].missing_native_starts",
                )
            ),
            mismatches=tuple(mismatches),
        )
        if item.get("exact") is not entry.exact:
            raise HistoricalArchiveOverlapError(
                "ARCHIVE_NATIVE_OVERLAP_ENTRY_EXACT_MISMATCH"
            )
        entries.append(entry)

    try:
        report = ArchiveNativeOverlapReport(
            overlap_candles=_integer(
                raw.get("overlap_candles"),
                "archive native overlap overlap_candles",
            ),
            entries=tuple(entries),
            schema_version=_integer(
                raw.get("schema_version"),
                "archive native overlap schema_version",
            ),
        )
    except ValueError as exc:
        raise HistoricalArchiveOverlapError(
            "ARCHIVE_NATIVE_OVERLAP_REPORT_INVALID"
        ) from exc

    if raw.get("exact") is not report.exact:
        raise HistoricalArchiveOverlapError(
            "ARCHIVE_NATIVE_OVERLAP_EXACT_MISMATCH"
        )
    if _integer(raw.get("compared_count"), "archive native overlap compared_count") != (
        report.compared_count
    ):
        raise HistoricalArchiveOverlapError(
            "ARCHIVE_NATIVE_OVERLAP_COMPARED_COUNT_MISMATCH"
        )
    if _string(raw.get("report_id"), "archive native overlap report_id") != report.report_id:
        raise HistoricalArchiveOverlapError(
            "ARCHIVE_NATIVE_OVERLAP_REPORT_ID_MISMATCH"
        )
    return report


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
