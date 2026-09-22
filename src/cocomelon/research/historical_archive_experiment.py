from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import quote

from cocomelon.domain.market import MarketId
from cocomelon.historical_archive_candles_cli import ingest_archive_candles
from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.research.historical_archive_acquisition import (
    ARCHIVE_BUCKET,
    ARCHIVE_PREFIX,
    plan_archive_shards,
)
from cocomelon.research.historical_archive_overlap import (
    ArchiveNativeOverlapReport,
    load_archive_native_overlap_report,
    validate_archive_native_overlap,
)
from cocomelon.research.historical_backfill import (
    HistoricalCandleClient,
    HistoricalFundingClient,
    backfill_funding,
    build_coverage_report,
)
from cocomelon.research.historical_dataset import (
    load_candle_source,
    load_funding_source,
)
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
    HistoricalModelComparisonReport,
    run_historical_model_comparison_from_sources,
)


class HistoricalArchiveExperimentError(RuntimeError):
    pass


class HistoricalArchiveExperimentClient(
    HistoricalCandleClient,
    HistoricalFundingClient,
    Protocol,
):
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
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveExperimentError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise HistoricalArchiveExperimentError(f"{field} must be an array")
    return cast(list[object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveExperimentError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveExperimentError(f"{field} must be an integer")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _market_path_component(market: MarketId) -> str:
    return quote(market.canonical, safe="")


@dataclass(frozen=True, slots=True)
class VerifiedArchiveCache:
    manifest_id: str
    requested_start_ms: int
    requested_end_ms: int
    shard_count: int
    total_byte_count: int

    def __post_init__(self) -> None:
        if not self.manifest_id.strip():
            raise ValueError("manifest_id must not be empty")
        if self.requested_start_ms < 0:
            raise ValueError("requested_start_ms must be non-negative")
        if self.requested_end_ms < self.requested_start_ms:
            raise ValueError("requested_end_ms must be >= requested_start_ms")
        if self.shard_count <= 0:
            raise ValueError("shard_count must be positive")
        if self.total_byte_count < 0:
            raise ValueError("total_byte_count must be non-negative")


@dataclass(frozen=True, slots=True)
class ArchiveHistoricalSourcePreparation:
    archive: VerifiedArchiveCache
    archive_ingest_manifest_id: str
    coverage_report_id: str
    overlap: ArchiveNativeOverlapReport
    markets: tuple[str, ...]
    intervals: tuple[str, ...]
    candle_manifest_count: int
    funding_manifest_count: int
    market_count: int
    parsed_trade_count: int
    archive_ingest_sha256: str
    coverage_sha256: str
    overlap_sha256: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in (
            "archive_ingest_manifest_id",
            "coverage_report_id",
            "archive_ingest_sha256",
            "coverage_sha256",
            "overlap_sha256",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        for field in (
            "archive_ingest_sha256",
            "coverage_sha256",
            "overlap_sha256",
        ):
            value = getattr(self, field)
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise ValueError(f"{field} must be lowercase SHA-256")
        if not self.overlap.exact:
            raise ValueError("prepared archive overlap must be exact")
        if tuple(sorted(set(self.markets))) != self.markets:
            raise ValueError("markets must be sorted and unique")
        if tuple(sorted(set(self.intervals))) != self.intervals:
            raise ValueError("intervals must be sorted and unique")
        if not self.markets or not self.intervals:
            raise ValueError("markets and intervals must not be empty")
        for field in (
            "candle_manifest_count",
            "funding_manifest_count",
            "market_count",
            "parsed_trade_count",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.market_count != len(self.markets):
            raise ValueError("market_count must match markets")
        if self.candle_manifest_count != len(self.markets) * len(self.intervals):
            raise ValueError("candle_manifest_count must match market/interval grid")
        if self.funding_manifest_count != len(self.markets):
            raise ValueError("funding_manifest_count must match markets")
        if self.schema_version != 1:
            raise ValueError("unsupported archive source preparation schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "archive_manifest_id": self.archive.manifest_id,
            "requested_start_ms": self.archive.requested_start_ms,
            "requested_end_ms": self.archive.requested_end_ms,
            "archive_shard_count": self.archive.shard_count,
            "archive_total_byte_count": self.archive.total_byte_count,
            "archive_ingest_manifest_id": self.archive_ingest_manifest_id,
            "coverage_report_id": self.coverage_report_id,
            "overlap_report_id": self.overlap.report_id,
            "overlap_candles": self.overlap.overlap_candles,
            "overlap_compared_count": self.overlap.compared_count,
            "markets": self.markets,
            "intervals": self.intervals,
            "candle_manifest_count": self.candle_manifest_count,
            "funding_manifest_count": self.funding_manifest_count,
            "market_count": self.market_count,
            "parsed_trade_count": self.parsed_trade_count,
            "archive_ingest_sha256": self.archive_ingest_sha256,
            "coverage_sha256": self.coverage_sha256,
            "overlap_sha256": self.overlap_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def preparation_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "preparation_id": self.preparation_id}

    def source_summary(self, source_root: Path) -> dict[str, object]:
        return {
            "archive_file_count": self.archive.shard_count,
            "archive_manifest_id": self.archive_ingest_manifest_id,
            "candle_manifests": self.candle_manifest_count,
            "coverage_report_id": self.coverage_report_id,
            "funding_manifests": self.funding_manifest_count,
            "market_count": self.market_count,
            "parsed_trade_count": self.parsed_trade_count,
            "source_root": str(source_root),
        }


@dataclass(frozen=True, slots=True)
class ArchiveHistoricalExperimentResult:
    archive: VerifiedArchiveCache
    source_summary: Mapping[str, object]
    overlap: ArchiveNativeOverlapReport
    comparison: HistoricalModelComparisonReport

    @property
    def report_id(self) -> str:
        return self.comparison.report_id

    @property
    def dataset_id(self) -> str:
        return self.comparison.dataset_id


def verify_downloaded_archive_cache(
    archive_root: Path,
    *,
    start_ms: int,
    end_ms: int,
) -> VerifiedArchiveCache:
    manifest_path = archive_root / "download_manifest.json"
    if not manifest_path.is_file():
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_MANIFEST_REQUIRED")
    try:
        manifest = _mapping(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            "download manifest",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_DOWNLOAD_MANIFEST_INVALID"
        ) from exc

    if _string(manifest.get("kind"), "download manifest kind") != (
        "hyperliquid-node-fills-by-block-download"
    ):
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_KIND_MISMATCH")
    if _string(manifest.get("bucket"), "download manifest bucket") != ARCHIVE_BUCKET:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_BUCKET_MISMATCH")
    if _string(manifest.get("prefix"), "download manifest prefix") != ARCHIVE_PREFIX:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_PREFIX_MISMATCH")
    if _integer(manifest.get("requested_start_ms"), "requested_start_ms") != start_ms:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_START_MISMATCH")
    if _integer(manifest.get("requested_end_ms"), "requested_end_ms") != end_ms:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_END_MISMATCH")

    expected = plan_archive_shards(start_ms=start_ms, end_ms=end_ms)
    expected_by_key = {item.key: item for item in expected}
    raw_shards = _sequence(manifest.get("shards"), "download manifest shards")
    if len(raw_shards) != len(expected):
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_SHARD_COUNT_MISMATCH")

    seen_keys: set[str] = set()
    listed_relative_paths: set[str] = set()
    identity_shards: list[dict[str, object]] = []
    total_byte_count = 0
    for index, raw in enumerate(raw_shards):
        item = _mapping(raw, f"download manifest shards[{index}]")
        key = _string(item.get("key"), f"shards[{index}].key")
        if key in seen_keys:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_DUPLICATE_KEY")
        seen_keys.add(key)

        shard = expected_by_key.get(key)
        if shard is None:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_UNEXPECTED_KEY")
        relative_path = _string(
            item.get("relative_path"),
            f"shards[{index}].relative_path",
        )
        if relative_path != shard.relative_path:
            raise HistoricalArchiveExperimentError(
                "ARCHIVE_DOWNLOAD_RELATIVE_PATH_MISMATCH"
            )
        if relative_path in listed_relative_paths:
            raise HistoricalArchiveExperimentError(
                "ARCHIVE_DOWNLOAD_DUPLICATE_RELATIVE_PATH"
            )
        listed_relative_paths.add(relative_path)
        if _integer(item.get("hour_start_ms"), f"shards[{index}].hour_start_ms") != (
            shard.hour_start_ms
        ):
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_HOUR_MISMATCH")

        byte_count = _integer(item.get("byte_count"), f"shards[{index}].byte_count")
        if byte_count < 0:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_SIZE_INVALID")
        etag = _string(item.get("etag"), f"shards[{index}].etag")
        sha256 = _string(item.get("sha256"), f"shards[{index}].sha256")
        if len(sha256) != 64:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_SHA256_INVALID")

        identity_shards.append(
            {
                "key": key,
                "hour_start_ms": shard.hour_start_ms,
                "relative_path": relative_path,
                "byte_count": byte_count,
                "etag": etag,
                "sha256": sha256,
            }
        )

        path = archive_root / relative_path
        if not path.is_file():
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_FILE_MISSING")
        if path.stat().st_size != byte_count:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_SIZE_MISMATCH")
        if _sha256_file(path) != sha256:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_DIGEST_MISMATCH")
        total_byte_count += byte_count

    if seen_keys != set(expected_by_key):
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_KEYS_INCOMPLETE")

    actual_lz4_paths = {
        str(path.relative_to(archive_root))
        for path in archive_root.rglob("*.lz4")
        if path.is_file()
    }
    if actual_lz4_paths != listed_relative_paths:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_LOCAL_FILE_SET_MISMATCH")

    plan_total = _integer(
        manifest.get("plan_total_byte_count"),
        "plan_total_byte_count",
    )
    if plan_total != total_byte_count:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_TOTAL_SIZE_MISMATCH")
    schema_version = _integer(manifest.get("schema_version"), "schema_version")
    if schema_version != 1:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_SCHEMA_UNSUPPORTED")

    identity_payload = {
        "kind": "hyperliquid-node-fills-by-block-download",
        "bucket": ARCHIVE_BUCKET,
        "prefix": ARCHIVE_PREFIX,
        "requested_start_ms": start_ms,
        "requested_end_ms": end_ms,
        "plan_total_byte_count": plan_total,
        "shards": tuple(identity_shards),
        "schema_version": 1,
    }
    expected_manifest_id = hashlib.sha256(
        json.dumps(
            identity_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()[:24]
    manifest_id = _string(manifest.get("manifest_id"), "manifest_id")
    if manifest_id != expected_manifest_id:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_MANIFEST_ID_MISMATCH")

    return VerifiedArchiveCache(
        manifest_id=manifest_id,
        requested_start_ms=start_ms,
        requested_end_ms=end_ms,
        shard_count=len(expected),
        total_byte_count=total_byte_count,
    )


def backfill_archive_experiment_funding(
    client: HistoricalFundingClient,
    *,
    source_root: Path,
    markets: Sequence[MarketId],
    start_ms: int,
    end_ms: int,
    clock_ms: Callable[[], int],
    max_funding_items: int = 500,
) -> tuple[str, ...]:
    unique_markets = tuple(sorted(set(markets), key=lambda item: item.canonical))
    if not unique_markets:
        raise ValueError("at least one market is required")
    manifest_ids: list[str] = []
    for market in unique_markets:
        result = backfill_funding(
            client,
            market=market,
            start_ms=start_ms,
            end_ms=end_ms,
            root=source_root / _market_path_component(market) / "funding",
            clock_ms=clock_ms,
            max_items=max_funding_items,
        )
        manifest_ids.append(result.manifest.manifest_id)
    return tuple(manifest_ids)


def _summary_integer(summary: Mapping[str, object], field: str) -> int:
    value = summary.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveExperimentError(
            f"ARCHIVE_SOURCE_SUMMARY_{field.upper()}_INVALID"
        )
    return value


def _summary_string(summary: Mapping[str, object], field: str) -> str:
    value = summary.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveExperimentError(
            f"ARCHIVE_SOURCE_SUMMARY_{field.upper()}_INVALID"
        )
    return value


def _build_source_preparation(
    *,
    archive: VerifiedArchiveCache,
    source_summary: Mapping[str, object],
    overlap: ArchiveNativeOverlapReport,
    source_root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
) -> ArchiveHistoricalSourcePreparation:
    return ArchiveHistoricalSourcePreparation(
        archive=archive,
        archive_ingest_manifest_id=_summary_string(
            source_summary,
            "archive_manifest_id",
        ),
        coverage_report_id=_summary_string(source_summary, "coverage_report_id"),
        overlap=overlap,
        markets=tuple(sorted({market.canonical for market in markets})),
        intervals=tuple(sorted(set(intervals))),
        candle_manifest_count=_summary_integer(
            source_summary,
            "candle_manifests",
        ),
        funding_manifest_count=_summary_integer(
            source_summary,
            "funding_manifests",
        ),
        market_count=_summary_integer(source_summary, "market_count"),
        parsed_trade_count=_summary_integer(
            source_summary,
            "parsed_trade_count",
        ),
        archive_ingest_sha256=_sha256_file(source_root / "archive_ingest.json"),
        coverage_sha256=_sha256_file(source_root / "coverage.json"),
        overlap_sha256=_sha256_file(
            source_root / "archive_native_overlap.json"
        ),
    )


def write_archive_source_preparation(
    source_root: Path,
    preparation: ArchiveHistoricalSourcePreparation,
) -> Path:
    path = source_root / "source-preparation.json"
    payload = (_canonical_json(preparation.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveExperimentError(
                "ARCHIVE_SOURCE_PREPARATION_CONFLICT"
            )
        return path
    _atomic_write(path, payload)
    return path


def prepare_archive_historical_sources(
    client: HistoricalArchiveExperimentClient,
    *,
    archive_root: Path,
    source_root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
    start_ms: int,
    end_ms: int,
    clock_ms: Callable[[], int],
    max_funding_items: int = 500,
    overlap_candles: int = 96,
) -> ArchiveHistoricalSourcePreparation:
    archive = verify_downloaded_archive_cache(
        archive_root,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    backfill_archive_experiment_funding(
        client,
        source_root=source_root,
        markets=markets,
        start_ms=start_ms,
        end_ms=end_ms,
        clock_ms=clock_ms,
        max_funding_items=max_funding_items,
    )
    source_summary = ingest_archive_candles(
        archive_root=archive_root,
        source_root=source_root,
        markets=markets,
        intervals=intervals,
        start_ms=start_ms,
        end_ms=end_ms,
        received_at_ms=clock_ms(),
    )
    overlap = validate_archive_native_overlap(
        client,
        source_root=source_root,
        markets=markets,
        intervals=intervals,
        overlap_candles=overlap_candles,
        clock_ms=clock_ms,
    )
    preparation = _build_source_preparation(
        archive=archive,
        source_summary=source_summary,
        overlap=overlap,
        source_root=source_root,
        markets=markets,
        intervals=intervals,
    )
    write_archive_source_preparation(source_root, preparation)
    return preparation


def _load_preparation_payload(path: Path) -> dict[str, object]:
    try:
        return _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive source preparation",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_INVALID"
        ) from exc


def _preparation_from_payload(
    raw: Mapping[str, object],
    *,
    overlap: ArchiveNativeOverlapReport,
) -> ArchiveHistoricalSourcePreparation:
    markets_raw = _sequence(raw.get("markets"), "source preparation markets")
    intervals_raw = _sequence(
        raw.get("intervals"),
        "source preparation intervals",
    )
    try:
        preparation = ArchiveHistoricalSourcePreparation(
            archive=VerifiedArchiveCache(
                manifest_id=_string(
                    raw.get("archive_manifest_id"),
                    "source preparation archive_manifest_id",
                ),
                requested_start_ms=_integer(
                    raw.get("requested_start_ms"),
                    "source preparation requested_start_ms",
                ),
                requested_end_ms=_integer(
                    raw.get("requested_end_ms"),
                    "source preparation requested_end_ms",
                ),
                shard_count=_integer(
                    raw.get("archive_shard_count"),
                    "source preparation archive_shard_count",
                ),
                total_byte_count=_integer(
                    raw.get("archive_total_byte_count"),
                    "source preparation archive_total_byte_count",
                ),
            ),
            archive_ingest_manifest_id=_string(
                raw.get("archive_ingest_manifest_id"),
                "source preparation archive_ingest_manifest_id",
            ),
            coverage_report_id=_string(
                raw.get("coverage_report_id"),
                "source preparation coverage_report_id",
            ),
            overlap=overlap,
            markets=tuple(
                _string(item, "source preparation market")
                for item in markets_raw
            ),
            intervals=tuple(
                _string(item, "source preparation interval")
                for item in intervals_raw
            ),
            candle_manifest_count=_integer(
                raw.get("candle_manifest_count"),
                "source preparation candle_manifest_count",
            ),
            funding_manifest_count=_integer(
                raw.get("funding_manifest_count"),
                "source preparation funding_manifest_count",
            ),
            market_count=_integer(
                raw.get("market_count"),
                "source preparation market_count",
            ),
            parsed_trade_count=_integer(
                raw.get("parsed_trade_count"),
                "source preparation parsed_trade_count",
            ),
            archive_ingest_sha256=_string(
                raw.get("archive_ingest_sha256"),
                "source preparation archive_ingest_sha256",
            ),
            coverage_sha256=_string(
                raw.get("coverage_sha256"),
                "source preparation coverage_sha256",
            ),
            overlap_sha256=_string(
                raw.get("overlap_sha256"),
                "source preparation overlap_sha256",
            ),
            schema_version=_integer(
                raw.get("schema_version"),
                "source preparation schema_version",
            ),
        )
    except ValueError as exc:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_INVALID"
        ) from exc
    if _string(
        raw.get("preparation_id"),
        "source preparation preparation_id",
    ) != preparation.preparation_id:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_ID_MISMATCH"
        )
    return preparation


def _verify_archive_ingest_against_download(
    *,
    archive_root: Path,
    source_root: Path,
    preparation: ArchiveHistoricalSourcePreparation,
) -> None:
    try:
        archive_ingest = _mapping(
            json.loads(
                (source_root / "archive_ingest.json").read_text(encoding="utf-8")
            ),
            "archive ingest",
        )
        download = _mapping(
            json.loads(
                (archive_root / "download_manifest.json").read_text(
                    encoding="utf-8"
                )
            ),
            "archive download manifest",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_PREPARED_MANIFEST_INVALID"
        ) from exc

    if _string(archive_ingest.get("manifest_id"), "archive ingest manifest_id") != (
        preparation.archive_ingest_manifest_id
    ):
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_PREPARED_INGEST_ID_MISMATCH"
        )
    if _integer(
        archive_ingest.get("requested_start_ms"),
        "archive ingest requested_start_ms",
    ) != preparation.archive.requested_start_ms:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_PREPARED_INGEST_START_MISMATCH"
        )
    if _integer(
        archive_ingest.get("requested_end_ms"),
        "archive ingest requested_end_ms",
    ) != preparation.archive.requested_end_ms:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_PREPARED_INGEST_END_MISMATCH"
        )

    ingest_files = {
        (
            _string(item.get("relative_path"), "archive ingest relative_path"),
            _string(item.get("sha256"), "archive ingest sha256"),
            _integer(item.get("byte_count"), "archive ingest byte_count"),
        )
        for item in (
            _mapping(value, "archive ingest file")
            for value in _sequence(archive_ingest.get("files"), "archive ingest files")
        )
    }
    download_files = {
        (
            _string(item.get("relative_path"), "archive download relative_path"),
            _string(item.get("sha256"), "archive download sha256"),
            _integer(item.get("byte_count"), "archive download byte_count"),
        )
        for item in (
            _mapping(value, "archive download shard")
            for value in _sequence(download.get("shards"), "archive download shards")
        )
    }
    if ingest_files != download_files:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_PREPARED_INGEST_FILE_SET_MISMATCH"
        )


def verify_prepared_archive_historical_sources(
    *,
    archive_root: Path,
    source_root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
    start_ms: int,
    end_ms: int,
    overlap_candles: int,
) -> ArchiveHistoricalSourcePreparation:
    path = source_root / "source-preparation.json"
    raw = _load_preparation_payload(path)
    overlap_path = source_root / "archive_native_overlap.json"
    overlap = load_archive_native_overlap_report(overlap_path)
    preparation = _preparation_from_payload(raw, overlap=overlap)
    canonical_preparation = _canonical_json(preparation.to_dict()) + "\n"
    if path.read_text(encoding="utf-8") != canonical_preparation:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_NON_CANONICAL"
        )

    archive = verify_downloaded_archive_cache(
        archive_root,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    if archive != preparation.archive:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_ARCHIVE_MISMATCH"
        )
    expected_markets = tuple(sorted({market.canonical for market in markets}))
    expected_intervals = tuple(sorted(set(intervals)))
    if preparation.markets != expected_markets:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_MARKETS_MISMATCH"
        )
    if preparation.intervals != expected_intervals:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_INTERVALS_MISMATCH"
        )
    if preparation.overlap.overlap_candles != overlap_candles:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_OVERLAP_MISMATCH"
        )
    if _sha256_file(source_root / "archive_ingest.json") != (
        preparation.archive_ingest_sha256
    ):
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_INGEST_DIGEST_MISMATCH"
        )
    if _sha256_file(source_root / "coverage.json") != preparation.coverage_sha256:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_COVERAGE_DIGEST_MISMATCH"
        )
    if _sha256_file(overlap_path) != preparation.overlap_sha256:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_OVERLAP_DIGEST_MISMATCH"
        )

    _verify_archive_ingest_against_download(
        archive_root=archive_root,
        source_root=source_root,
        preparation=preparation,
    )

    candle_manifests = []
    funding_manifests = []
    archive_manifest_by_series: dict[tuple[str, str], str] = {}
    native_manifest_by_series: dict[tuple[str, str], str] = {}
    for market in sorted(set(markets), key=lambda item: item.canonical):
        market_root = source_root / _market_path_component(market)
        funding_manifest, _ = load_funding_source(market_root / "funding")
        if (
            funding_manifest.market != market.canonical
            or funding_manifest.requested_start_ms != start_ms
            or funding_manifest.requested_end_ms != end_ms
        ):
            raise HistoricalArchiveExperimentError(
                "ARCHIVE_PREPARED_FUNDING_RANGE_MISMATCH"
            )
        funding_manifests.append(funding_manifest)

        for interval in expected_intervals:
            candle_manifest, _ = load_candle_source(
                market_root / "candles" / interval
            )
            interval_end_ms = end_ms - (end_ms % INTERVAL_MS[interval])
            if (
                candle_manifest.market != market.canonical
                or candle_manifest.interval != interval
                or candle_manifest.requested_start_ms != start_ms
                or candle_manifest.requested_end_ms != interval_end_ms
            ):
                raise HistoricalArchiveExperimentError(
                    "ARCHIVE_PREPARED_CANDLE_RANGE_MISMATCH"
                )
            candle_manifests.append(candle_manifest)
            archive_manifest_by_series[
                (market.canonical, interval)
            ] = candle_manifest.manifest_id

            native_manifest, _ = load_candle_source(
                source_root
                / "archive_native_overlap"
                / _market_path_component(market)
                / "candles"
                / interval
            )
            native_manifest_by_series[
                (market.canonical, interval)
            ] = native_manifest.manifest_id

    coverage = build_coverage_report(
        candle_manifests=candle_manifests,
        funding_manifests=funding_manifests,
    )
    if coverage.get("report_id") != preparation.coverage_report_id:
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_COVERAGE_ID_MISMATCH"
        )

    for entry in preparation.overlap.entries:
        key = (entry.market, entry.interval)
        if archive_manifest_by_series.get(key) != entry.archive_manifest_id:
            raise HistoricalArchiveExperimentError(
                "ARCHIVE_SOURCE_PREPARATION_OVERLAP_ARCHIVE_SOURCE_MISMATCH"
            )
        if native_manifest_by_series.get(key) != entry.native_manifest_id:
            raise HistoricalArchiveExperimentError(
                "ARCHIVE_SOURCE_PREPARATION_OVERLAP_NATIVE_SOURCE_MISMATCH"
            )
    if len(preparation.overlap.entries) != len(expected_markets) * len(
        expected_intervals
    ):
        raise HistoricalArchiveExperimentError(
            "ARCHIVE_SOURCE_PREPARATION_OVERLAP_SERIES_MISMATCH"
        )
    return preparation


