from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.config import ExecutionMode, Settings
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.research.historical_archive_acquisition import plan_archive_shards
from cocomelon.research.historical_archive_candidate_freeze import (
    build_archive_candidate_freeze,
    verify_archive_candidate_freeze,
    write_archive_candidate_freeze,
)
from cocomelon.research.historical_archive_final_calibration import (
    build_archive_final_calibration,
    verify_archive_final_calibration,
    write_archive_final_calibration,
)
from cocomelon.research.historical_archive_presets import (
    PRESET_NAME,
    build_archive_preset_preflight,
    get_archive_experiment_preset,
    prepare_archive_experiment_preset,
    run_archive_experiment_preset,
    run_prepared_archive_experiment_preset,
    verify_archive_preset_bundle_receipt,
    verify_archive_preset_run_receipt,
    verify_archive_preset_source_attestation,
)
from cocomelon.research.historical_archive_review import (
    build_archive_development_review,
    write_archive_development_review,
)
from cocomelon.research.historical_archive_training_plan import (
    build_archive_candidate_training_plan,
    verify_archive_candidate_training_plan,
    write_archive_candidate_training_plan,
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


def _clock(received_at_ms: int | None) -> Callable[[], int]:
    if received_at_ms is None:
        return lambda: time.time_ns() // 1_000_000
    if received_at_ms < 0:
        raise ValueError("received_at_ms must be non-negative")
    return lambda: received_at_ms


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-archive-preset",
        description="Inspect or run a frozen touched archive research preset",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show")
    show.add_argument("--preset", default=PRESET_NAME)

    keys = subparsers.add_parser("keys")
    keys.add_argument("--preset", default=PRESET_NAME)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--preset", default=PRESET_NAME)
    verify.add_argument("--receipt", required=True, type=Path)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--preset", default=PRESET_NAME)
    preflight.add_argument("--archive-root", required=True, type=Path)
    preflight.add_argument("--source-root", required=True, type=Path)
    preflight.add_argument("--output-root", required=True, type=Path)

    freeze_candidate = subparsers.add_parser("freeze-candidate")
    freeze_candidate.add_argument("--preset", default=PRESET_NAME)
    freeze_candidate.add_argument("--archive-root", required=True, type=Path)
    freeze_candidate.add_argument("--source-root", required=True, type=Path)
    freeze_candidate.add_argument("--output-root", required=True, type=Path)
    freeze_candidate.add_argument("--frozen-at-ms", required=True, type=int)

    verify_candidate = subparsers.add_parser("verify-candidate-freeze")
    verify_candidate.add_argument("--preset", default=PRESET_NAME)
    verify_candidate.add_argument("--archive-root", required=True, type=Path)
    verify_candidate.add_argument("--source-root", required=True, type=Path)
    verify_candidate.add_argument("--output-root", required=True, type=Path)

    calibrate_candidate = subparsers.add_parser("calibrate-candidate")
    calibrate_candidate.add_argument("--preset", default=PRESET_NAME)
    calibrate_candidate.add_argument("--archive-root", required=True, type=Path)
    calibrate_candidate.add_argument("--source-root", required=True, type=Path)
    calibrate_candidate.add_argument("--output-root", required=True, type=Path)

    verify_calibration = subparsers.add_parser("verify-final-calibration")
    verify_calibration.add_argument("--preset", default=PRESET_NAME)
    verify_calibration.add_argument("--archive-root", required=True, type=Path)
    verify_calibration.add_argument("--source-root", required=True, type=Path)
    verify_calibration.add_argument("--output-root", required=True, type=Path)

    plan_training = subparsers.add_parser("plan-candidate-training")
    plan_training.add_argument("--preset", default=PRESET_NAME)
    plan_training.add_argument("--archive-root", required=True, type=Path)
    plan_training.add_argument("--source-root", required=True, type=Path)
    plan_training.add_argument("--output-root", required=True, type=Path)

    verify_training = subparsers.add_parser("verify-candidate-training-plan")
    verify_training.add_argument("--preset", default=PRESET_NAME)
    verify_training.add_argument("--archive-root", required=True, type=Path)
    verify_training.add_argument("--source-root", required=True, type=Path)
    verify_training.add_argument("--output-root", required=True, type=Path)

    review = subparsers.add_parser("review")
    review.add_argument("--preset", default=PRESET_NAME)
    review.add_argument("--archive-root", required=True, type=Path)
    review.add_argument("--source-root", required=True, type=Path)
    review.add_argument("--output-root", required=True, type=Path)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--preset", default=PRESET_NAME)
    prepare.add_argument("--archive-root", required=True, type=Path)
    prepare.add_argument("--source-root", required=True, type=Path)
    prepare.add_argument("--received-at-ms", required=True, type=int)

    run_prepared = subparsers.add_parser("run-prepared")
    run_prepared.add_argument("--preset", default=PRESET_NAME)
    run_prepared.add_argument("--archive-root", required=True, type=Path)
    run_prepared.add_argument("--source-root", required=True, type=Path)
    run_prepared.add_argument("--output-root", required=True, type=Path)

    verify_bundle = subparsers.add_parser("verify-bundle")
    verify_bundle.add_argument("--preset", default=PRESET_NAME)
    verify_bundle.add_argument("--archive-root", required=True, type=Path)
    verify_bundle.add_argument("--source-root", required=True, type=Path)
    verify_bundle.add_argument("--output-root", required=True, type=Path)

    run = subparsers.add_parser("run")
    run.add_argument("--preset", default=PRESET_NAME)
    run.add_argument("--archive-root", required=True, type=Path)
    run.add_argument("--source-root", required=True, type=Path)
    run.add_argument("--output-root", required=True, type=Path)
    run.add_argument("--received-at-ms", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        preset = get_archive_experiment_preset(args.preset)
        if args.command == "show":
            _emit(
                {
                    "command": "show",
                    "paid_request_performed": False,
                    **preset.to_dict(),
                }
            )
            return 0
        if args.command == "keys":
            shards = plan_archive_shards(
                start_ms=preset.start_ms,
                end_ms=preset.end_ms,
            )
            _emit(
                {
                    "command": "keys",
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "paid_request_performed": False,
                    "shard_count": len(shards),
                    "keys": tuple(item.key for item in shards),
                }
            )
            return 0
        if args.command == "verify":
            receipt = verify_archive_preset_run_receipt(
                args.receipt,
                preset=preset,
            )
            _emit(
                {
                    "command": "verify",
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "paid_request_performed": False,
                    "receipt_id": receipt.receipt_id,
                    "valid": True,
                }
            )
            return 0
        if args.command == "preflight":
            preflight = build_archive_preset_preflight(
                preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            _emit(
                {
                    "command": "preflight",
                    "ready": True,
                    **preflight.to_dict(),
                }
            )
            return 0
        if args.command == "freeze-candidate":
            freeze = build_archive_candidate_freeze(
                preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
                frozen_at_ms=args.frozen_at_ms,
            )
            freeze_path = write_archive_candidate_freeze(
                args.output_root,
                freeze,
            )
            _emit(
                {
                    "command": "freeze-candidate",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "candidate_id": freeze.candidate_id,
                    "candidate_kind": freeze.candidate_kind,
                    "model_family": freeze.model_family,
                    "calibration_variant": freeze.calibration_variant,
                    "selection_policy": freeze.selection_policy,
                    "prospective_only": freeze.prospective_only,
                    "promotion_eligible": freeze.promotion_eligible,
                    "execution_ready": freeze.execution_ready,
                    "frozen_at_ms": freeze.frozen_at_ms,
                    "validation_not_before_ms": (
                        freeze.validation_not_before_ms
                    ),
                    "candidate_freeze": str(freeze_path),
                }
            )
            return 0
        if args.command == "verify-candidate-freeze":
            freeze_path = args.output_root / "candidate-freeze.json"
            freeze = verify_archive_candidate_freeze(
                freeze_path,
                preset=preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            _emit(
                {
                    "command": "verify-candidate-freeze",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "candidate_id": freeze.candidate_id,
                    "valid": True,
                    "candidate_freeze": str(freeze_path),
                }
            )
            return 0
        if args.command == "calibrate-candidate":
            calibration = build_archive_final_calibration(
                preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            calibration_path = write_archive_final_calibration(
                args.output_root,
                calibration,
            )
            _emit(
                {
                    "command": "calibrate-candidate",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "candidate_id": calibration.candidate_id,
                    "training_plan_id": calibration.training_plan_id,
                    "calibration_id": calibration.calibration_id,
                    "model_family": calibration.model_family,
                    "calibration_variant": calibration.calibration_variant,
                    "selected_alpha": (
                        None
                        if calibration.selected_alpha is None
                        else str(calibration.selected_alpha)
                    ),
                    "selected_horizon_thresholds": tuple(
                        {
                            "horizon_ms": horizon_ms,
                            "threshold": (
                                None
                                if threshold is None
                                else str(threshold)
                            ),
                        }
                        for horizon_ms, threshold
                        in calibration.selected_horizon_thresholds
                    ),
                    "calibration_trade_count": (
                        calibration.calibration_trade_count
                    ),
                    "calibration_mean_realized_net_return": str(
                        calibration.calibration_mean_realized_net_return
                    ),
                    "validation_not_before_ms": (
                        calibration.validation_not_before_ms
                    ),
                    "prospective_only": calibration.prospective_only,
                    "promotion_eligible": calibration.promotion_eligible,
                    "trained_model_persisted": (
                        calibration.trained_model_persisted
                    ),
                    "execution_ready": calibration.execution_ready,
                    "final_calibration": str(calibration_path),
                }
            )
            return 0
        if args.command == "verify-final-calibration":
            calibration_path = (
                args.output_root / "candidate-final-calibration.json"
            )
            calibration = verify_archive_final_calibration(
                calibration_path,
                preset=preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            _emit(
                {
                    "command": "verify-final-calibration",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "candidate_id": calibration.candidate_id,
                    "calibration_id": calibration.calibration_id,
                    "valid": True,
                    "final_calibration": str(calibration_path),
                }
            )
            return 0
        if args.command == "plan-candidate-training":
            plan = build_archive_candidate_training_plan(
                preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            plan_path = write_archive_candidate_training_plan(
                args.output_root,
                plan,
            )
            _emit(
                {
                    "command": "plan-candidate-training",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "candidate_id": plan.candidate_id,
                    "plan_id": plan.plan_id,
                    "model_family": plan.model_family,
                    "calibration_variant": plan.calibration_variant,
                    "training_policy": plan.training_policy,
                    "selection_algorithm": plan.selection_algorithm,
                    "dataset_id": plan.dataset_id,
                    "fit_anchor_count": plan.fit_anchor_count,
                    "embargo_anchor_count": plan.embargo_anchor_count,
                    "calibration_anchor_count": plan.calibration_anchor_count,
                    "validation_not_before_ms": plan.validation_not_before_ms,
                    "prospective_only": plan.prospective_only,
                    "promotion_eligible": plan.promotion_eligible,
                    "execution_ready": plan.execution_ready,
                    "training_plan": str(plan_path),
                }
            )
            return 0
        if args.command == "verify-candidate-training-plan":
            plan_path = args.output_root / "candidate-training-plan.json"
            plan = verify_archive_candidate_training_plan(
                plan_path,
                preset=preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            _emit(
                {
                    "command": "verify-candidate-training-plan",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "candidate_id": plan.candidate_id,
                    "plan_id": plan.plan_id,
                    "valid": True,
                    "training_plan": str(plan_path),
                }
            )
            return 0
        if args.command == "review":
            review = build_archive_development_review(
                preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            review_path = write_archive_development_review(
                args.output_root,
                review,
            )
            _emit(
                {
                    "command": "review",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "review_id": review.review_id,
                    "review_policy_id": review.policy_id,
                    "status": review.status,
                    "promotion_eligible": review.promotion_eligible,
                    "qualified_variants": tuple(
                        {
                            "model_family": item.model_family,
                            "calibration_variant": item.calibration_variant,
                            "total_test_trades": item.total_test_trades,
                            "mean_realized_net_return": (
                                None
                                if item.mean_realized_net_return is None
                                else str(item.mean_realized_net_return)
                            ),
                        }
                        for item in review.variants
                        if item.eligible_for_freeze_review
                    ),
                    "review_path": str(review_path),
                }
            )
            return 0
        if args.command == "verify-bundle":
            bundle = verify_archive_preset_bundle_receipt(
                args.output_root / "preset-bundle.json",
                preset=preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            _emit(
                {
                    "bundle_id": bundle.bundle_id,
                    "command": "verify-bundle",
                    "paid_request_performed": False,
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "valid": True,
                }
            )
            return 0

        if args.command == "run-prepared":
            result = run_prepared_archive_experiment_preset(
                preset=preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            receipt = verify_archive_preset_run_receipt(
                args.output_root / "preset-run.json",
                preset=preset,
            )
            bundle = verify_archive_preset_bundle_receipt(
                args.output_root / "preset-bundle.json",
                preset=preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                output_root=args.output_root,
            )
            implementation = verify_archive_preset_source_attestation(
                args.output_root,
                preset=preset,
            )
            _emit(
                {
                    "command": "run-prepared",
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "evidence_class": preset.evidence_class,
                    "paid_request_performed": False,
                    "prepared_source_execution": True,
                    "archive_manifest_id": result.archive.manifest_id,
                    "archive_shard_count": result.archive.shard_count,
                    "archive_total_byte_count": result.archive.total_byte_count,
                    "overlap_report_id": result.overlap.report_id,
                    "overlap_compared_count": result.overlap.compared_count,
                    "dataset_id": result.dataset_id,
                    "report_id": result.report_id,
                    "comparison_version": result.comparison.comparison_version,
                    "preset_run_receipt_id": receipt.receipt_id,
                    "preset_run_receipt": str(
                        args.output_root / "preset-run.json"
                    ),
                    "preset_bundle_id": bundle.bundle_id,
                    "preset_bundle_receipt": str(
                        args.output_root / "preset-bundle.json"
                    ),
                    "implementation_attestation_id": (
                        implementation.attestation_id
                    ),
                    "source_tree_sha256": implementation.source_tree_sha256,
                    "source_file_count": len(implementation.files),
                    "row_count": result.comparison.dataset_row_count,
                    "fold_count": len(result.comparison.baseline_folds),
                    "output_root": str(args.output_root),
                }
            )
            return 0

        settings = Settings.from_env()
        if settings.execution_mode is not ExecutionMode.PAPER:
            raise ValueError("historical archive presets require paper execution mode")
        client = InfoClient(settings)
        if args.command == "prepare":
            preparation = prepare_archive_experiment_preset(
                client,
                preset=preset,
                archive_root=args.archive_root,
                source_root=args.source_root,
                clock_ms=_clock(args.received_at_ms),
            )
            _emit(
                {
                    "command": "prepare",
                    "preset": preset.name,
                    "preset_id": preset.preset_id,
                    "evidence_class": preset.evidence_class,
                    "paid_request_performed": False,
                    "preparation_id": preparation.preparation_id,
                    "archive_manifest_id": preparation.archive.manifest_id,
                    "archive_shard_count": preparation.archive.shard_count,
                    "archive_total_byte_count": (
                        preparation.archive.total_byte_count
                    ),
                    "archive_ingest_manifest_id": (
                        preparation.archive_ingest_manifest_id
                    ),
                    "coverage_report_id": preparation.coverage_report_id,
                    "overlap_report_id": preparation.overlap.report_id,
                    "overlap_compared_count": preparation.overlap.compared_count,
                    "source_preparation": str(
                        args.source_root / "source-preparation.json"
                    ),
                    "source_root": str(args.source_root),
                }
            )
            return 0

        result = run_archive_experiment_preset(
            client,
            preset=preset,
            archive_root=args.archive_root,
            source_root=args.source_root,
            output_root=args.output_root,
            clock_ms=_clock(args.received_at_ms),
        )
        receipt = verify_archive_preset_run_receipt(
            args.output_root / "preset-run.json",
            preset=preset,
        )
        bundle = verify_archive_preset_bundle_receipt(
            args.output_root / "preset-bundle.json",
            preset=preset,
            archive_root=args.archive_root,
            source_root=args.source_root,
            output_root=args.output_root,
        )
        implementation = verify_archive_preset_source_attestation(
            args.output_root,
            preset=preset,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "run",
            "preset": preset.name,
            "preset_id": preset.preset_id,
            "evidence_class": preset.evidence_class,
            "archive_manifest_id": result.archive.manifest_id,
            "archive_shard_count": result.archive.shard_count,
            "archive_total_byte_count": result.archive.total_byte_count,
            "overlap_report_id": result.overlap.report_id,
            "overlap_compared_count": result.overlap.compared_count,
            "dataset_id": result.dataset_id,
            "report_id": result.report_id,
            "comparison_version": result.comparison.comparison_version,
            "preset_run_receipt_id": receipt.receipt_id,
            "preset_run_receipt": str(args.output_root / "preset-run.json"),
            "preset_bundle_id": bundle.bundle_id,
            "preset_bundle_receipt": str(args.output_root / "preset-bundle.json"),
            "implementation_attestation_id": implementation.attestation_id,
            "source_tree_sha256": implementation.source_tree_sha256,
            "source_file_count": len(implementation.files),
            "row_count": result.comparison.dataset_row_count,
            "fold_count": len(result.comparison.baseline_folds),
            "output_root": str(args.output_root),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
