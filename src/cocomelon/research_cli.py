from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import ResearchArtifactBatch, evaluate_research_checkpoint
from cocomelon.research.lifecycle import activate_validation_cutover
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError


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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _artifact_batch(value: object, *, descriptor_path: Path) -> ResearchArtifactBatch:
    payload = _mapping(value, "artifact_batch")
    allowed = {"artifact_root", "batch_id", "source_id"}
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise ValueError(
            "artifact_batch contains non-authoritative caller fields: "
            + ",".join(unexpected)
        )
    artifact_root = Path(_string(payload.get("artifact_root"), "artifact_root"))
    if not artifact_root.is_absolute():
        artifact_root = (descriptor_path.parent / artifact_root).resolve()
    return ResearchArtifactBatch(
        artifact_root=artifact_root,
        batch_id=_string(payload.get("batch_id"), "batch_id"),
        source_id=_string(payload.get("source_id"), "source_id"),
    )


def _load_checkpoint_dataset(path: Path) -> tuple[ResearchArtifactBatch, ...]:
    payload = _mapping(json.loads(path.read_text(encoding="utf-8")), "dataset")
    if set(payload) != {"artifact_batches"}:
        raise ValueError(
            "checkpoint dataset must contain only authoritative artifact_batches descriptors"
        )
    return tuple(
        _artifact_batch(item, descriptor_path=path)
        for item in _array(payload.get("artifact_batches"), "artifact_batches")
    )


def _add_registry_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-research",
        description="Isolated touched-data research control surface",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-registry")
    _add_registry_argument(init_parser)

    v4_parser = subparsers.add_parser("register-v4-interval")
    _add_registry_argument(v4_parser)
    v4_parser.add_argument("--run-id", required=True)
    v4_parser.add_argument("--start-ms", required=True, type=int)
    v4_parser.add_argument("--end-ms", required=True, type=int)
    v4_parser.add_argument("--disposition", required=True)

    v4_complete_parser = subparsers.add_parser("mark-v4-registry-complete")
    _add_registry_argument(v4_complete_parser)
    v4_complete_parser.add_argument("--through-ms", required=True, type=int)
    v4_complete_parser.add_argument("--source-id", required=True)

    candidate_parser = subparsers.add_parser("create-candidate")
    _add_registry_argument(candidate_parser)
    candidate_parser.add_argument("--candidate-id", required=True)
    candidate_parser.add_argument("--family-id", required=True)
    candidate_parser.add_argument("--parent-candidate-id")
    candidate_parser.add_argument("--config-digest", required=True)
    candidate_parser.add_argument("--code-revision", required=True)
    candidate_parser.add_argument("--execution-config-json", required=True)
    candidate_parser.add_argument("--risk-config-json", required=True)

    batch_parser = subparsers.add_parser("record-batch")
    _add_registry_argument(batch_parser)
    batch_parser.add_argument("--candidate-id", required=True)
    batch_parser.add_argument("--batch-id", required=True)
    batch_parser.add_argument("--source-id", required=True)
    batch_parser.add_argument("--replay-run-id", required=True)
    batch_parser.add_argument("--start-ms", required=True, type=int)
    batch_parser.add_argument("--end-ms", required=True, type=int)

    checkpoint_parser = subparsers.add_parser("checkpoint")
    _add_registry_argument(checkpoint_parser)
    checkpoint_parser.add_argument("--candidate-id", required=True)
    checkpoint_parser.add_argument("--dataset", required=True, type=Path)

    freeze_parser = subparsers.add_parser("freeze-candidate")
    _add_registry_argument(freeze_parser)
    freeze_parser.add_argument("--candidate-id", required=True)
    freeze_parser.add_argument("--freeze-ms", required=True, type=int)

    cutover_parser = subparsers.add_parser("validate-cutover")
    _add_registry_argument(cutover_parser)
    cutover_parser.add_argument("--candidate-id", required=True)
    cutover_parser.add_argument("--validation-start-ms", required=True, type=int)

    return parser


