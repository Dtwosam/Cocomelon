from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.learning_readiness import evaluate_learning_readiness
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
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


def _evidence_kind(value: str) -> LearningEvidenceKind:
    try:
        return LearningEvidenceKind(value)
    except ValueError as exc:
        choices = ", ".join(kind.value for kind in LearningEvidenceKind)
        raise argparse.ArgumentTypeError(
            f"unsupported evidence kind {value!r}; choose from {choices}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-readiness",
        description=(
            "Audit research-eligible learning evidence and authenticated "
            "point-in-time feature coverage without training a model"
        ),
    )
    parser.add_argument("--learning-root", required=True, type=Path)
    parser.add_argument("--feature-store-dir", type=Path)
    parser.add_argument("--as-of-ms", required=True, type=int)
    parser.add_argument("--kind", required=True, type=_evidence_kind)
    parser.add_argument("--feature", required=True, action="append")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ledger = LearningEvidenceLedger(args.learning_root)
        feature_store = (
            None
            if args.feature_store_dir is None
            else LearningFeatureSnapshotStore(args.feature_store_dir)
        )
        report = evaluate_learning_readiness(
            ledger,
            feature_store=feature_store,
            as_of_ms=args.as_of_ms,
            evidence_kind=args.kind,
            feature_registry=tuple(args.feature),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-readiness",
            **report.to_dict(),
        }
    )
    return 0 if report.structurally_ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
