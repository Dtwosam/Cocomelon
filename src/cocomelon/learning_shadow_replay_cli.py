from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_shadow_replay import (
    run_learning_shadow_replay,
    verify_learning_shadow_replay_receipt,
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


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--recording-root", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--shadow-evidence-root", required=True, type=Path)
    parser.add_argument("--shadow-admission", required=True, type=Path)
    parser.add_argument("--review-decision", required=True, type=Path)
    parser.add_argument("--review-dossier", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--validation-score", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--clean-evidence-root", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-shadow-replay",
        description=(
            "Run or verify one frozen learned candidate through the trusted "
            "offline paper replay engine"
        ),
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    run = subparsers.add_parser("run")
    _add_common(run)
    run.add_argument("--runtime-code-revision", required=True)
    run.add_argument("--evidence-eligible-at-ms", required=True, type=int)

    verify = subparsers.add_parser("verify")
    _add_common(verify)
    verify.add_argument("--receipt", required=True, type=Path)
    return parser


def _verify_args(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "bundle_path": args.bundle,
        "output_root": args.output_root,
        "shadow_evidence_root": args.shadow_evidence_root,
        "shadow_admission_path": args.shadow_admission,
        "review_decision_path": args.review_decision,
        "review_dossier_path": args.review_dossier,
        "package_root": args.package_root,
        "validation_spec_path": args.validation_spec,
        "validation_score_path": args.validation_score,
        "finalization_path": args.finalization,
        "clean_evidence_root": args.clean_evidence_root,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.action == "run":
            receipt = run_learning_shadow_replay(
                recording_root=args.recording_root,
                bundle_path=args.bundle,
                output_root=args.output_root,
                shadow_evidence_root=args.shadow_evidence_root,
                shadow_admission_path=args.shadow_admission,
                review_decision_path=args.review_decision,
                review_dossier_path=args.review_dossier,
                package_root=args.package_root,
                validation_spec_path=args.validation_spec,
                validation_score_path=args.validation_score,
                finalization_path=args.finalization,
                clean_evidence_root=args.clean_evidence_root,
                runtime_code_revision=args.runtime_code_revision,
                evidence_eligible_at_ms=args.evidence_eligible_at_ms,
            )
            receipt_path = args.output_root / "shadow-replay-receipt.json"
        else:
            receipt_path = args.receipt
            receipt = verify_learning_shadow_replay_receipt(
                receipt_path,
                **_verify_args(args),
            )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-shadow-replay",
            "action": args.action,
            "receipt_path": str(receipt_path),
            "receipt_id": receipt.receipt_id,
            "shadow_admission_id": receipt.shadow_admission_id,
            "candidate_id": receipt.candidate_id,
            "shadow_campaign_id": receipt.shadow_campaign_id,
            "closed_paper_trade_count": len(receipt.closed_trade_ids),
            "feature_snapshot_count": receipt.feature_snapshot_count,
            "shadow_evidence_state_digest": receipt.shadow_evidence_state_digest,
            "paper_only": receipt.paper_only,
            "research_only": receipt.research_only,
            "promotion_eligible": receipt.promotion_eligible,
            "execution_ready": receipt.execution_ready,
            "live_promotion_authorized": receipt.live_promotion_authorized,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
