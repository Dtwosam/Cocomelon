from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

ARCHIVE_BUCKET = "hl-mainnet-node-data"
ARCHIVE_PREFIX = "node_fills_by_block/hourly"
REQUESTER_PAYS_ACK = "I_UNDERSTAND_HYPERLIQUID_ARCHIVE_IS_REQUESTER_PAYS"
HOUR_MS = 3_600_000


class HistoricalArchiveAcquisitionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveShard:
    bucket: str
    key: str
    hour_start_ms: int
    relative_path: str

    def __post_init__(self) -> None:
        if self.bucket != ARCHIVE_BUCKET:
            raise ValueError("archive bucket must use the canonical Hyperliquid node bucket")
        if not self.key.startswith(f"{ARCHIVE_PREFIX}/"):
            raise ValueError("archive key must use the canonical fill prefix")
        if self.hour_start_ms < 0 or self.hour_start_ms % HOUR_MS != 0:
            raise ValueError("hour_start_ms must be a non-negative UTC hour boundary")
        if not self.relative_path.strip():
            raise ValueError("relative_path must not be empty")


@dataclass(frozen=True, slots=True)
class ArchiveShardHead:
    shard: ArchiveShard
    byte_count: int
    etag: str

    def __post_init__(self) -> None:
        if self.byte_count < 0:
            raise ValueError("byte_count must be non-negative")
        if not self.etag.strip():
            raise ValueError("etag must not be empty")


@dataclass(frozen=True, slots=True)
class ArchiveInspection:
    requested_start_ms: int
    requested_end_ms: int
    heads: tuple[ArchiveShardHead, ...]
    missing_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.requested_start_ms < 0:
            raise ValueError("requested_start_ms must be non-negative")
        if self.requested_end_ms < self.requested_start_ms:
            raise ValueError("requested_end_ms must be >= requested_start_ms")
        if tuple(sorted(set(self.missing_keys))) != self.missing_keys:
            raise ValueError("missing_keys must be sorted and unique")

    @property
    def total_byte_count(self) -> int:
        return sum(item.byte_count for item in self.heads)

    @property
    def complete(self) -> bool:
        return not self.missing_keys


@dataclass(frozen=True, slots=True)
class ArchiveDownloadedShard:
    shard: ArchiveShard
    byte_count: int
    etag: str
    sha256: str
    relative_path: str
    reused_cache: bool

    def __post_init__(self) -> None:
        if self.byte_count < 0:
            raise ValueError("byte_count must be non-negative")
        if len(self.sha256) != 64:
            raise ValueError("sha256 must be a SHA-256 hex digest")
        if not self.relative_path.strip():
            raise ValueError("relative_path must not be empty")


@dataclass(frozen=True, slots=True)
class ArchiveDownloadResult:
    requested_start_ms: int
    requested_end_ms: int
    plan_total_byte_count: int
    transferred_byte_count: int
    shards: tuple[ArchiveDownloadedShard, ...]
    manifest_path: str

    def __post_init__(self) -> None:
        if self.plan_total_byte_count < 0 or self.transferred_byte_count < 0:
            raise ValueError("byte counts must be non-negative")
        if self.transferred_byte_count > self.plan_total_byte_count:
            raise ValueError("transferred bytes cannot exceed plan bytes")

    @property
    def downloaded_count(self) -> int:
        return sum(1 for item in self.shards if not item.reused_cache)

    @property
    def cached_count(self) -> int:
        return sum(1 for item in self.shards if item.reused_cache)


