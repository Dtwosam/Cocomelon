from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.historical_archive_clean_runtime import (
    load_pinned_archive_clean_runtime,
    publish_archive_clean_runtime,
    publish_archive_clean_runtime_from_package,
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
        prog="cocomelon-historical-archive-clean-runtime",
        description=(
            "Publish or verify an immutable PAPER-only archive clean runtime"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--output-root", required=True, type=Path)
    publish.add_argument("--runtime-root", required=True, type=Path)

    publish_package = subparsers.add_parser("publish-package")
    publish_package.add_argument("--package-root", required=True, type=Path)
    publish_package.add_argument("--runtime-root", required=True, type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--runtime-root", required=True, type=Path)
    verify.add_argument("--pin-id", required=True)

    return parser


def runtime_payload(
    argv: Sequence[str],
    *,
    clock_ms: Callable[[], int] = utc_now_ms,
) -> dict[str, object]:
    args = build_parser().parse_args(argv)
    if args.command in {"publish", "publish-package"}:
        if args.command == "publish":
            bundle, pin = publish_archive_clean_runtime(
                output_root=args.output_root,
                publish_root=args.runtime_root,
                pinned_at_ms=clock_ms(),
            )
        else:
            bundle, pin = publish_archive_clean_runtime_from_package(
                package_root=args.package_root,
                publish_root=args.runtime_root,
                pinned_at_ms=clock_ms(),
            )
        return {
            "command": args.command,
            "paid_request_performed": False,
            "paper_only": True,
            "prospective_only": True,
            "promotion_eligible": False,
            "execution_ready": False,
            "candidate_id": bundle.candidate_id,
            "model_artifact_id": bundle.model_artifact_id,
            "validation_spec_id": bundle.validation_spec_id,
            "runtime_id": bundle.runtime_id,
            "pin_id": pin.pin_id,
            "portable_package_bound": getattr(
                bundle,
                "portable_package_bound",
                False,
            ),
            "candidate_package_id": getattr(
                bundle,
                "candidate_package_id",
                None,
            ),
            "candidate_package_sha256": getattr(
                bundle,
                "candidate_package_sha256",
                None,
            ),
            "pinned_at_ms": pin.pinned_at_ms,
            "validation_start_ms": bundle.validation_start_ms,
            "validation_end_ms": bundle.validation_end_ms,
            "observer_source_attestation_id": (
                bundle.observer_source_attestation_id
            ),
            "observer_source_tree_sha256": (
                bundle.observer_source_tree_sha256
            ),
            "runtime_root": str(args.runtime_root),
        }

    pinned = load_pinned_archive_clean_runtime(
        args.runtime_root,
        expected_pin_id=args.pin_id,
    )
    bundle = pinned.bundle
    return {
        "command": "verify",
        "paid_request_performed": False,
        "valid": True,
        "paper_only": bundle.paper_only,
        "prospective_only": bundle.prospective_only,
        "promotion_eligible": bundle.promotion_eligible,
        "execution_ready": bundle.execution_ready,
        "candidate_id": bundle.candidate_id,
        "model_artifact_id": bundle.model_artifact_id,
        "validation_spec_id": bundle.validation_spec_id,
        "runtime_id": bundle.runtime_id,
        "pin_id": pinned.pin.pin_id,
        "portable_package_bound": getattr(
            bundle,
            "portable_package_bound",
            False,
        ),
        "candidate_package_id": getattr(
            bundle,
            "candidate_package_id",
            None,
        ),
        "candidate_package_sha256": getattr(
            bundle,
            "candidate_package_sha256",
            None,
        ),
        "pinned_at_ms": pinned.pin.pinned_at_ms,
        "observer_source_tree_sha256": bundle.observer_source_tree_sha256,
        "runtime_root": str(args.runtime_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    resolved = tuple(sys.argv[1:] if argv is None else argv)
    try:
        payload = runtime_payload(resolved)
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
