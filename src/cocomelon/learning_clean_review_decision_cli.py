from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_clean_review_decision import (
    DECISION_ADVANCE,
    DECISION_REJECT,
    build_learning_clean_review_decision,
    verify_learning_clean_review_decision,
    write_learning_clean_review_decision,
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
        prog="cocomelon-learning-clean-review-decision",
        description=(
            "Record an authenticated human review decision for a terminal "
            "learned clean candidate"
        ),
    )
    parser.add_argument("--review-dossier", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--validation-score", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at-ms", required=True, type=int)
    parser.add_argument(
        "--decision",
        required=True,
        choices=(DECISION_ADVANCE, DECISION_REJECT),
    )
    parser.add_argument("--rationale", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        decision = build_learning_clean_review_decision(
            review_dossier_path=args.review_dossier,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            finalization_path=args.finalization,
            evidence_root=args.evidence_root,
            reviewer=args.reviewer,
            reviewed_at_ms=args.reviewed_at_ms,
            decision=args.decision,
            rationale=args.rationale,
        )
        path = write_learning_clean_review_decision(args.output_root, decision)
        verified = verify_learning_clean_review_decision(
            path,
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
            "command": "learning-clean-review-decision",
            "path": str(path),
            "candidate_id": verified.candidate_id,
            "review_dossier_id": verified.review_dossier_id,
            "review_decision_id": verified.review_decision_id,
            "reviewer": verified.reviewer,
            "reviewed_at_ms": verified.reviewed_at_ms,
            "decision": verified.decision,
            "shadow_evaluation_authorized": verified.shadow_evaluation_authorized,
            "human_review_completed": verified.human_review_completed,
            "paper_only": verified.paper_only,
            "research_only": verified.research_only,
            "promotion_eligible": verified.promotion_eligible,
            "execution_ready": verified.execution_ready,
            "live_promotion_authorized": verified.live_promotion_authorized,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