class RequesterPaysArchiveStore(Protocol):
    def head(self, shard: ArchiveShard) -> ArchiveShardHead | None: ...

    def download(self, shard: ArchiveShard, target: Path) -> None: ...


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def plan_archive_shards(
    *,
    start_ms: int,
    end_ms: int,
) -> tuple[ArchiveShard, ...]:
    if start_ms < 0:
        raise ValueError("start_ms must be non-negative")
    if end_ms < start_ms:
        raise ValueError("end_ms must be >= start_ms")

    first_hour = start_ms - (start_ms % HOUR_MS)
    last_hour = end_ms - (end_ms % HOUR_MS)
    shards: list[ArchiveShard] = []
    cursor = first_hour
    while cursor <= last_hour:
        instant = datetime.fromtimestamp(cursor / 1000, tz=timezone.utc)
        day = instant.strftime("%Y%m%d")
        hour = instant.hour
        key = f"{ARCHIVE_PREFIX}/{day}/{hour}.lz4"
        relative_path = str(Path("hourly") / day / f"{hour}.lz4")
        shards.append(
            ArchiveShard(
                bucket=ARCHIVE_BUCKET,
                key=key,
                hour_start_ms=cursor,
                relative_path=relative_path,
            )
        )
        cursor += HOUR_MS
    return tuple(shards)


def require_requester_pays_ack(value: str) -> None:
    if value != REQUESTER_PAYS_ACK:
        raise HistoricalArchiveAcquisitionError("REQUESTER_PAYS_ACK_REQUIRED")


def inspect_archive_shards(
    store: RequesterPaysArchiveStore,
    *,
    start_ms: int,
    end_ms: int,
    requester_pays_ack: str,
) -> ArchiveInspection:
    require_requester_pays_ack(requester_pays_ack)
    shards = plan_archive_shards(start_ms=start_ms, end_ms=end_ms)
    heads: list[ArchiveShardHead] = []
    missing: list[str] = []
    for shard in shards:
        head = store.head(shard)
        if head is None:
            missing.append(shard.key)
            continue
        if head.shard != shard:
            raise HistoricalArchiveAcquisitionError("ARCHIVE_HEAD_IDENTITY_MISMATCH")
        heads.append(head)

    return ArchiveInspection(
        requested_start_ms=start_ms,
        requested_end_ms=end_ms,
        heads=tuple(heads),
        missing_keys=tuple(sorted(missing)),
    )


def _cache_metadata_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.source.json")


def _load_verified_cache(
    root: Path,
    head: ArchiveShardHead,
) -> ArchiveDownloadedShard | None:
    target = root / head.shard.relative_path
    metadata_path = _cache_metadata_path(target)
    if not target.exists() and not metadata_path.exists():
        return None
    if not target.is_file() or not metadata_path.is_file():
        raise HistoricalArchiveAcquisitionError("ARCHIVE_CACHE_INCOMPLETE")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveAcquisitionError("ARCHIVE_CACHE_METADATA_INVALID") from exc
    expected = {
        "bucket": head.shard.bucket,
        "key": head.shard.key,
        "byte_count": head.byte_count,
        "etag": head.etag,
    }
    actual = {
        "bucket": metadata.get("bucket"),
        "key": metadata.get("key"),
        "byte_count": metadata.get("byte_count"),
        "etag": metadata.get("etag"),
    }
    if actual != expected:
        raise HistoricalArchiveAcquisitionError("ARCHIVE_CACHE_SOURCE_MISMATCH")

    sha256 = metadata.get("sha256")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise HistoricalArchiveAcquisitionError("ARCHIVE_CACHE_SHA256_INVALID")
    if target.stat().st_size != head.byte_count:
        raise HistoricalArchiveAcquisitionError("ARCHIVE_CACHE_SIZE_MISMATCH")
    if _sha256_file(target) != sha256:
        raise HistoricalArchiveAcquisitionError("ARCHIVE_CACHE_DIGEST_MISMATCH")

    return ArchiveDownloadedShard(
        shard=head.shard,
        byte_count=head.byte_count,
        etag=head.etag,
        sha256=sha256,
        relative_path=head.shard.relative_path,
        reused_cache=True,
    )


def _write_cache_metadata(
    target: Path,
    *,
    head: ArchiveShardHead,
    sha256: str,
) -> None:
    payload = {
        "bucket": head.shard.bucket,
        "key": head.shard.key,
        "byte_count": head.byte_count,
        "etag": head.etag,
        "sha256": sha256,
        "schema_version": 1,
    }
    _atomic_write(
        _cache_metadata_path(target),
        (_canonical_json(payload) + "\n").encode("utf-8"),
    )