def _create_candidate(registry: ResearchRegistry, args: argparse.Namespace) -> dict[str, object]:
    parent_id = args.parent_candidate_id
    ancestors: tuple[str, ...] = ()
    if parent_id is not None:
        parent = registry.load_candidate(parent_id)
        ancestors = parent.ancestor_candidate_ids + (parent.candidate_id,)
    manifest = ResearchCandidateManifest(
        candidate_id=args.candidate_id,
        family_id=args.family_id,
        parent_candidate_id=parent_id,
        ancestor_candidate_ids=ancestors,
        config_digest=args.config_digest,
        code_revision=args.code_revision,
        execution_config_json=args.execution_config_json,
        risk_config_json=args.risk_config_json,
        state=ResearchCandidateState.DRAFT,
        first_observation_ms=None,
        last_observation_ms=None,
        source_provenance_ids=(),
        local_touched_intervals=(),
        effective_touched_intervals=(),
        performance_report_ids=(),
    )
    registry.create_candidate(manifest)
    return {
        "candidate_id": manifest.candidate_id,
        "command": "create-candidate",
        "family_id": manifest.family_id,
        "state": manifest.state.value,
    }


def _execute(args: argparse.Namespace) -> dict[str, object]:
    registry = ResearchRegistry(args.registry)
    try:
        if args.command == "init-registry":
            return {"command": "init-registry", "registry": str(args.registry)}
        if args.command == "register-v4-interval":
            interval = TimeInterval(args.start_ms, args.end_ms)
            registry.record_v4_interval(
                run_id=args.run_id,
                interval=interval,
                disposition=args.disposition,
            )
            return {
                "command": "register-v4-interval",
                "disposition": args.disposition,
                "end_ms": interval.end_ms,
                "run_id": args.run_id,
                "start_ms": interval.start_ms,
            }
        if args.command == "mark-v4-registry-complete":
            registry.mark_v4_registry_complete_through(
                through_ms=args.through_ms,
                source_id=args.source_id,
            )
            return {
                "command": "mark-v4-registry-complete",
                "source_id": args.source_id,
                "through_ms": args.through_ms,
            }
        if args.command == "create-candidate":
            return _create_candidate(registry, args)
        if args.command == "record-batch":
            interval = TimeInterval(args.start_ms, args.end_ms)
            registry.record_batch(
                candidate_id=args.candidate_id,
                batch_id=args.batch_id,
                source_id=args.source_id,
                replay_run_id=args.replay_run_id,
                interval=interval,
            )
            return {
                "batch_id": args.batch_id,
                "candidate_id": args.candidate_id,
                "command": "record-batch",
                "end_ms": interval.end_ms,
                "replay_run_id": args.replay_run_id,
                "source_id": args.source_id,
                "start_ms": interval.start_ms,
            }
        if args.command == "checkpoint":
            artifact_batches = _load_checkpoint_dataset(args.dataset)
            return evaluate_research_checkpoint(
                registry=registry,
                candidate_id=args.candidate_id,
                artifact_batches=artifact_batches,
            ).to_dict()
        if args.command == "freeze-candidate":
            registry.freeze_candidate(args.candidate_id, freeze_ms=args.freeze_ms)
            candidate = registry.load_candidate(args.candidate_id)
            return {
                "candidate_id": args.candidate_id,
                "command": "freeze-candidate",
                "freeze_ms": args.freeze_ms,
                "state": candidate.state.value,
            }
        if args.command == "validate-cutover":
            activate_validation_cutover(
                registry,
                args.candidate_id,
                validation_start_ms=args.validation_start_ms,
            )
            candidate = registry.load_candidate(args.candidate_id)
            return {
                "allowed": True,
                "candidate_id": args.candidate_id,
                "command": "validate-cutover",
                "state": candidate.state.value,
                "validation_start_ms": args.validation_start_ms,
            }
        raise ResearchRegistryError(f"unknown research command: {args.command}")
    finally:
        registry.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _execute(args)
    except (OSError, ValueError, ResearchRegistryError, json.JSONDecodeError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())