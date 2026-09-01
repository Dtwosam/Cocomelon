from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.artifact import ResearchArtifactError
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.runner import ResearchRunnerRequest, run_research_artifact_attempt
from cocomelon.research.runner_history import ResearchRunnerAttempt, load_runner_attempts

RESEARCH_RUNNER_LABEL = "TOUCHED / NON-PROMOTIONAL"


def _emit_json(value: object, *, stream: TextIO) -> None:
    print(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=stream,
    )


def _require_registry(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"research registry does not exist: {path}")


def _attempt_payload(attempt: ResearchRunnerAttempt) -> dict[str, object]:
    return {
        "artifact_root": attempt.artifact_root,
        "attempt_id": attempt.attempt_id,
        "attempt_index": attempt.attempt_index,
        "batch_id": attempt.batch_id,
        "candidate_id": attempt.candidate_id,
        "end_ms": attempt.end_ms,
        "error_message": attempt.error_message,
        "error_type": attempt.error_type,
        "report_id": attempt.report_id,
        "source_id": attempt.source_id,
        "start_ms": attempt.start_ms,
        "status": attempt.status.value,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-research-runner",
        description="Run touched/non-promotional authenticated research attempts",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run_parser = commands.add_parser("run-artifact")
    run_parser.add_argument("--registry", required=True, type=Path)
    run_parser.add_argument("--attempt-id", required=True)
    run_parser.add_argument("--candidate-id", required=True)
    run_parser.add_argument("--batch-id", required=True)
    run_parser.add_argument("--source-id", required=True)
    run_parser.add_argument("--artifact-root", required=True, type=Path)

    attempts_parser = commands.add_parser("attempts")
    attempts_parser.add_argument("--registry", required=True, type=Path)
    attempts_parser.add_argument("--candidate-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    registry: ResearchRegistry | None = None
    try:
        registry_path: Path = args.registry
        _require_registry(registry_path)
        registry = ResearchRegistry(registry_path)

        if args.command == "run-artifact":
            result = run_research_artifact_attempt(
                registry,
                ResearchRunnerRequest(
                    attempt_id=args.attempt_id,
                    candidate_id=args.candidate_id,
                    batch_id=args.batch_id,
                    source_id=args.source_id,
                    artifact_root=args.artifact_root,
                ),
            )
            _emit_json(
                {
                    "attempt_id": result.attempt_id,
                    "end_ms": result.end_ms,
                    "label": RESEARCH_RUNNER_LABEL,
                    "report_id": result.report_id,
                    "start_ms": result.start_ms,
                    "status": "succeeded",
                },
                stream=sys.stdout,
            )
        else:
            attempts = load_runner_attempts(
                registry.connection,
                candidate_id=args.candidate_id,
            )
            _emit_json(
                {
                    "attempts": [_attempt_payload(attempt) for attempt in attempts],
                    "label": RESEARCH_RUNNER_LABEL,
                },
                stream=sys.stdout,
            )
    except (
        FileNotFoundError,
        OSError,
        ValueError,
        ResearchArtifactError,
        ResearchRegistryError,
        json.JSONDecodeError,
        sqlite3.Error,
    ) as exc:
        _emit_json(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    finally:
        if registry is not None:
            registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
