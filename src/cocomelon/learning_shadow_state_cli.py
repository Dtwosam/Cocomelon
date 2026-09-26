from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_shadow_state import (
    build_learning_shadow_state,
    verify_learning_shadow_state,
    write_learning_shadow_state,
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
        prog="cocomelon-learning-shadow-state",
        description="Build or verify non-economic learned shadow operational state",
    )
    parser.add_argument("--shadow-evidence-root", required=True, type=Path)
    parser.add_argument("--shadow-admission", required=True, type=Path)
    parser.add_argument("--review-decision", required=True, type=Path)
    parser.add_argument("--review-dossier", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--validation-score", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--clean-evidence-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--as-of-ms", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state = build_learning_shadow_state(
            shadow_evidence_root=args.shadow_evidence_root,
            shadow_admission_path=args.shadow_admission,
            review_decision_path=args.review_decision,
            review_dossier_path=args.review_dossier,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            finalization_path=args.finalization,
            clean_evidence_root=args.clean_evidence_root,
            as_of_ms=args.as_of_ms,
        )
        path = write_learning_shadow_state(args.output_root, state)
        verified = verify_learning_shadow_state(
            path,
            shadow_evidence_root=args.shadow_evidence_root,
            shadow_admission_path=args.shadow_admission,
            review_decision_path=args.review_decision,
            review_dossier_path=args.review_dossier,
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            finalization_path=args.finalization,
            clean_evidence_root=args.clean_evidence_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-shadow-state",
            "path": str(path),
            "candidate_id": verified.candidate_id,
            "shadow_admission_id": verified.shadow_admission_id,
            "state_id": verified.state_id,
            "status": verified.status,
            "closed_paper_trade_count": verified.closed_paper_trade_count,
            "campaign_count": verified.campaign_count,
            "shadow_start_ms": verified.shadow_start_ms,
            "as_of_ms": verified.as_of_ms,
            "shadow_evidence_state_digest": verified.shadow_evidence_state_digest,
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
