from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_shadow_admission import (
    build_learning_shadow_admission,
    verify_learning_shadow_admission,
    write_learning_shadow_admission,
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
        prog="cocomelon-learning-shadow-admission",
        description=(
            "Admit an approved learned candidate to larger mainnet paper/shadow "
            "evaluation without granting live authority"
        ),
    )
    parser.add_argument("--review-decision", required=True, type=Path)
    parser.add_argument("--review-dossier", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--validation-score", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--shadow-start-ms", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        admission = build_learning_shadow_admission(
            review_decision_path=args.review_decision,
            review_dossier_path=args.review_dossier,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            finalization_path=args.finalization,
            evidence_root=args.evidence_root,
            shadow_start_ms=args.shadow_start_ms,
        )
        path = write_learning_shadow_admission(args.output_root, admission)
        verified = verify_learning_shadow_admission(
            path,
            review_decision_path=args.review_decision,
            review_dossier_path=args.review_dossier,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            finalization_path=args.finalization,
            evidence_root=args.evidence_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-shadow-admission",
            "path": str(path),
            "candidate_id": verified.candidate_id,
            "review_decision_id": verified.review_decision_id,
            "shadow_admission_id": verified.shadow_admission_id,
            "reviewed_at_ms": verified.reviewed_at_ms,
            "shadow_start_ms": verified.shadow_start_ms,
            "minimum_closed_mainnet_paper_trades": (
                verified.minimum_closed_mainnet_paper_trades
            ),
            "minimum_shadow_calendar_days": verified.minimum_shadow_calendar_days,
            "minimum_profit_factor": str(verified.minimum_profit_factor),
            "maximum_paper_drawdown_fraction": str(
                verified.maximum_paper_drawdown_fraction
            ),
            "shadow_evaluation_authorized": verified.shadow_evaluation_authorized,
            "promotion_eligible": verified.promotion_eligible,
            "execution_ready": verified.execution_ready,
            "live_promotion_authorized": verified.live_promotion_authorized,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
