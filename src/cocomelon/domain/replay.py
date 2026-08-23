from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EvidenceClass(StrEnum):
    CANDLE_CONTEXT = "candle_context"
    MICROSTRUCTURE = "microstructure"


class SourceRecordKind(StrEnum):
    NORMALIZED_EVENT = "normalized_event"
    DATA_GAP = "data_gap"


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise ValueError(f"{field} must be a 64-character sha256 hex digest")


def _canonical_digest(payload: dict[str, object], *, length: int = 64) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


@dataclass(frozen=True, slots=True)
class SourceSegment:
    relative_path: str
    partition: str
    sha256: str
    byte_count: int
    row_count: int
    schema_version: int
    first_available_at_ms: int
    last_available_at_ms: int

    def __post_init__(self) -> None:
        _require_nonempty(self.relative_path, "relative_path")
        _require_nonempty(self.partition, "partition")
        _require_sha256(self.sha256, "sha256")
        if self.byte_count < 0:
            raise ValueError("byte_count must be non-negative")
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.first_available_at_ms < 0:
            raise ValueError("first_available_at_ms must be non-negative")
        if self.last_available_at_ms < self.first_available_at_ms:
            raise ValueError("last_available_at_ms must be >= first_available_at_ms")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "partition": self.partition,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "row_count": self.row_count,
            "schema_version": self.schema_version,
            "first_available_at_ms": self.first_available_at_ms,
            "last_available_at_ms": self.last_available_at_ms,
        }


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    record_kind: SourceRecordKind
    available_at_ms: int
    source: str
    schema_version: int
    market: str | None
    exchange_time_ms: int | None
    event_key: str | None
    payload_json: str
    event_kind: str | None = None

    def __post_init__(self) -> None:
        if self.available_at_ms < 0:
            raise ValueError("available_at_ms must be non-negative")
        _require_nonempty(self.source, "source")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.market is not None:
            _require_nonempty(self.market, "market")
        if self.exchange_time_ms is not None and self.exchange_time_ms < 0:
            raise ValueError("exchange_time_ms must be non-negative")
        if self.event_key is not None:
            _require_nonempty(self.event_key, "event_key")
        if self.event_kind is not None:
            _require_nonempty(self.event_kind, "event_kind")
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ValueError("payload_json must be valid JSON") from exc
        canonical = json.dumps(
            parsed,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        object.__setattr__(self, "payload_json", canonical)

    @property
    def payload(self) -> Any:
        return json.loads(self.payload_json)

    @property
    def sort_key(self) -> tuple[int, str, str, str]:
        return (
            self.available_at_ms,
            self.event_kind or self.record_kind.value,
            self.market or "",
            self.event_key or self.payload_json,
        )


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    evidence_class: EvidenceClass
    start_ms: int
    end_ms: int
    segments: tuple[SourceSegment, ...]
    gap_refs: tuple[str, ...]
    code_revision: str
    config_digest: str
    feature_version: str
    strategy_version: str
    risk_version: str
    execution_config_version: str | None
    fee_schedule_id: str | None
    replay_engine_version: str
    dataset_manifest_id: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        if not self.segments:
            raise ValueError("segments must not be empty")
        object.__setattr__(
            self,
            "segments",
            tuple(sorted(self.segments, key=lambda item: item.relative_path)),
        )
        normalized_gaps = tuple(sorted(set(self.gap_refs)))
        if any(not value.strip() for value in normalized_gaps):
            raise ValueError("gap_refs values must not be empty")
        object.__setattr__(self, "gap_refs", normalized_gaps)
        for field in (
            "code_revision",
            "feature_version",
            "strategy_version",
            "risk_version",
            "replay_engine_version",
        ):
            _require_nonempty(getattr(self, field), field)
        _require_sha256(self.config_digest, "config_digest")
        for field in ("execution_config_version", "fee_schedule_id", "dataset_manifest_id"):
            value = getattr(self, field)
            if value is not None:
                _require_nonempty(value, field)
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def manifest_id(self) -> str:
        return _canonical_digest(
            {
                "evidence_class": self.evidence_class.value,
                "start_ms": self.start_ms,
                "end_ms": self.end_ms,
                "segments": tuple(item.canonical_payload() for item in self.segments),
                "gap_refs": self.gap_refs,
                "code_revision": self.code_revision,
                "config_digest": self.config_digest,
                "feature_version": self.feature_version,
                "strategy_version": self.strategy_version,
                "risk_version": self.risk_version,
                "execution_config_version": self.execution_config_version,
                "fee_schedule_id": self.fee_schedule_id,
                "replay_engine_version": self.replay_engine_version,
                "dataset_manifest_id": self.dataset_manifest_id,
                "schema_version": self.schema_version,
            },
            length=24,
        )


@dataclass(frozen=True, slots=True)
class ReplayResult:
    manifest_id: str
    run_id: str
    evidence_class: EvidenceClass
    start_ms: int
    end_ms: int
    processed_events: int
    processed_gaps: int
    strategy_decisions: int
    risk_approvals: int
    risk_rejections: int
    execution_attempts: int
    fills: int
    opened_positions: int
    closed_positions: int
    journal_observations: int
    closed_trade_ids: tuple[str, ...]
    final_account_state_id: str
    data_complete: bool
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in ("manifest_id", "run_id", "final_account_state_id"):
            _require_nonempty(getattr(self, field), field)
        if self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        for field in (
            "processed_events",
            "processed_gaps",
            "strategy_decisions",
            "risk_approvals",
            "risk_rejections",
            "execution_attempts",
            "fills",
            "opened_positions",
            "closed_positions",
            "journal_observations",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        normalized_trades = tuple(sorted(set(self.closed_trade_ids)))
        if any(not value.strip() for value in normalized_trades):
            raise ValueError("closed_trade_ids values must not be empty")
        object.__setattr__(self, "closed_trade_ids", normalized_trades)
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def result_digest(self) -> str:
        return _canonical_digest(
            {
                "manifest_id": self.manifest_id,
                "run_id": self.run_id,
                "evidence_class": self.evidence_class.value,
                "start_ms": self.start_ms,
                "end_ms": self.end_ms,
                "processed_events": self.processed_events,
                "processed_gaps": self.processed_gaps,
                "strategy_decisions": self.strategy_decisions,
                "risk_approvals": self.risk_approvals,
                "risk_rejections": self.risk_rejections,
                "execution_attempts": self.execution_attempts,
                "fills": self.fills,
                "opened_positions": self.opened_positions,
                "closed_positions": self.closed_positions,
                "journal_observations": self.journal_observations,
                "closed_trade_ids": self.closed_trade_ids,
                "final_account_state_id": self.final_account_state_id,
                "data_complete": self.data_complete,
                "schema_version": self.schema_version,
            }
        )
