from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO, cast

from cocomelon.research.learning_candidate_predictor import (
    build_learning_candidate_predictor,
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


def _feature_mapping(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in raw.items()
    ):
        raise ValueError("features JSON must be an object of string values")
    return cast(dict[str, str], raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-candidate-predict",
        description=(
            "Score one prospective feature tuple with a frozen learning "
            "candidate package"
        ),
    )
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--validation-spec", required=True, type=Path)
    parser.add_argument("--features-json", required=True, type=Path)
    parser.add_argument("--observed-at-ms", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        predictor = build_learning_candidate_predictor(
            package_root=args.package_root,
            validation_spec_path=args.validation_spec,
        )
        features = _feature_mapping(args.features_json)
        expected = set(predictor.feature_registry)
        if set(features) != expected:
            raise ValueError(
                "features JSON keys must exactly match frozen feature registry"
            )
        values = tuple(features[name] for name in predictor.feature_registry)
        prediction = predictor.score(
            feature_values=values,
            observed_at_ms=args.observed_at_ms,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-candidate-predict",
            **prediction.to_dict(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
