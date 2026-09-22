from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.config import ExecutionMode, Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.research.historical_archive_clean_checkpoint import (
    ArchiveCleanCheckpointEvidenceStore,
)
from cocomelon.research.historical_archive_clean_cycle import (
    build_archive_clean_operational_cycle_receipt,
    write_archive_clean_operational_cycle_receipt,
)
from cocomelon.research.historical_archive_clean_observer import (
    ArchiveCleanPublicReader,
    ArchiveCleanSourceCaptureStore,
    run_archive_clean_observer_cycle,
)
from cocomelon.research.historical_archive_clean_runtime import (
    load_pinned_archive_clean_runtime,
)
from cocomelon.util.time import utc_now_ms


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


def _require_empty_root(path: Path, field: str) -> None:
    if not path.exists():
        return
    if not path.is_dir():
        raise ValueError(f"{field} must be a directory")
    if any(path.iterdir()):
        raise ValueError(f"{field} must be missing or empty")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive-clean-cycle",
        description=(
            "Run one pinned PAPER-only archive clean cycle with compact "
            "operational checkpoint state"
        ),
    )
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--pin-id", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--cycle-evidence-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    return parser


def archive_clean_cycle_payload(
    settings: Settings,
    *,
    runtime_root: Path,
    pin_id: str,
    checkpoint_path: Path,
    cycle_evidence_root: Path,
    source_root: Path,
    reader: ArchiveCleanPublicReader | None = None,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> dict[str, object]:
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise ValueError("archive clean cycle requires paper execution mode")

    pinned = load_pinned_archive_clean_runtime(
        runtime_root,
        expected_pin_id=pin_id,
    )
    spec = pinned.runtime.spec
    artifact = pinned.runtime.artifact

    _require_empty_root(cycle_evidence_root, "cycle_evidence_root")
    _require_empty_root(source_root, "source_root")
    evidence_store = ArchiveCleanCheckpointEvidenceStore(
        checkpoint_path,
        cycle_evidence_root=cycle_evidence_root,
        spec=spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
    )
    restored_checkpoint_id = evidence_store.checkpoint.checkpoint_id
    source_store = ArchiveCleanSourceCaptureStore(source_root)

    source = reader or InfoClient(settings)
    result = run_archive_clean_observer_cycle(
        source,
        artifact=artifact,
        spec=spec,
        evidence_store=evidence_store,
        source_store=source_store,
        clock_ms=clock_ms,
    )
    completed_at_ms = clock_ms()
    checkpoint = evidence_store.save(as_of_ms=completed_at_ms)
    receipt = build_archive_clean_operational_cycle_receipt(
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        campaign_id=evidence_store.campaign_id,
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        restored_checkpoint_id=restored_checkpoint_id,
        checkpoint=checkpoint,
        result=result,
        completed_at_ms=completed_at_ms,
        cycle_evidence_root=cycle_evidence_root,
        source_root=source_root,
    )
    receipt_path = write_archive_clean_operational_cycle_receipt(
        cycle_evidence_root,
        receipt,
    )
    return {
        "command": "historical-archive-clean-cycle",
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "paper_only": True,
        "prospective_only": True,
        "promotion_eligible": False,
        "execution_ready": False,
        "runtime_id": pinned.bundle.runtime_id,
        "pin_id": pinned.pin.pin_id,
        "campaign_id": evidence_store.campaign_id,
        "validation_spec_id": spec.spec_id,
        "candidate_id": spec.candidate_id,
        "restored_checkpoint_id": restored_checkpoint_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "receipt_id": receipt.receipt_id,
        "status": result.status,
        "cycle_started_ms": result.cycle_started_ms,
        "completed_at_ms": completed_at_ms,
        "anchor_end_ms": result.anchor_end_ms,
        "observation_id": result.observation_id,
        "settled_outcome_ids": result.settled_outcome_ids,
        "missing_settlement_signal_ids": (
            result.missing_settlement_signal_ids
        ),
        "capture_coverage": result.capture_coverage,
        "expected_elapsed_anchor_count": result.expected_elapsed_anchor_count,
        "captured_elapsed_anchor_count": result.captured_elapsed_anchor_count,
        "cumulative_settled_outcome_count": (
            checkpoint.settled_outcome_count
        ),
        "pending_signal_count": receipt.pending_signal_count,
        "cycle_evidence_file_count": receipt.cycle_evidence_file_count,
        "source_file_count": receipt.source_file_count,
        "checkpoint": str(checkpoint_path),
        "cycle_receipt": str(receipt_path),
        "cycle_evidence_root": str(cycle_evidence_root),
        "source_root": str(source_root),
        "runtime_root": str(runtime_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = archive_clean_cycle_payload(
            Settings.from_env(),
            runtime_root=args.runtime_root,
            pin_id=args.pin_id,
            checkpoint_path=args.checkpoint,
            cycle_evidence_root=args.cycle_evidence_root,
            source_root=args.source_root,
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
