from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import cocomelon.historical_archive_acquisition_cli as cli
from cocomelon.research.historical_archive_acquisition import (
    ARCHIVE_PREFIX,
    REQUESTER_PAYS_ACK,
    ArchiveShard,
    ArchiveShardHead,
)

HOUR = 3_600_000


class FakeStore:
    def __init__(self, sizes: dict[str, int]) -> None:
        self.sizes = sizes
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
        target.write_bytes(b"x" * self.sizes[shard.key])


class FakeBotoClient:
    def __init__(self) -> None:
        self.head_kwargs: dict[str, object] | None = None
        self.download_args: tuple[object, ...] | None = None
        self.download_kwargs: dict[str, object] | None = None

    def head_object(self, **kwargs: object) -> dict[str, object]:
        self.head_kwargs = kwargs
        return {"ContentLength": 12, "ETag": '"etag-value"'}

    def download_file(
        self,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.download_args = args
        self.download_kwargs = kwargs


def _utc_ms(year: int, month: int, day: int, hour: int = 0) -> int:
    return int(
        datetime(
            year,
            month,
            day,
            hour,
            tzinfo=timezone.utc,
        ).timestamp()
        * 1000
    )


def _json_stdout(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_keys_command_is_offline_and_does_not_build_aws_store(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    start = _utc_ms(2026, 7, 1)

    def forbidden(_profile: str | None) -> Any:
        raise AssertionError("AWS store must not be constructed for keys")

    monkeypatch.setattr(cli, "_build_store", forbidden)

    status = cli.main(
        [
            "keys",
            "--start-ms",
            str(start),
            "--end-ms",
            str(start + HOUR),
        ]
    )

    assert status == 0
    payload = _json_stdout(capsys)
    assert payload["paid_request_performed"] is False
    assert payload["shard_count"] == 2
    assert payload["keys"] == [
        f"{ARCHIVE_PREFIX}/20260701/0.lz4",
        f"{ARCHIVE_PREFIX}/20260701/1.lz4",
    ]


def test_paid_command_rejects_bad_ack_before_aws_store_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    start = _utc_ms(2026, 7, 1)

    def forbidden(_profile: str | None) -> Any:
        raise AssertionError("AWS store must not be constructed before ack")

    monkeypatch.setattr(cli, "_build_store", forbidden)

    status = cli.main(
        [
            "inspect",
            "--start-ms",
            str(start),
            "--end-ms",
            str(start),
            "--ack-requester-pays",
            "NO",
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error"] == "REQUESTER_PAYS_ACK_REQUIRED"


def test_inspect_command_surfaces_missing_shards_without_download(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    start = _utc_ms(2026, 7, 1)
    key0 = f"{ARCHIVE_PREFIX}/20260701/0.lz4"
    store = FakeStore({key0: 12})
    monkeypatch.setattr(cli, "_build_store", lambda _profile: store)

    status = cli.main(
        [
            "inspect",
            "--start-ms",
            str(start),
            "--end-ms",
            str(start + HOUR),
            "--ack-requester-pays",
            REQUESTER_PAYS_ACK,
        ]
    )

    assert status == 3
    payload = _json_stdout(capsys)
    assert payload["available_shard_count"] == 1
    assert payload["missing_shard_count"] == 1
    assert payload["total_compressed_bytes_found"] == 12
    assert store.download_calls == []


def test_download_command_enforces_byte_budget_before_body_fetch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    start = _utc_ms(2026, 7, 1)
    key = f"{ARCHIVE_PREFIX}/20260701/0.lz4"
    store = FakeStore({key: 12})
    monkeypatch.setattr(cli, "_build_store", lambda _profile: store)

    status = cli.main(
        [
            "download",
            "--start-ms",
            str(start),
            "--end-ms",
            str(start),
            "--ack-requester-pays",
            REQUESTER_PAYS_ACK,
            "--destination-root",
            str(tmp_path),
            "--max-download-bytes",
            "11",
        ]
    )

    assert status == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert payload["error"] == "ARCHIVE_DOWNLOAD_BYTE_BUDGET_EXCEEDED"
    assert store.download_calls == []


def test_boto_adapter_always_sets_requester_pays() -> None:
    client = FakeBotoClient()
    store = cli.Boto3RequesterPaysArchiveStore(client)
    start = _utc_ms(2026, 7, 1)
    shard = ArchiveShard(
        bucket="hl-mainnet-node-data",
        key=f"{ARCHIVE_PREFIX}/20260701/0.lz4",
        hour_start_ms=start,
        relative_path="hourly/20260701/0.lz4",
    )

    head = store.head(shard)
    store.download(shard, Path("/tmp/not-written-by-fake"))

    assert head is not None
    assert head.byte_count == 12
    assert head.etag == "etag-value"
    assert client.head_kwargs == {
        "Bucket": "hl-mainnet-node-data",
        "Key": shard.key,
        "RequestPayer": "requester",
    }
    assert client.download_args == (
        "hl-mainnet-node-data",
        shard.key,
        "/tmp/not-written-by-fake",
    )
    assert client.download_kwargs == {
        "ExtraArgs": {"RequestPayer": "requester"}
    }
