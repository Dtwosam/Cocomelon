from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.historical_archive_clean_checkpoint import (
    load_archive_clean_operational_checkpoint,
)
from cocomelon.research.historical_archive_clean_finalization import (
    build_archive_clean_finalization,
    write_archive_clean_finalization,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive-clean-finalize",
        description=(
            "Finalize one frozen PAPER-only archive clean-validation campaign "
            "from its pinned runtime and compact terminal checkpoint"
        ),
    )
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--pin-id", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def archive_clean_finalization_payload(
    *,
    runtime_root: Path,
    pin_id: str,
    checkpoint_path: Path,
    output_root: Path,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> dict[str, object]:
    pinned = load_pinned_archive_clean_runtime(
        runtime_root,
        expected_pin_id=pin_id,
    )
    checkpoint = load_archive_clean_operational_checkpoint(checkpoint_path)
    finalized_at_ms = clock_ms()
    finalization = build_archive_clean_finalization(
        pinned.runtime.spec,
        runtime_id=pinned.bundle.runtime_id,
        pin_id=pinned.pin.pin_id,
        checkpoint=checkpoint,
        finalized_at_ms=finalized_at_ms,
    )
    path = write_archive_clean_finalization(output_root, finalization)
    return {
        "command": "historical-archive-clean-finalize",
        "paper_only": finalization.paper_only,
        "prospective_only": finalization.prospective_only,
        "promotion_eligible": finalization.promotion_eligible,
        "execution_ready": finalization.execution_ready,
        "candidate_id": finalization.candidate_id,
        "model_artifact_id": finalization.model_artifact_id,
        "validation_spec_id": finalization.validation_spec_id,
        "campaign_id": finalization.campaign_id,
        "runtime_id": finalization.runtime_id,
        "pin_id": finalization.pin_id,
        "checkpoint_id": finalization.checkpoint_id,
        "finalization_id": finalization.finalization_id,
        "finalized_at_ms": finalization.finalized_at_ms,
        "verdict": finalization.verdict,
        "eligible_for_candidate_review": (
            finalization.eligible_for_candidate_review
        ),
        "reason_codes": finalization.reason_codes,
        "capture_coverage": str(finalization.capture_coverage),
        "captured_anchor_count": finalization.captured_anchor_count,
        "expected_anchor_count": finalization.expected_anchor_count,
        "settled_trade_count": finalization.settled_trade_count,
        "mean_net_return": (
            None
            if finalization.mean_net_return is None
            else str(finalization.mean_net_return)
        ),
        "block_results": tuple(item.to_dict() for item in finalization.block_results),
        "finalization": str(path),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = archive_clean_finalization_payload(
            runtime_root=args.runtime_root,
            pin_id=args.pin_id,
            checkpoint_path=args.checkpoint,
            output_root=args.output_root,
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
