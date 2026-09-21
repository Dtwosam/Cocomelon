from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cocomelon.research.historical_archive_acquisition import (
    ARCHIVE_BUCKET,
    ARCHIVE_PREFIX,
    REQUESTER_PAYS_ACK,
    ArchiveShard,
    ArchiveShardHead,
    HistoricalArchiveAcquisitionError,
    download_archive_inspection,
    inspect_archive_shards,
    plan_archive_shards,
)

HOUR = 3_600_000


class FakeStore:
    def __init__(
        self,
        *,
        sizes: dict[str, int],
        payloads: dict[str, bytes] | None = None,
    ) -> None:
        self.sizes = sizes
        self.payloads = payloads or {
            key: bytes([index % 251]) * size
            for index, (key, size) in enumerate(sizes.items(), start=1)
        }
        self.head_calls: list[str] = []
        self.download_calls: list[str] = []

    def head(self, shard: ArchiveShard) -> ArchiveShardHead | None:
        self.head_calls.append(shard.key)
        size = self.sizes.get(shard.key)
        if size is None:
            return None
        return ArchiveShardHead(
            shard=shard,
            byte_count=size,
            etag=f"etag-{size}",
        )

    def download(self, shard: ArchiveShard, target: Path) -> None:
        self.download_calls.append(shard.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.payloads[shard.key])


def _utc_ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            hour,
            tzinfo=UTC,
        ).timestamp()
        * 1000
    )


def test_archive_shard_plan_is_hourly_inclusive_and_uses_canonical_keys() -> None:
    start = _utc_ms(2026, 7, 1)
    shards = plan_archive_shards(
        start_ms=start + 12_345,
        end_ms=start + 2 * HOUR + 55_000,
    )

    assert len(shards) == 3
    assert [item.hour_start_ms for item in shards] == [
        start,
        start + HOUR,
        start + 2 * HOUR,
    ]
    assert [item.key for item in shards] == [
        f"{ARCHIVE_PREFIX}/20260701/0.lz4",
        f"{ARCHIVE_PREFIX}/20260701/1.lz4",
        f"{ARCHIVE_PREFIX}/20260701/2.lz4",
    ]
    assert all(item.bucket == ARCHIVE_BUCKET for item in shards)
    assert shards[0].relative_path == "hourly/20260701/0.lz4"


def test_archive_inspection_requires_ack_before_any_paid_head() -> None:
    start = _utc_ms(2026, 7, 1)
    shard = plan_archive_shards(start_ms=start, end_ms=start)[0]
    store = FakeStore(sizes={shard.key: 10})

    with pytest.raises(
        HistoricalArchiveAcquisitionError,
        match="REQUESTER_PAYS_ACK_REQUIRED",
    ):
        inspect_archive_shards(
            store,
            start_ms=start,
            end_ms=start,
            requester_pays_ack="",
        )

    assert store.head_calls == []


def test_archive_inspection_reports_missing_shards_without_downloading() -> None:
    start = _utc_ms(2026, 7, 1)
    shards = plan_archive_shards(start_ms=start, end_ms=start + HOUR)
    store = FakeStore(sizes={shards[0].key: 10})

    inspection = inspect_archive_shards(
        store,
        start_ms=start,
        end_ms=start + HOUR,
        requester_pays_ack=REQUESTER_PAYS_ACK,
    )

    assert inspection.complete is False
    assert inspection.total_byte_count == 10
    assert inspection.missing_keys == (shards[1].key,)
    assert store.download_calls == []


def test_download_blocks_missing_plan_and_byte_budget_before_body_fetch(
    tmp_path: Path,
) -> None:
    start = _utc_ms(2026, 7, 1)
    shards = plan_archive_shards(start_ms=start, end_ms=start + HOUR)
    store = FakeStore(
        sizes={
            shards[0].key: 10,
            shards[1].key: 20,
        }
    )
    inspection = inspect_archive_shards(
        store,
        start_ms=start,
        end_ms=start + HOUR,
        requester_pays_ack=REQUESTER_PAYS_ACK,
    )

    with pytest.raises(
        HistoricalArchiveAcquisitionError,
        match="ARCHIVE_DOWNLOAD_BYTE_BUDGET_EXCEEDED",
    ):
        download_archive_inspection(
            store,
            inspection,
            destination_root=tmp_path,
            requester_pays_ack=REQUESTER_PAYS_ACK,
            max_download_bytes=29,
        )

    assert store.download_calls == []


def test_download_writes_verified_cache_and_reuses_it_without_body_fetch(
    tmp_path: Path,
) -> None:
    start = _utc_ms(2026, 7, 1)
    shards = plan_archive_shards(start_ms=start, end_ms=start + HOUR)
    store = FakeStore(
        sizes={
            shards[0].key: 10,
            shards[1].key: 20,
        }
    )
    inspection = inspect_archive_shards(
        store,
        start_ms=start,
        end_ms=start + HOUR,
        requester_pays_ack=REQUESTER_PAYS_ACK,
    )

    first = download_archive_inspection(
        store,
        inspection,
        destination_root=tmp_path,
        requester_pays_ack=REQUESTER_PAYS_ACK,
        max_download_bytes=30,
    )
    first_manifest = json.loads(
        (tmp_path / "download_manifest.json").read_text(encoding="utf-8")
    )

    assert first.downloaded_count == 2
    assert first.cached_count == 0
    assert first.transferred_byte_count == 30
    assert len(store.download_calls) == 2

    store.download_calls.clear()
    second = download_archive_inspection(
        store,
        inspection,
        destination_root=tmp_path,
        requester_pays_ack=REQUESTER_PAYS_ACK,
        max_download_bytes=0,
    )
    second_manifest = json.loads(
        (tmp_path / "download_manifest.json").read_text(encoding="utf-8")
    )

    assert second.downloaded_count == 0
    assert second.cached_count == 2
    assert second.transferred_byte_count == 0
    assert store.download_calls == []
    assert first_manifest["manifest_id"] == second_manifest["manifest_id"]
    assert first_manifest["shards"] == second_manifest["shards"]
    assert first_manifest["downloaded_count"] == 2
    assert second_manifest["cache_reused_count"] == 2


def test_corrupted_archive_cache_fails_closed_instead_of_overwriting(
    tmp_path: Path,
) -> None:
    start = _utc_ms(2026, 7, 1)
    shard = plan_archive_shards(start_ms=start, end_ms=start)[0]
    store = FakeStore(sizes={shard.key: 10})
    inspection = inspect_archive_shards(
        store,
        start_ms=start,
        end_ms=start,
        requester_pays_ack=REQUESTER_PAYS_ACK,
    )
    download_archive_inspection(
        store,
        inspection,
        destination_root=tmp_path,
        requester_pays_ack=REQUESTER_PAYS_ACK,
        max_download_bytes=10,
    )
    target = tmp_path / shard.relative_path
    target.write_bytes(b"corrupted!")

    store.download_calls.clear()
    with pytest.raises(
        HistoricalArchiveAcquisitionError,
        match="ARCHIVE_CACHE_DIGEST_MISMATCH",
    ):
        download_archive_inspection(
            store,
            inspection,
            destination_root=tmp_path,
            requester_pays_ack=REQUESTER_PAYS_ACK,
            max_download_bytes=10,
        )

    assert store.download_calls == []
