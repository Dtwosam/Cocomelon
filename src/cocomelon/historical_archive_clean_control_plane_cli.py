from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.historical_archive_clean_control_plane import (
    CONTROL_PLANE_WORKFLOW_PATH,
    freeze_archive_clean_control_plane,
    verify_archive_clean_control_plane,
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
        prog="cocomelon-historical-archive-clean-control-plane",
        description="Freeze or verify the archive clean scheduled control plane",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--runtime-root", required=True, type=Path)
    freeze.add_argument("--pin-id", required=True)
    freeze.add_argument(
        "--workflow",
        type=Path,
        default=Path(CONTROL_PLANE_WORKFLOW_PATH),
    )

    verify = subparsers.add_parser("verify")
    verify.add_argument("--runtime-root", required=True, type=Path)
    verify.add_argument("--pin-id", required=True)
    verify.add_argument("--control-plane-id", required=True)
    verify.add_argument(
        "--workflow",
        type=Path,
        default=Path(CONTROL_PLANE_WORKFLOW_PATH),
    )

    return parser


def control_plane_payload(
    argv: Sequence[str],
    *,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> dict[str, object]:
    args = build_parser().parse_args(argv)
    if args.command == "freeze":
        attestation = freeze_archive_clean_control_plane(
            runtime_root=args.runtime_root,
            expected_pin_id=args.pin_id,
            workflow_path=args.workflow,
            frozen_at_ms=clock_ms(),
        )
    else:
        attestation = verify_archive_clean_control_plane(
            args.runtime_root / "control-plane.json",
            runtime_root=args.runtime_root,
            expected_pin_id=args.pin_id,
            workflow_path=args.workflow,
            expected_control_plane_id=args.control_plane_id,
        )

    return {
        "command": args.command,
        "paid_request_performed": False,
        "paper_only": attestation.paper_only,
        "prospective_only": attestation.prospective_only,
        "promotion_eligible": attestation.promotion_eligible,
        "execution_ready": attestation.execution_ready,
        "runtime_id": attestation.runtime_id,
        "pin_id": attestation.pin_id,
        "candidate_id": attestation.candidate_id,
        "validation_spec_id": attestation.validation_spec_id,
        "control_plane_id": attestation.control_plane_id,
        "workflow_sha256": attestation.workflow_sha256,
        "observer_source_tree_sha256": (
            attestation.observer_source_tree_sha256
        ),
        "frozen_at_ms": attestation.frozen_at_ms,
        "validation_start_ms": attestation.validation_start_ms,
        "validation_end_ms": attestation.validation_end_ms,
        "runtime_root": str(args.runtime_root),
        "workflow": str(args.workflow),
        "valid": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    resolved = tuple(sys.argv[1:] if argv is None else argv)
    try:
        payload = control_plane_payload(resolved)
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
