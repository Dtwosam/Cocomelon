from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from cocomelon.domain.replay import EvidenceClass, ReplayManifest
from cocomelon.replay.jsonl import ValidatedSegment, validate_jsonl_segment


class ReplayInputMismatchError(ValueError):
    pass


def build_replay_manifest(
    segments: Iterable[ValidatedSegment],
    *,
    code_version: str,
    python_version: str,
    config_sha256: str,
    strategy_version: str,
    risk_version: str,
    execution_version: str,
    journal_schema_version: int,
    replay_engine_version: str,
    evidence_class: EvidenceClass,
) -> ReplayManifest:
    materialized = tuple(segments)
    if not materialized:
        raise ValueError("segments must not be empty")
    relative_paths = [segment.input_file.relative_path for segment in materialized]
    if len(set(relative_paths)) != len(relative_paths):
        raise ValueError("replay input relative paths must be unique")
    if any(segment.evidence_class is not evidence_class for segment in materialized):
        raise ValueError("segment evidence_class does not match manifest evidence_class")
    rows = tuple(row for segment in materialized for row in segment.rows)
    if not rows:
        raise ValueError("manifest requires at least one evidence row")

    return ReplayManifest.create(
        code_version=code_version,
        python_version=python_version,
        config_sha256=config_sha256,
        strategy_version=strategy_version,
        risk_version=risk_version,
        execution_version=execution_version,
        journal_schema_version=journal_schema_version,
        replay_engine_version=replay_engine_version,
        evidence_class=evidence_class,
        inputs=tuple(segment.input_file for segment in materialized),
        start_receive_ms=min(row.receive_time_ms for row in rows),
        end_receive_ms=max(row.receive_time_ms for row in rows),
    )


def verify_replay_inputs(
    manifest: ReplayManifest,
    *,
    root: str | Path,
) -> tuple[ValidatedSegment, ...]:
    root_path = Path(root)
    verified: list[ValidatedSegment] = []
    for expected in manifest.inputs:
        segment = validate_jsonl_segment(
            root_path / expected.relative_path,
            root=root_path,
            evidence_class=manifest.evidence_class,
        )
        actual = segment.input_file
        if actual.size_bytes != expected.size_bytes:
            raise ReplayInputMismatchError(
                f"size mismatch for {expected.relative_path}: "
                f"expected {expected.size_bytes}, got {actual.size_bytes}"
            )
        if actual.sha256 != expected.sha256:
            raise ReplayInputMismatchError(f"sha256 mismatch for {expected.relative_path}")
        if actual.schema_version != expected.schema_version:
            raise ReplayInputMismatchError(
                f"schema_version mismatch for {expected.relative_path}"
            )
        if actual.relative_path != expected.relative_path:
            raise ReplayInputMismatchError(
                f"relative_path mismatch for {expected.relative_path}"
            )
        verified.append(segment)
    return tuple(verified)
