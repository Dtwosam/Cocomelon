from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_clean_review_dossier import (
    build_learning_clean_review_dossier,
    verify_learning_clean_review_dossier,
    write_learning_clean_review_dossier,
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
        prog="cocomelon-learning-clean-review-dossier",
        description=(
            "Materialize a terminal review dossier for a verified "
            "review-eligible learned clean candidate"
        ),
    )
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--validation-score", required=True, type=Path)
    parser.add_argument("--finalization", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dossier = build_learning_clean_review_dossier(
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
            validation_score_path=args.validation_score,
            finalization_path=args.finalization,
            evidence_root=args.evidence_root,
        )
        path = write_learning_clean_review_dossier(
            args.output_root,
            dossier,
        )
        verified = verify_learning_clean_review_dossier(
            path,
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
            "command": "learning-clean-review-dossier",
            "path": str(path),
            **verified.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
