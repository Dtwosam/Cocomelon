from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import quote

from cocomelon.domain.market import MarketId
from cocomelon.historical_archive_candles_cli import ingest_archive_candles
from cocomelon.research.historical_archive_acquisition import (
    ARCHIVE_BUCKET,
    ARCHIVE_PREFIX,
    plan_archive_shards,
)
from cocomelon.research.historical_backfill import (
    HistoricalFundingClient,
    backfill_funding,
)
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
    HistoricalModelComparisonReport,
    run_historical_model_comparison_from_sources,
)


class HistoricalArchiveExperimentError(RuntimeError):
    pass


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
class ArchiveHistoricalExperimentResult:
    archive: VerifiedArchiveCache
    source_summary: Mapping[str, object]
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
        if _integer(item.get("hour_start_ms"), f"shards[{index}].hour_start_ms") != (
            shard.hour_start_ms
        ):
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_HOUR_MISMATCH")

        byte_count = _integer(item.get("byte_count"), f"shards[{index}].byte_count")
        if byte_count < 0:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_SIZE_INVALID")
        sha256 = _string(item.get("sha256"), f"shards[{index}].sha256")
        if len(sha256) != 64:
            raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_SHA256_INVALID")

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

    plan_total = _integer(
        manifest.get("plan_total_byte_count"),
        "plan_total_byte_count",
    )
    if plan_total != total_byte_count:
        raise HistoricalArchiveExperimentError("ARCHIVE_DOWNLOAD_TOTAL_SIZE_MISMATCH")
    manifest_id = _string(manifest.get("manifest_id"), "manifest_id")

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


def run_archive_historical_experiment(
    funding_client: HistoricalFundingClient,
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
) -> ArchiveHistoricalExperimentResult:
    archive = verify_downloaded_archive_cache(
        archive_root,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    backfill_archive_experiment_funding(
        funding_client,
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
    comparison = run_historical_model_comparison_from_sources(
        source_root=source_root,
        output_root=output_root,
        markets=markets,
        horizons_ms=horizons_ms,
        config=config,
    )
    return ArchiveHistoricalExperimentResult(
        archive=archive,
        source_summary=source_summary,
        comparison=comparison,
    )
