from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from cocomelon.domain.journal import canonical_json, sha256_text
from cocomelon.domain.market import MarketId

REPLAY_MANIFEST_SCHEMA_VERSION = 1


class EvidenceClass(StrEnum):
    CANDLE_CONTEXT = "candle_context"
    MICROSTRUCTURE = "microstructure"


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"{field} must be a SHA-256 hex digest")


@dataclass(frozen=True, slots=True, order=True)
class SourceCoordinate:
    relative_path: str
    segment: int
    line_number: int

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute():
            raise ValueError("relative_path must be relative")
        if ".." in path.parts:
            raise ValueError("relative_path must not contain parent traversal")
        if not self.relative_path.strip():
            raise ValueError("relative_path must not be empty")
        if self.segment <= 0:
            raise ValueError("segment must be positive")
        if self.line_number <= 0:
            raise ValueError("line_number must be positive")


@dataclass(frozen=True, slots=True)
class ReplayInputFile:
    relative_path: str
    size_bytes: int
    sha256: str
    schema_version: int

    def __post_init__(self) -> None:
        path = PurePosixPath(self.relative_path)
        if path.is_absolute():
            raise ValueError("relative_path must be relative")
        if ".." in path.parts:
            raise ValueError("relative_path must not contain parent traversal")
        if not self.relative_path.strip():
            raise ValueError("relative_path must not be empty")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        _require_sha256(self.sha256, "sha256")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    evidence_class: EvidenceClass
    receive_time_ms: int
    exchange_time_ms: int | None
    record_type: str
    source: str
    coordinate: SourceCoordinate
    payload_json: str
    market: MarketId | None = None
    event_kind: str | None = None
    event_key: str | None = None

    def __post_init__(self) -> None:
        if self.receive_time_ms < 0:
            raise ValueError("receive_time_ms must be non-negative")
        if self.exchange_time_ms is not None and self.exchange_time_ms < 0:
            raise ValueError("exchange_time_ms must be non-negative")
        _require_nonempty(self.record_type, "record_type")
        _require_nonempty(self.source, "source")
        if self.event_kind is not None:
            _require_nonempty(self.event_kind, "event_kind")
        if self.event_key is not None:
            _require_nonempty(self.event_key, "event_key")


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    run_id: str
    manifest_schema_version: int
    code_version: str
    python_version: str
    config_sha256: str
    strategy_version: str
    risk_version: str
    execution_version: str
    journal_schema_version: int
    replay_engine_version: str
    evidence_class: EvidenceClass
    inputs: tuple[ReplayInputFile, ...]
    start_receive_ms: int
    end_receive_ms: int

    def __post_init__(self) -> None:
        _require_sha256(self.run_id, "run_id")
        if self.manifest_schema_version <= 0:
            raise ValueError("manifest_schema_version must be positive")
        for field, value in (
            ("code_version", self.code_version),
            ("python_version", self.python_version),
            ("strategy_version", self.strategy_version),
            ("risk_version", self.risk_version),
            ("execution_version", self.execution_version),
            ("replay_engine_version", self.replay_engine_version),
        ):
            _require_nonempty(value, field)
        _require_sha256(self.config_sha256, "config_sha256")
        if self.journal_schema_version <= 0:
            raise ValueError("journal_schema_version must be positive")
        if not self.inputs:
            raise ValueError("inputs must not be empty")
        if self.start_receive_ms < 0:
            raise ValueError("start_receive_ms must be non-negative")
        if self.end_receive_ms < self.start_receive_ms:
            raise ValueError("end_receive_ms must be >= start_receive_ms")

    @classmethod
    def create(
        cls,
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
        inputs: tuple[ReplayInputFile, ...],
        start_receive_ms: int,
        end_receive_ms: int,
        manifest_schema_version: int = REPLAY_MANIFEST_SCHEMA_VERSION,
    ) -> ReplayManifest:
        ordered_inputs = tuple(sorted(inputs, key=lambda item: item.relative_path))
        canonical = {
            "manifest_schema_version": manifest_schema_version,
            "code_version": code_version,
            "python_version": python_version,
            "config_sha256": config_sha256,
            "strategy_version": strategy_version,
            "risk_version": risk_version,
            "execution_version": execution_version,
            "journal_schema_version": journal_schema_version,
            "replay_engine_version": replay_engine_version,
            "evidence_class": evidence_class.value,
            "inputs": [
                {
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "sha256": item.sha256,
                    "schema_version": item.schema_version,
                }
                for item in ordered_inputs
            ],
            "start_receive_ms": start_receive_ms,
            "end_receive_ms": end_receive_ms,
        }
        return cls(
            run_id=sha256_text(canonical_json(canonical)),
            manifest_schema_version=manifest_schema_version,
            code_version=code_version,
            python_version=python_version,
            config_sha256=config_sha256,
            strategy_version=strategy_version,
            risk_version=risk_version,
            execution_version=execution_version,
            journal_schema_version=journal_schema_version,
            replay_engine_version=replay_engine_version,
            evidence_class=evidence_class,
            inputs=ordered_inputs,
            start_receive_ms=start_receive_ms,
            end_receive_ms=end_receive_ms,
        )
