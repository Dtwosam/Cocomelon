from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.historical_archive_candidate_package import (
    build_archive_clean_candidate_package,
    load_archive_clean_candidate_package,
    materialize_archive_clean_candidate_package,
    verify_archive_clean_candidate_package,
)
from cocomelon.research.historical_archive_presets import (
    PRESET_NAME,
    get_archive_experiment_preset,
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
        prog="cocomelon-historical-archive-candidate-package",
        description=(
            "Build or verify the portable PAPER-only archive candidate handoff"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("build", "verify-source"):
        command = subparsers.add_parser(name)
        command.add_argument("--preset", default=PRESET_NAME)
        command.add_argument("--archive-root", required=True, type=Path)
        command.add_argument("--source-root", required=True, type=Path)
        command.add_argument("--output-root", required=True, type=Path)
        command.add_argument("--package-root", required=True, type=Path)

    portable = subparsers.add_parser("verify-portable")
    portable.add_argument("--package-root", required=True, type=Path)
    return parser


def _payload(package_root: Path, loaded: object) -> dict[str, object]:
    package = loaded.package  # type: ignore[attr-defined]
    return {
        "package_id": package.package_id,
        "candidate_id": package.candidate_id,
        "model_artifact_id": package.model_artifact_id,
        "validation_spec_id": package.validation_spec_id,
        "model_payload_sha256": package.model_payload_sha256,
        "candidate_model_sha256": package.candidate_model_sha256,
        "validation_spec_sha256": package.validation_spec_sha256,
        "model_family": package.model_family,
        "calibration_variant": package.calibration_variant,
        "validation_start_ms": package.validation_start_ms,
        "validation_end_ms": package.validation_end_ms,
        "finalization_not_before_ms": package.finalization_not_before_ms,
        "local_lineage_reverified": package.local_lineage_reverified,
        "paper_only": package.paper_only,
        "prospective_only": package.prospective_only,
        "promotion_eligible": package.promotion_eligible,
        "execution_ready": package.execution_ready,
        "package_root": str(package_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-portable":
            loaded = load_archive_clean_candidate_package(args.package_root)
            _emit(
                {
                    "command": "verify-portable",
                    "valid": True,
                    "paid_request_performed": False,
                    **_payload(args.package_root, loaded),
                }
            )
            return 0

        preset = get_archive_experiment_preset(args.preset)
        if args.command == "build":
            package = build_archive_clean_candidate_package(
                preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            materialize_archive_clean_candidate_package(
                output_root=args.output_root,
                package_root=args.package_root,
                package=package,
            )
            loaded = load_archive_clean_candidate_package(args.package_root)
        else:
            loaded = verify_archive_clean_candidate_package(
                preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
                package_root=args.package_root,
            )
        _emit(
            {
                "command": args.command,
                "valid": True,
                "paid_request_performed": False,
                **_payload(args.package_root, loaded),
            }
        )
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
