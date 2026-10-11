"""Seal completed-worker SHORT rank receipts without changing paper state.

This exporter is intentionally run only after the original trader has exited.
The worker's independently reported GitHub artifact digest + run metadata,
not the JSON's self-declared fields, must authenticate its provenance later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path
from typing import Final

from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshotStore,
    ShortRankFirstSeenError,
)

ARCHIVE_NAME: Final = "first-seen-short-rank-source.zip"
RECEIPT_NAME: Final = "first-seen-short-rank-seal.json"
SOURCE_DIR: Final = "prospective-short-rank-first-seen"
ERROR_FILE: Final = "prospective-short-rank-first-seen-error.json"


class ShortRankSealError(RuntimeError):
    pass


def _canonical(payload: object) -> bytes:
    return (
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ) + "\n"
    ).encode("utf-8")


def _zip_member(name: str, payload: bytes, target: zipfile.ZipFile) -> None:
    # No ZIP timestamp or host-permission randomness can change the identity.
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    target.writestr(info, payload)


def _identity(
    *, run_id: int, attempt: int, head_sha: str,
) -> dict[str, object]:
    if (
        type(run_id) is not int or run_id <= 0
        or type(attempt) is not int or attempt <= 0
        or len(head_sha) != 40
        or any(char not in "0123456789abcdef" for char in head_sha)
    ):
        raise ShortRankSealError("worker identity is invalid")
    return {
        "worker_run_id_claimed": run_id,
        "worker_run_attempt_claimed": attempt,
        "worker_head_sha_claimed": head_sha,
    }


def seal_completed_short_rank_archive(
    state_root: Path,
    output_dir: Path,
    *,
    worker_run_id: int,
    worker_run_attempt: int,
    worker_head_sha: str,
    sealed_at_ms: int | None = None,
) -> dict[str, object]:
    """Make either a verified local archive or an explicit rejected receipt.

    Original source files are never modified. A rejected result never leaves
    a plausible success ZIP. Caller-supplied identity is NOT a signature.
    """
    identity = _identity(
        run_id=worker_run_id,
        attempt=worker_run_attempt,
        head_sha=worker_head_sha,
    )
    if sealed_at_ms is None:
        sealed_at_ms = time.time_ns() // 1_000_000
    if type(sealed_at_ms) is not int or sealed_at_ms < 0:
        raise ShortRankSealError("seal timestamp invalid")
    if state_root.is_symlink() or not state_root.is_dir():
        raise ShortRankSealError("original state root missing or symlinked")
    if (
        output_dir.resolve() == state_root.resolve()
        or state_root.resolve() in output_dir.resolve().parents
        or output_dir.resolve() in state_root.resolve().parents
    ):
        raise ShortRankSealError("rank export output overlaps original worker state")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / ARCHIVE_NAME
    receipt_path = output_dir / RECEIPT_NAME
    if archive_path.exists() or receipt_path.exists():
        raise ShortRankSealError("rank seal output must be new and empty")

    receipt: dict[str, object] = {
        "schema_version": 1,
        **identity,
        "sealed_at_ms": sealed_at_ms,
        "rank_source_status": "rejected",
        "rejection_reason": None,
        "archive_file_sha256": None,
        "archive_size_bytes": None,
        "archive_snapshot_count": 0,
        "rank_state_digest": None,
        "locally_verified_original_rank_files": False,
        "github_artifact_provenance_independently_authenticated": False,
        "original_market_archive_bound": False,
        "continuous_rank_coverage_certified": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    temp = archive_path.with_suffix(".pending")
    try:
        if temp.exists():
            raise ShortRankSealError("stale pending archive")
        source_root = state_root / SOURCE_DIR
        snapshots_root = source_root / "snapshots"
        failure_path = state_root / ERROR_FILE
        if failure_path.exists() or failure_path.is_symlink():
            raise ShortRankSealError("producer reported rank capture failure")
        if (
            source_root.is_symlink() or not source_root.is_dir()
            or snapshots_root.is_symlink() or not snapshots_root.is_dir()
        ):
            raise ShortRankSealError("rank snapshot source missing or symlinked")
        entries = sorted(snapshots_root.iterdir())
        if not entries or any(
            p.is_symlink()
            or not p.is_file()
            or len(p.name) != 21
            or p.name[16:] != ".json"
            or not p.name[:16].isascii()
            or not p.name[:16].isdigit()
            for p in entries
        ):
            raise ShortRankSealError(
                "rank source empty, incomplete, or noncanonical"
            )
        snapshots = FirstSeenRankSnapshotStore(source_root).iter_records()
        if len(snapshots) != len(entries):
            raise ShortRankSealError("rank snapshot population incomplete")
        if snapshots[-1].captured_at_ms > sealed_at_ms:
            raise ShortRankSealError("source claims future capture time")
        files: list[dict[str, object]] = []
        for snapshot, path in zip(snapshots, entries, strict=True):
            raw = path.read_bytes()
            files.append({
                "path": f"snapshots/{path.name}",
                "byte_size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "snapshot_digest": snapshot.snapshot_digest,
                "observed_at_ms": snapshot.observed_at_ms,
                "captured_at_ms": snapshot.captured_at_ms,
            })
        state_digest = FirstSeenRankSnapshotStore(source_root).state_digest
        manifest: dict[str, object] = {
            "schema_version": 1,
            **identity,
            "sealed_at_ms": sealed_at_ms,
            "rank_state_digest": state_digest,
            "rank_snapshot_count": len(snapshots),
            "first_observed_at_ms": snapshots[0].observed_at_ms,
            "last_observed_at_ms": snapshots[-1].observed_at_ms,
            "first_captured_at_ms": snapshots[0].captured_at_ms,
            "last_captured_at_ms": snapshots[-1].captured_at_ms,
            "files": files,
            "source_is_original_paper_worker_state": "claimed_by_worker_run",
            "github_artifact_provenance_independently_authenticated": False,
            "market_microstructure_source_bound": False,
            "continuous_rank_coverage_certified": False,
            "execution_authority": False,
            "promotion_authority": False,
        }
        with zipfile.ZipFile(temp, "w", allowZip64=True) as bundle:
            _zip_member("manifest.json", _canonical(manifest), bundle)
            for path in entries:
                _zip_member(
                    f"snapshots/{path.name}", path.read_bytes(), bundle,
                )
        archive_bytes = temp.read_bytes()
        archive_path.write_bytes(archive_bytes)
        temp.unlink()
        receipt.update({
            "rank_source_status": "locally_sealed",
            "archive_file_sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "archive_size_bytes": len(archive_bytes),
            "archive_snapshot_count": len(snapshots),
            "rank_state_digest": state_digest,
            "locally_verified_original_rank_files": True,
        })
    except (OSError, ValueError, ShortRankFirstSeenError, ShortRankSealError) as exc:
        # Do not silently backfill a missing captured cohort. Record only
        # a stable failure category, not potentially sensitive file contents.
        receipt["rejection_reason"] = (
            str(exc) if isinstance(exc, ShortRankSealError)
            else "unreadable_or_inconsistent_rank_snapshot"
        )
        if temp.exists():
            temp.unlink()
        if archive_path.exists():
            archive_path.unlink()
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
    receipt = seal_completed_short_rank_archive(
        args.state_root, args.output_dir,
        worker_run_id=args.worker_run_id,
        worker_run_attempt=args.worker_run_attempt,
        worker_head_sha=args.worker_head_sha,
    )
    print(_canonical(receipt).decode("utf-8").strip())
    return 0 if receipt["rank_source_status"] == "locally_sealed" else 2


if __name__ == "__main__":
    sys.exit(main())