def _download_one(
    store: RequesterPaysArchiveStore,
    *,
    root: Path,
    head: ArchiveShardHead,
) -> ArchiveDownloadedShard:
    target = root / head.shard.relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.download")
    if temporary.exists():
        temporary.unlink()
    try:
        store.download(head.shard, temporary)
        if not temporary.is_file():
            raise HistoricalArchiveAcquisitionError("ARCHIVE_DOWNLOAD_MISSING_FILE")
        if temporary.stat().st_size != head.byte_count:
            raise HistoricalArchiveAcquisitionError("ARCHIVE_DOWNLOAD_SIZE_MISMATCH")
        sha256 = _sha256_file(temporary)
        os.replace(temporary, target)
        _write_cache_metadata(target, head=head, sha256=sha256)
    finally:
        if temporary.exists():
            temporary.unlink()

    return ArchiveDownloadedShard(
        shard=head.shard,
        byte_count=head.byte_count,
        etag=head.etag,
        sha256=sha256,
        relative_path=head.shard.relative_path,
        reused_cache=False,
    )


def download_archive_inspection(
    store: RequesterPaysArchiveStore,
    inspection: ArchiveInspection,
    *,
    destination_root: Path,
    requester_pays_ack: str,
    max_download_bytes: int,
) -> ArchiveDownloadResult:
    require_requester_pays_ack(requester_pays_ack)
    if max_download_bytes < 0:
        raise ValueError("max_download_bytes must be non-negative")
    if not inspection.complete:
        raise HistoricalArchiveAcquisitionError("ARCHIVE_PLAN_HAS_MISSING_SHARDS")

    cached: dict[str, ArchiveDownloadedShard] = {}
    required_bytes = 0
    for head in inspection.heads:
        cached_item = _load_verified_cache(destination_root, head)
        if cached_item is None:
            required_bytes += head.byte_count
        else:
            cached[head.shard.key] = cached_item

    if required_bytes > max_download_bytes:
        raise HistoricalArchiveAcquisitionError("ARCHIVE_DOWNLOAD_BYTE_BUDGET_EXCEEDED")

    resolved: list[ArchiveDownloadedShard] = []
    transferred = 0
    for head in inspection.heads:
        cached_item = cached.get(head.shard.key)
        if cached_item is not None:
            resolved.append(cached_item)
            continue
        downloaded = _download_one(
            store,
            root=destination_root,
            head=head,
        )
        resolved.append(downloaded)
        transferred += downloaded.byte_count

    manifest_payload = {
        "kind": "hyperliquid-node-fills-by-block-download",
        "bucket": ARCHIVE_BUCKET,
        "prefix": ARCHIVE_PREFIX,
        "requested_start_ms": inspection.requested_start_ms,
        "requested_end_ms": inspection.requested_end_ms,
        "plan_total_byte_count": inspection.total_byte_count,
        "transferred_byte_count": transferred,
        "shards": tuple(
            {
                "key": item.shard.key,
                "hour_start_ms": item.shard.hour_start_ms,
                "relative_path": item.relative_path,
                "byte_count": item.byte_count,
                "etag": item.etag,
                "sha256": item.sha256,
                "reused_cache": item.reused_cache,
            }
            for item in resolved
        ),
        "schema_version": 1,
    }
    manifest_payload["manifest_id"] = hashlib.sha256(
        _canonical_json(manifest_payload).encode("utf-8")
    ).hexdigest()[:24]
    manifest_path = destination_root / "download_manifest.json"
    _atomic_write(
        manifest_path,
        (_canonical_json(manifest_payload) + "\n").encode("utf-8"),
    )

    return ArchiveDownloadResult(
        requested_start_ms=inspection.requested_start_ms,
        requested_end_ms=inspection.requested_end_ms,
        plan_total_byte_count=inspection.total_byte_count,
        transferred_byte_count=transferred,
        shards=tuple(resolved),
        manifest_path=str(manifest_path),
    )
