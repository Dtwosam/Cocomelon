from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from cocomelon.research.historical_archive_acquisition import (
    REQUESTER_PAYS_ACK,
    ArchiveShard,
    ArchiveShardHead,
    HistoricalArchiveAcquisitionError,
    RequesterPaysArchiveStore,
    download_archive_inspection,
    inspect_archive_shards,
    plan_archive_shards,
    require_requester_pays_ack,
)


def _emit(payload: dict[str, object], *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=target,
    )


def _boto3() -> Any:
    try:
        return importlib.import_module("boto3")
    except ModuleNotFoundError as exc:
        raise HistoricalArchiveAcquisitionError(
            "boto3 is required for requester-pays archive access; "
            "install the research extra"
        ) from exc


def _error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    error = response.get("Error")
    if not isinstance(error, dict):
        return None
    code = error.get("Code")
    return code if isinstance(code, str) else None


class Boto3RequesterPaysArchiveStore(RequesterPaysArchiveStore):
    def __init__(self, client: Any) -> None:
        self._client = client

    def head(self, shard: ArchiveShard) -> ArchiveShardHead | None:
        try:
            response = self._client.head_object(
                Bucket=shard.bucket,
                Key=shard.key,
                RequestPayer="requester",
            )
        except Exception as exc:
            code = _error_code(exc)
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            suffix = "unknown" if code is None else code
            raise HistoricalArchiveAcquisitionError(
                f"ARCHIVE_HEAD_FAILED:{shard.key}:{suffix}"
            ) from exc

        byte_count = response.get("ContentLength")
        etag = response.get("ETag")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int):
            raise HistoricalArchiveAcquisitionError(
                f"ARCHIVE_HEAD_SIZE_INVALID:{shard.key}"
            )
        if not isinstance(etag, str) or not etag.strip():
            raise HistoricalArchiveAcquisitionError(
                f"ARCHIVE_HEAD_ETAG_INVALID:{shard.key}"
            )
        return ArchiveShardHead(
            shard=shard,
            byte_count=byte_count,
            etag=etag.strip().strip('"'),
        )

    def download(self, shard: ArchiveShard, target: Path) -> None:
        try:
            self._client.download_file(
                shard.bucket,
                shard.key,
                str(target),
                ExtraArgs={"RequestPayer": "requester"},
            )
        except Exception as exc:
            code = _error_code(exc)
            suffix = "unknown" if code is None else code
            raise HistoricalArchiveAcquisitionError(
                f"ARCHIVE_DOWNLOAD_FAILED:{shard.key}:{suffix}"
            ) from exc


def _build_store(profile: str | None) -> Boto3RequesterPaysArchiveStore:
    boto3 = _boto3()
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return Boto3RequesterPaysArchiveStore(session.client("s3"))


def _add_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start-ms", required=True, type=int)
    parser.add_argument("--end-ms", required=True, type=int)


def _add_paid_access(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ack-requester-pays",
        required=True,
        help=f"must equal {REQUESTER_PAYS_ACK}",
    )
    parser.add_argument(
        "--aws-profile",
        help="optional AWS profile name; credentials use standard AWS resolution",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive",
        description="Plan and safely acquire requester-pays Hyperliquid fill archives",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    keys = subparsers.add_parser(
        "keys",
        help="plan exact archive keys without contacting AWS",
    )
    _add_range(keys)

    inspect = subparsers.add_parser(
        "inspect",
        help="HEAD requester-pays objects and total their compressed bytes",
    )
    _add_range(inspect)
    _add_paid_access(inspect)

    download = subparsers.add_parser(
        "download",
        help="download a complete inspected archive plan under a hard byte ceiling",
    )
    _add_range(download)
    _add_paid_access(download)
    download.add_argument("--destination-root", required=True, type=Path)
    download.add_argument("--max-download-bytes", required=True, type=int)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "keys":
            shards = plan_archive_shards(
                start_ms=args.start_ms,
                end_ms=args.end_ms,
            )
            _emit(
                {
                    "command": "keys",
                    "paid_request_performed": False,
                    "requested_start_ms": args.start_ms,
                    "requested_end_ms": args.end_ms,
                    "shard_count": len(shards),
                    "keys": tuple(shard.key for shard in shards),
                }
            )
            return 0

        require_requester_pays_ack(args.ack_requester_pays)
        store = _build_store(args.aws_profile)
        inspection = inspect_archive_shards(
            store,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            requester_pays_ack=args.ack_requester_pays,
        )

        if args.command == "inspect":
            _emit(
                {
                    "command": "inspect",
                    "requester_pays": True,
                    "requested_start_ms": inspection.requested_start_ms,
                    "requested_end_ms": inspection.requested_end_ms,
                    "expected_shard_count": len(inspection.heads)
                    + len(inspection.missing_keys),
                    "available_shard_count": len(inspection.heads),
                    "missing_shard_count": len(inspection.missing_keys),
                    "missing_keys": inspection.missing_keys,
                    "total_compressed_bytes_found": inspection.total_byte_count,
                    "complete": inspection.complete,
                }
            )
            return 0 if inspection.complete else 3

        result = download_archive_inspection(
            store,
            inspection,
            destination_root=args.destination_root,
            requester_pays_ack=args.ack_requester_pays,
            max_download_bytes=args.max_download_bytes,
        )
        _emit(
            {
                "command": "download",
                "requester_pays": True,
                "requested_start_ms": result.requested_start_ms,
                "requested_end_ms": result.requested_end_ms,
                "plan_total_byte_count": result.plan_total_byte_count,
                "transferred_byte_count": result.transferred_byte_count,
                "downloaded_count": result.downloaded_count,
                "cached_count": result.cached_count,
                "manifest_path": result.manifest_path,
            }
        )
        return 0
    except (OSError, ValueError, HistoricalArchiveAcquisitionError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
