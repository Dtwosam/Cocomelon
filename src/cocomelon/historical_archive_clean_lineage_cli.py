from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.historical_archive_clean_checkpoint import (
    load_archive_clean_operational_checkpoint,
)
from cocomelon.research.historical_archive_clean_lineage import (
    HistoricalArchiveCleanLineageError,
    verify_archive_clean_cycle_lineage_paths,
)
from cocomelon.research.historical_archive_clean_runtime import (
    load_pinned_archive_clean_runtime,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive-clean-lineage",
        description=(
            "Verify the append-only PAPER-only archive clean cycle receipt "
            "chain against the pinned runtime and current checkpoint"
        ),
    )
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--pin-id", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--receipts-root", required=True, type=Path)
    return parser


def archive_clean_lineage_payload(
    *,
    runtime_root: Path,
    pin_id: str,
    checkpoint_path: Path,
    receipts_root: Path,
) -> dict[str, object]:
    pinned = load_pinned_archive_clean_runtime(
        runtime_root,
        expected_pin_id=pin_id,
    )
    checkpoint = load_archive_clean_operational_checkpoint(checkpoint_path)
    if not receipts_root.is_dir():
        raise HistoricalArchiveCleanLineageError(
            "ARCHIVE_CLEAN_LINEAGE_RECEIPTS_ROOT_NOT_DIRECTORY"
        )
    receipt_paths = tuple(sorted(receipts_root.rglob("cycle.json")))
    report = verify_archive_clean_cycle_lineage_paths(
        pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        receipt_paths=receipt_paths,
    )
    if report.latest_checkpoint_id != checkpoint.checkpoint_id:
        raise HistoricalArchiveCleanLineageError(
            "ARCHIVE_CLEAN_LINEAGE_TIP_CHECKPOINT_MISMATCH"
        )
    return {
        "command": "historical-archive-clean-lineage",
        "status": report.status,
        "paper_only": report.paper_only,
        "prospective_only": report.prospective_only,
        "promotion_eligible": report.promotion_eligible,
        "execution_ready": report.execution_ready,
        "runtime_id": report.runtime_id,
        "pin_id": report.pin_id,
        "campaign_id": report.campaign_id,
        "validation_spec_id": report.validation_spec_id,
        "candidate_id": report.candidate_id,
        "initial_checkpoint_id": report.initial_checkpoint_id,
        "latest_checkpoint_id": report.latest_checkpoint_id,
        "receipt_count": report.receipt_count,
        "receipt_sequence_sha256": report.receipt_sequence_sha256,
        "cumulative_settled_outcome_count": (
            report.cumulative_settled_outcome_count
        ),
        "latest_expected_elapsed_anchor_count": (
            report.latest_expected_elapsed_anchor_count
        ),
        "latest_captured_elapsed_anchor_count": (
            report.latest_captured_elapsed_anchor_count
        ),
        "lineage_id": report.lineage_id,
        "checkpoint": str(checkpoint_path),
        "receipts_root": str(receipts_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = archive_clean_lineage_payload(
            runtime_root=args.runtime_root,
            pin_id=args.pin_id,
            checkpoint_path=args.checkpoint,
            receipts_root=args.receipts_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