def run_prepared_archive_historical_experiment(
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
    horizons_ms: Sequence[int],
    start_ms: int,
    end_ms: int,
    config: HistoricalModelComparisonConfig,
    overlap_candles: int = 96,
) -> ArchiveHistoricalExperimentResult:
    preparation = verify_prepared_archive_historical_sources(
        archive_root=archive_root,
        source_root=source_root,
        markets=markets,
        intervals=intervals,
        start_ms=start_ms,
        end_ms=end_ms,
        overlap_candles=overlap_candles,
    )
    comparison = run_historical_model_comparison_from_sources(
        source_root=source_root,
        output_root=output_root,
        markets=markets,
        horizons_ms=horizons_ms,
        config=config,
    )
    return ArchiveHistoricalExperimentResult(
        archive=preparation.archive,
        source_summary=preparation.source_summary(source_root),
        overlap=preparation.overlap,
        comparison=comparison,
    )


def run_archive_historical_experiment(
    client: HistoricalArchiveExperimentClient,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    intervals: Sequence[str],
    horizons_ms: Sequence[int],
    start_ms: int,
    end_ms: int,
    clock_ms: Callable[[], int],
    config: HistoricalModelComparisonConfig,
    max_funding_items: int = 500,
    overlap_candles: int = 96,
) -> ArchiveHistoricalExperimentResult:
    preparation = prepare_archive_historical_sources(
        client,
        archive_root=archive_root,
        source_root=source_root,
        markets=markets,
        intervals=intervals,
        start_ms=start_ms,
        end_ms=end_ms,
        clock_ms=clock_ms,
        max_funding_items=max_funding_items,
        overlap_candles=overlap_candles,
    )
    comparison = run_historical_model_comparison_from_sources(
        source_root=source_root,
        output_root=output_root,
        markets=markets,
        horizons_ms=horizons_ms,
        config=config,
    )
    return ArchiveHistoricalExperimentResult(
        archive=preparation.archive,
        source_summary=preparation.source_summary(source_root),
        overlap=preparation.overlap,
        comparison=comparison,
    )
