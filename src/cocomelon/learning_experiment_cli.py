from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO, cast

from cocomelon.research.learning_experiment import (
    SUPPORTED_MODEL_FAMILIES,
    run_learning_experiment,
)
from cocomelon.research.outcome_learning import LearningEvidenceKind


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


def _json_object(path: Path, field: str) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must be a readable JSON object") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ValueError(f"{field} must be a JSON object")
    return cast(dict[str, object], raw)


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
        prog="cocomelon-learning-experiment",
        description=(
            "Materialize one reproducible research-only learning experiment "
            "from an append-only learning ledger"
        ),
    )
    parser.add_argument("--learning-root", required=True, type=Path)
    parser.add_argument("--feature-store-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--as-of-ms", required=True, type=int)
    parser.add_argument("--kind", required=True, type=_evidence_kind)
    parser.add_argument("--feature", required=True, action="append")
    parser.add_argument(
        "--model-family",
        required=True,
        choices=tuple(sorted(SUPPORTED_MODEL_FAMILIES)),
    )
    parser.add_argument("--model-config", required=True, type=Path)
    parser.add_argument("--decision-policy", required=True, type=Path)
    parser.add_argument("--implementation-commit-sha", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_learning_experiment(
            learning_root=args.learning_root,
            feature_store_dir=args.feature_store_dir,
            output_root=args.output_root,
            as_of_ms=args.as_of_ms,
            evidence_kind=args.kind,
            feature_registry=tuple(args.feature),
            model_family=args.model_family,
            model_config=_json_object(args.model_config, "model_config"),
            decision_policy=_json_object(
                args.decision_policy,
                "decision_policy",
            ),
            implementation_commit_sha=args.implementation_commit_sha,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-experiment",
            **result.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
