from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO, cast

from cocomelon.research.learning_challenger_run import (
    build_learning_challenger_run_manifest,
    write_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset_bundle import (
    load_verified_learning_dataset_bundle,
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


def _kind(value: str) -> LearningEvidenceKind:
    try:
        return LearningEvidenceKind(value)
    except ValueError as exc:
        choices = ", ".join(kind.value for kind in LearningEvidenceKind)
        raise argparse.ArgumentTypeError(
            f"unsupported evidence kind {value!r}; choose from {choices}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-learning-challenger-run",
        description="Freeze a reproducible research-only challenger run manifest",
    )
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--input-kind",
        required=True,
        action="append",
        type=_kind,
    )
    parser.add_argument(
        "--feature",
        required=True,
        action="append",
    )
    parser.add_argument("--model-family", required=True)
    parser.add_argument("--model-config", required=True, type=Path)
    parser.add_argument("--decision-policy", required=True, type=Path)
    parser.add_argument("--implementation-commit-sha", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        bundle = load_verified_learning_dataset_bundle(
            output_dir=args.bundle_dir,
        )
        manifest = build_learning_challenger_run_manifest(
            bundle,
            input_kinds=tuple(args.input_kind),
            feature_registry=tuple(args.feature),
            model_family=args.model_family,
            model_config=_json_object(args.model_config, "model_config"),
            decision_policy=_json_object(
                args.decision_policy,
                "decision_policy",
            ),
            implementation_commit_sha=args.implementation_commit_sha,
        )
        write_learning_challenger_run_manifest(args.output, manifest)
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "learning-challenger-run",
            "run_id": manifest.run_id,
            "dataset_id": manifest.dataset_id,
            "dataset_lineage_id": manifest.dataset_lineage_id,
            "input_record_count": len(manifest.input_record_ids),
            "feature_registry_id": manifest.feature_registry_id,
            "model_config_id": manifest.model_config_id,
            "decision_policy_id": manifest.decision_policy_id,
            "output": str(args.output),
            "research_only": manifest.research_only,
            "promotion_eligible": manifest.promotion_eligible,
            "execution_ready": manifest.execution_ready,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
