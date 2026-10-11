"""Seal true original prospective SHORT rank-input features after paper exit.

Research-only and read-only with respect to the live paper state: verification
of every full ranking feature payload must precede a successful source ZIP.
Historical ranks from before full-input capture are NEVER backfilled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Final

from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshotStore,
    ShortRankFirstSeenError,
)
from cocomelon.research.prospective_short_rank_full_features import (
    OriginalRankFeatureInputBatchStore,
    OriginalRankInputBatchError,
)

SOURCE_DIR: Final = "prospective-short-rank-full-feature-inputs"
SOURCE_ERROR: Final = "prospective-short-rank-full-feature-inputs-error.json"
RANK_DIR: Final = "prospective-short-rank-first-seen"
RANK_ERROR: Final = "prospective-short-rank-first-seen-error.json"
BUNDLE_FILE: Final = "first-seen-short-rank-full-inputs.zip"
RECEIPT_FILE: Final = "first-seen-short-rank-full-inputs-seal.json"
MAX_BATCH_SIZE: Final = 5_000_000
MAX_BATCHES: Final = 30_000


class OriginalFullRankFeatureSealError(RuntimeError):
    pass


def _canonical(data: object) -> bytes:
    return (
        json.dumps(
            data, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ) + "\n"
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archive_hash(path: Path) -> str:
    hash_code = hashlib.sha256()
    with path.open("rb") as file:
        for data in iter(lambda: file.read(1024 * 1024), b""):
            hash_code.update(data)
    return hash_code.hexdigest()


def _zip_member(
    archive: zipfile.ZipFile, name: str, payload: bytes,
) -> None:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)


def seal_original_short_rank_full_feature_inputs(
    state_root: Path,
    output_dir: Path,
    *,
    worker_run_id: int,
    worker_run_attempt: int,
    worker_head_sha: str,
    sealed_at_ms: int | None = None,
) -> dict[str, object]:
    if (
        type(worker_run_id) is not int or worker_run_id <= 0
        or type(worker_run_attempt) is not int or worker_run_attempt <= 0
        or not isinstance(worker_head_sha, str)
        or len(worker_head_sha) != 40
        or any(x not in "0123456789abcdef" for x in worker_head_sha)
    ):
        raise OriginalFullRankFeatureSealError("source worker identity invalid")
    if sealed_at_ms is None:
        sealed_at_ms = time.time_ns() // 1_000_000
    if type(sealed_at_ms) is not int or sealed_at_ms < 0:
        raise OriginalFullRankFeatureSealError("source seal time invalid")
    if state_root.is_symlink() or not state_root.is_dir():
        raise OriginalFullRankFeatureSealError("original paper state root invalid")
    source = state_root.resolve()
    dest = output_dir.resolve()
    if source == dest or source in dest.parents or dest in source.parents:
        raise OriginalFullRankFeatureSealError(
            "source seal output overlaps original paper state"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / BUNDLE_FILE
    receipt_path = output_dir / RECEIPT_FILE
    pending = output_dir / ".original-rank-full-inputs.pending"
    if any(path.exists() or path.is_symlink() for path in (
        bundle_path, receipt_path, pending,
    )):
        raise OriginalFullRankFeatureSealError(
            "source output must be new and empty"
        )
    identity: dict[str, object] = {
        "worker_run_id_claimed": worker_run_id,
        "worker_run_attempt_claimed": worker_run_attempt,
        "worker_head_sha_claimed": worker_head_sha,
    }
    receipt: dict[str, object] = {
        "schema_version": 1,
        **identity,
        "sealed_at_ms": sealed_at_ms,
        "full_rank_feature_status": "rejected",
        "failure_reason": None,
        "zip_sha256": None,
        "zip_size_bytes": None,
        "rank_snapshot_count": 0,
        "verified_full_input_batch_count": 0,
        "historical_rank_snapshots_without_full_inputs": None,
        "rank_state_digest": None,
        "feature_input_source_digest": None,
        "entire_rank_history_full_feature_inputs_complete": False,
        "original_worker_api_artifact_authenticated": False,
        "full_mainnet_market_inputs_authenticated": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    try:
        rank_path = state_root / RANK_DIR
        input_path = state_root / SOURCE_DIR
        for marker in (state_root / SOURCE_ERROR, state_root / RANK_ERROR):
            if marker.exists() or marker.is_symlink():
                raise OriginalFullRankFeatureSealError(
                    "original rank or full-input producer reported failure"
                )
        for directory in (
            rank_path, rank_path / "snapshots",
            input_path, input_path / "batches",
        ):
            if not directory.is_dir() or directory.is_symlink():
                raise OriginalFullRankFeatureSealError(
                    "original rank or full-input source is missing or symlinked"
                )
        rank_files = sorted((rank_path / "snapshots").iterdir())
        if any(
            file.is_symlink()
            or not file.is_file()
            or len(file.name) != 21
            or file.name[16:] != ".json"
            or not file.name[:16].isascii()
            or not file.name[:16].isdigit()
            for file in rank_files
        ):
            raise OriginalFullRankFeatureSealError(
                "original rank file population unexpected"
            )
        ranks_store = FirstSeenRankSnapshotStore(rank_path)
        ranks = ranks_store.iter_records()
        inputs_store = OriginalRankFeatureInputBatchStore(input_path)
        batches = inputs_store.iter_verified()
        if (
            not ranks or not batches or len(batches) > MAX_BATCHES
            or len(batches) > len(ranks)
            or len(rank_files) != len(ranks)
        ):
            raise OriginalFullRankFeatureSealError(
                "full feature cohort missing or incomplete"
            )
        index = next(
            (
                i for i, row in enumerate(ranks)
                if row.observed_at_ms == batches[0].observed_at_ms
            ),
            None,
        )
        if index is None or len(ranks) - index != len(batches):
            raise OriginalFullRankFeatureSealError(
                "full original source has missing intermediary rank inputs"
            )
        if batches[-1].captured_at_ms > sealed_at_ms:
            raise OriginalFullRankFeatureSealError(
                "feature source claims later capture than seal time"
            )
        members: list[tuple[str, bytes]] = []
        descriptors: list[dict[str, object]] = []
        for batch, rank in zip(batches, ranks[index:], strict=True):
            batch.bind_to(rank)
            name = f"batches/{batch.observed_at_ms:016d}.json"
            path = input_path / name
            if path.is_symlink() or not path.is_file():
                raise OriginalFullRankFeatureSealError(
                    "original feature batch path is not regular source"
                )
            size = path.stat().st_size
            if size <= 0 or size > MAX_BATCH_SIZE:
                raise OriginalFullRankFeatureSealError(
                    "original feature batch size violates limit"
                )
            data = path.read_bytes()
            if data != _canonical(batch.to_dict()):
                raise OriginalFullRankFeatureSealError(
                    "original feature bytes are not canonical"
                )
            members.append((name, data))
            descriptors.append({
                "path": name,
                "byte_size": len(data),
                "sha256": _sha256(data),
                "observed_at_ms": batch.observed_at_ms,
                "captured_at_ms": batch.captured_at_ms,
                "rank_snapshot_digest": batch.rank_snapshot_digest,
                "batch_sha256": batch.batch_sha256,
                "feature_market_count": len(batch.features),
            })
        manifest: dict[str, object] = {
            "schema_version": 1,
            **identity,
            "sealed_at_ms": sealed_at_ms,
            "rank_snapshot_count": len(ranks),
            "verified_full_input_batch_count": len(batches),
            "historical_rank_snapshots_without_full_inputs": index,
            "first_complete_rank_input_observed_ms": batches[0].observed_at_ms,
            "last_complete_rank_input_observed_ms": batches[-1].observed_at_ms,
            "rank_state_digest": ranks_store.state_digest,
            "feature_input_source_digest": inputs_store.source_digest,
            "files": descriptors,
            "entire_rank_history_full_feature_inputs_complete": index == 0,
            "source_github_api_authenticated": False,
            "full_mainnet_market_inputs_authenticated": False,
            "ready_for_review": False,
            "execution_authority": False,
            "promotion_authority": False,
        }
        with zipfile.ZipFile(pending, "w", allowZip64=True) as bundle:
            _zip_member(bundle, "manifest.json", _canonical(manifest))
            for name, data in members:
                _zip_member(bundle, name, data)
        os.replace(pending, bundle_path)
        receipt.update({
            "full_rank_feature_status": "locally_sealed_prospective_suffix",
            "zip_sha256": _archive_hash(bundle_path),
            "zip_size_bytes": bundle_path.stat().st_size,
            "rank_snapshot_count": len(ranks),
            "verified_full_input_batch_count": len(batches),
            "historical_rank_snapshots_without_full_inputs": index,
            "rank_state_digest": ranks_store.state_digest,
            "feature_input_source_digest": inputs_store.source_digest,
            "entire_rank_history_full_feature_inputs_complete": index == 0,
        })
    except (
        OSError, ValueError, TypeError, ShortRankFirstSeenError,
        OriginalRankInputBatchError, OriginalFullRankFeatureSealError,
    ) as exc:
        receipt["failure_reason"] = (
            str(exc) if isinstance(exc, OriginalFullRankFeatureSealError)
            else "original_rank_or_input_source_unreadable_or_inconsistent"
        )
        if pending.exists():
            pending.unlink()
        if bundle_path.exists():
            bundle_path.unlink()
    receipt_path.write_bytes(_canonical(receipt))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker-run-id", type=int, required=True)
    parser.add_argument("--worker-run-attempt", type=int, required=True)
    parser.add_argument("--worker-head-sha", required=True)
    args = parser.parse_args(argv)
    receipt = seal_original_short_rank_full_feature_inputs(
        args.state_root, args.output_dir,
        worker_run_id=args.worker_run_id,
        worker_run_attempt=args.worker_run_attempt,
        worker_head_sha=args.worker_head_sha,
    )
    print(_canonical(receipt).decode("utf-8").strip())
    return 0 if receipt["full_rank_feature_status"] == (
        "locally_sealed_prospective_suffix"
    ) else 2


if __name__ == "__main__":
    sys.exit(main())
