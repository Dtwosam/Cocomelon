"""Read-only original-worker seal of prospective coarse rank market contexts.

A producer-local ZIP is NEVER independently authenticated. A successful
source seal requires matching original rank, full feature, and context suffixes
and replays every recorded rankability decision before publishing a single ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
from cocomelon.research.prospective_short_rank_market_context import (
    OriginalRankEligibilityContextError,
    OriginalRankEligibilityContextStore,
    replay_recorded_rank_eligibility,
)

BUNDLE_FILE: Final = "first-seen-short-rank-market-context.zip"
RECEIPT_FILE: Final = "first-seen-short-rank-market-context-seal.json"
MAX_CONTEXT_BATCHES: Final = 30_000
MAX_CONTEXT_BATCH_BYTES: Final = 5_000_000


class OriginalRankMarketContextSealError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return (json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ) + "\n").encode("utf-8")


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _archive_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _add_zip_file(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)


def seal_original_rank_market_context(
    state_root: Path,
    output_dir: Path,
    *,
    worker_run_id: int,
    worker_run_attempt: int,
    worker_head_sha: str,
    sealed_at_ms: int | None = None,
) -> dict[str, object]:
    """Preserve a verifiable new context suffix or an explicit negative receipt."""
    if (
        type(worker_run_id) is not int or worker_run_id <= 0
        or type(worker_run_attempt) is not int or worker_run_attempt <= 0
        or not isinstance(worker_head_sha, str)
        or len(worker_head_sha) != 40
        or any(x not in "0123456789abcdef" for x in worker_head_sha)
    ):
        raise OriginalRankMarketContextSealError("original worker identity invalid")
    if sealed_at_ms is None:
        sealed_at_ms = time.time_ns() // 1_000_000
    if type(sealed_at_ms) is not int or sealed_at_ms < 0:
        raise OriginalRankMarketContextSealError("seal time invalid")
    if state_root.is_symlink() or not state_root.is_dir():
        raise OriginalRankMarketContextSealError("original state root invalid")
    source_root, dest = state_root.resolve(), output_dir.resolve()
    if (
        source_root == dest or source_root in dest.parents
        or dest in source_root.parents
    ):
        raise OriginalRankMarketContextSealError(
            "rank context export overlaps original paper state"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = output_dir / BUNDLE_FILE
    receipt_file = output_dir / RECEIPT_FILE
    pending = output_dir / ".rank-market-context.pending"
    if any(p.exists() or p.is_symlink() for p in (bundle, receipt_file, pending)):
        raise OriginalRankMarketContextSealError(
            "rank context output must be new and empty"
        )

    identity = {
        "worker_run_id_claimed": worker_run_id,
        "worker_run_attempt_claimed": worker_run_attempt,
        "worker_head_sha_claimed": worker_head_sha,
    }
    receipt: dict[str, object] = {
        "schema_version": 1,
        **identity,
        "sealed_at_ms": sealed_at_ms,
        "original_rank_market_context_status": "rejected",
        "failure_reason": None,
        "zip_sha256": None,
        "zip_size_bytes": None,
        "verified_market_context_batches": 0,
        "rank_snapshots_without_context": None,
        "original_rank_state_digest": None,
        "original_feature_source_digest": None,
        "original_context_source_digest": None,
        "local_original_eligibility_membership_replayed": False,
        "independent_original_github_source_authenticated": False,
        "independent_mainnet_market_stream_authenticated": False,
        "risk_matched_after_cost_profitability_proven": False,
        "research_only": True,
        "ready_for_review": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    try:
        for bad in (
            "prospective-short-rank-first-seen-error.json",
            "prospective-short-rank-full-feature-inputs-error.json",
            "prospective-short-rank-market-context-error.json",
        ):
            marker = state_root / bad
            if marker.exists() or marker.is_symlink():
                raise OriginalRankMarketContextSealError(
                    "original rank, full-input or market context producer reported failure"
                )

        rank_dir = state_root / "prospective-short-rank-first-seen"
        input_dir = state_root / "prospective-short-rank-full-feature-inputs"
        context_dir = state_root / "prospective-short-rank-market-context"
        for dirname in (
            rank_dir, rank_dir / "snapshots",
            input_dir, input_dir / "batches",
            context_dir, context_dir / "batches",
        ):
            if dirname.is_symlink() or not dirname.is_dir():
                raise OriginalRankMarketContextSealError(
                    "original rank, full-input or context population missing"
                )
        rank_store = FirstSeenRankSnapshotStore(rank_dir)
        input_store = OriginalRankFeatureInputBatchStore(input_dir)
        context_store = OriginalRankEligibilityContextStore(context_dir)
        ranks = rank_store.iter_records()
        features = input_store.iter_verified()
        contexts = context_store.iter_verified()
        if not contexts or len(contexts) > MAX_CONTEXT_BATCHES:
            raise OriginalRankMarketContextSealError(
                "no prospective source context cohort available"
            )
        if not ranks or not features:
            raise OriginalRankMarketContextSealError(
                "original rank or full-feature archive unavailable"
            )
        start_rank = next((
            i for i, item in enumerate(ranks)
            if item.observed_at_ms == contexts[0].observed_at_ms
        ), None)
        start_full = next((
            i for i, item in enumerate(features)
            if item.observed_at_ms == contexts[0].observed_at_ms
        ), None)
        if (
            start_rank is None or start_full is None
            or len(ranks) - start_rank != len(contexts)
            or len(features) - start_full != len(contexts)
            or contexts[-1].captured_at_ms > sealed_at_ms
        ):
            raise OriginalRankMarketContextSealError(
                "complete prospective market context suffix does not match rank and features"
            )
        descriptors: list[dict[str, object]] = []
        source_paths: list[tuple[str, Path]] = []
        total_markets = 0
        for context, rank, feature in zip(
            contexts, ranks[start_rank:], features[start_full:], strict=True,
        ):
            replay_recorded_rank_eligibility(
                rank=rank, feature_inputs=feature, context=context,
            )
            total_markets += len(context.snapshots)
            name = f"batches/{context.observed_at_ms:016d}.json"
            path = context_dir / name
            if path.is_symlink() or not path.is_file():
                raise OriginalRankMarketContextSealError(
                    "original rank context batch path invalid"
                )
            size = path.stat().st_size
            if size <= 0 or size > MAX_CONTEXT_BATCH_BYTES:
                raise OriginalRankMarketContextSealError(
                    "original rank context batch too large or empty"
                )
            raw = path.read_bytes()
            if raw != _canonical(context.to_dict()):
                raise OriginalRankMarketContextSealError(
                    "original rank context source bytes noncanonical"
                )
            descriptors.append({
                "path": name,
                "byte_size": len(raw),
                "sha256": _hash(raw),
                "observed_at_ms": context.observed_at_ms,
                "rank_snapshot_digest": context.rank_snapshot_digest,
                "batch_sha256": context.batch_sha256,
                "market_count": len(context.snapshots),
            })
            source_paths.append((name, path))
        rank_digest = rank_store.state_digest
        feature_digest = input_store.source_digest
        context_digest = context_store.source_digest
        manifest = {
            "schema_version": 1,
            **identity,
            "sealed_at_ms": sealed_at_ms,
            "original_rank_state_digest": rank_digest,
            "original_feature_source_digest": feature_digest,
            "original_context_source_digest": context_digest,
            "rank_snapshot_count": len(ranks),
            "verified_market_context_batches": len(contexts),
            "rank_snapshots_without_context": start_rank,
            "first_context_observed_at_ms": contexts[0].observed_at_ms,
            "last_context_observed_at_ms": contexts[-1].observed_at_ms,
            "source_context_markets_replayed": total_markets,
            "files": descriptors,
            "independent_mainnet_market_stream_authenticated": False,
            "ready_for_review": False,
            "execution_authority": False,
            "promotion_authority": False,
        }
        with zipfile.ZipFile(pending, "w", allowZip64=True) as archive:
            _add_zip_file(archive, "manifest.json", _canonical(manifest))
            for (name, path), descriptor in zip(
                source_paths, descriptors, strict=True,
            ):
                raw = path.read_bytes()
                if (
                    len(raw) != descriptor["byte_size"]
                    or _hash(raw) != descriptor["sha256"]
                ):
                    raise OriginalRankMarketContextSealError(
                        "original rank market context changed during sealing"
                    )
                _add_zip_file(archive, name, raw)
        os.replace(pending, bundle)
        receipt.update({
            "original_rank_market_context_status": "locally_sealed_prospective_suffix",
            "zip_sha256": _archive_hash(bundle),
            "zip_size_bytes": bundle.stat().st_size,
            "verified_market_context_batches": len(contexts),
            "rank_snapshots_without_context": start_rank,
            "original_rank_state_digest": rank_digest,
            "original_feature_source_digest": feature_digest,
            "original_context_source_digest": context_digest,
            "local_original_eligibility_membership_replayed": True,
        })
    except (
        OSError, ValueError, TypeError, ShortRankFirstSeenError,
        OriginalRankInputBatchError, OriginalRankEligibilityContextError,
        OriginalRankMarketContextSealError,
    ) as exc:
        receipt["failure_reason"] = (
            str(exc) if isinstance(exc, OriginalRankMarketContextSealError)
            else "original_rank_market_context_unreadable_or_inconsistent"
        )
        if pending.exists():
            pending.unlink()
        if bundle.exists():
            bundle.unlink()
    receipt_file.write_bytes(_canonical(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker-run-id", type=int, required=True)
    parser.add_argument("--worker-run-attempt", type=int, required=True)
    parser.add_argument("--worker-head-sha", required=True)
    args = parser.parse_args()
    receipt = seal_original_rank_market_context(
        args.state_root, args.output_dir,
        worker_run_id=args.worker_run_id,
        worker_run_attempt=args.worker_run_attempt,
        worker_head_sha=args.worker_head_sha,
    )
    print(_canonical(receipt).decode("utf-8").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
