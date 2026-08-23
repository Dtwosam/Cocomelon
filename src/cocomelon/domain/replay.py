from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import PurePosixPath


class EvidenceClass(StrEnum):
    CANDLE_CONTEXT = "candle_context"
    MICROSTRUCTURE = "microstructure"


class JournalRecordType(StrEnum):
    SCANNER_SNAPSHOT = "scanner_snapshot"
    STRATEGY_DECISION = "strategy_decision"
    RISK_DECISION = "risk_decision"
    ORDER_PLAN = "order_plan"
    EXECUTION_ATTEMPT = "execution_attempt"
    FILL = "fill"
    POSITION_OPEN = "position_open"
    POSITION_ACTION = "position_action"
    POSITION_CLOSE = "position_close"
    FUNDING_ACCRUAL = "funding_accrual"
    ACCOUNT_SNAPSHOT = "account_snapshot"
    DATA_GAP = "data_gap"
    REPLAY_RESULT = "replay_result"


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_nonnegative(value: int, field: str) -> None:
    if value < 0:
        raise ValueError(f"{field} must be non-negative")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON mapping keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("float values must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class InputArtifact:
    relative_path: str
    sha256: str
    byte_size: int
    partition_id: str

    def __post_init__(self) -> None:
        _require_nonempty(self.relative_path, "relative_path")
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("relative_path must be a safe relative POSIX path")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ValueError("sha256 must be a lowercase 64-character hex digest")
        _require_nonnegative(self.byte_size, "byte_size")
        _require_nonempty(self.partition_id, "partition_id")

    def logical_content(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
            "partition_id": self.partition_id,
        }


@dataclass(frozen=True, slots=True)
class ReplayManifest:
    evidence_class: EvidenceClass
    inputs: tuple[InputArtifact, ...]
    start_receive_ms: int
    end_receive_ms: int
    code_version: str
    config_version: str
    strategy_version: str
    risk_version: str
    execution_version: str
    recorder_schema_versions: tuple[int, ...]
    manifest_schema_version: int = 1
    tie_break_policy_version: str = "phase8-v1"
    compaction_dataset_version: str | None = None

    def __post_init__(self) -> None:
        _require_nonnegative(self.start_receive_ms, "start_receive_ms")
        _require_nonnegative(self.end_receive_ms, "end_receive_ms")
        if self.end_receive_ms < self.start_receive_ms:
            raise ValueError("end_receive_ms must be >= start_receive_ms")
        for field, value in (
            ("code_version", self.code_version),
            ("config_version", self.config_version),
            ("strategy_version", self.strategy_version),
            ("risk_version", self.risk_version),
            ("execution_version", self.execution_version),
            ("tie_break_policy_version", self.tie_break_policy_version),
        ):
            _require_nonempty(value, field)
        if self.manifest_schema_version <= 0:
            raise ValueError("manifest_schema_version must be positive")
        if not self.recorder_schema_versions:
            raise ValueError("recorder_schema_versions must not be empty")
        if any(item <= 0 for item in self.recorder_schema_versions):
            raise ValueError("recorder_schema_versions must be positive")
        normalized_inputs = tuple(sorted(self.inputs, key=lambda item: item.relative_path))
        if len({item.relative_path for item in normalized_inputs}) != len(normalized_inputs):
            raise ValueError("manifest inputs must have unique relative paths")
        object.__setattr__(self, "inputs", normalized_inputs)
        object.__setattr__(
            self,
            "recorder_schema_versions",
            tuple(sorted(set(self.recorder_schema_versions))),
        )

    def logical_content(self) -> dict[str, object]:
        return {
            "manifest_schema_version": self.manifest_schema_version,
            "evidence_class": self.evidence_class,
            "inputs": [item.logical_content() for item in self.inputs],
            "start_receive_ms": self.start_receive_ms,
            "end_receive_ms": self.end_receive_ms,
            "code_version": self.code_version,
            "config_version": self.config_version,
            "strategy_version": self.strategy_version,
            "risk_version": self.risk_version,
            "execution_version": self.execution_version,
            "recorder_schema_versions": self.recorder_schema_versions,
            "tie_break_policy_version": self.tie_break_policy_version,
            "compaction_dataset_version": self.compaction_dataset_version,
        }

    @property
    def replay_id(self) -> str:
        return sha256_hex(self.logical_content())


@dataclass(frozen=True, slots=True)
class JournalRecord:
    record_type: JournalRecordType
    occurred_at_ms: int
    recorded_at_ms: int
    code_version: str
    config_version: str
    payload: Mapping[str, object]
    market: str | None = None
    decision_id: str | None = None
    risk_decision_id: str | None = None
    plan_id: str | None = None
    attempt_id: str | None = None
    fill_id: str | None = None
    position_id: str | None = None
    funding_record_id: str | None = None
    replay_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonnegative(self.occurred_at_ms, "occurred_at_ms")
        _require_nonnegative(self.recorded_at_ms, "recorded_at_ms")
        _require_nonempty(self.code_version, "code_version")
        _require_nonempty(self.config_version, "config_version")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for field, value in (
            ("market", self.market),
            ("decision_id", self.decision_id),
            ("risk_decision_id", self.risk_decision_id),
            ("plan_id", self.plan_id),
            ("attempt_id", self.attempt_id),
            ("fill_id", self.fill_id),
            ("position_id", self.position_id),
            ("funding_record_id", self.funding_record_id),
            ("replay_id", self.replay_id),
        ):
            if value is not None:
                _require_nonempty(value, field)
        canonical_json_bytes(self.payload)

    def logical_content(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_type": self.record_type,
            "occurred_at_ms": self.occurred_at_ms,
            "market": self.market,
            "decision_id": self.decision_id,
            "risk_decision_id": self.risk_decision_id,
            "plan_id": self.plan_id,
            "attempt_id": self.attempt_id,
            "fill_id": self.fill_id,
            "position_id": self.position_id,
            "funding_record_id": self.funding_record_id,
            "replay_id": self.replay_id,
            "code_version": self.code_version,
            "config_version": self.config_version,
            "payload": self.payload,
        }

    @property
    def journal_id(self) -> str:
        return sha256_hex(self.logical_content())


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    availability_ms: int
    kind: str
    source_key: str
    input_path: str
    line_number: int
    payload: Mapping[str, object]
    market: str | None = None
    exchange_time_ms: int | None = None

    def __post_init__(self) -> None:
        _require_nonnegative(self.availability_ms, "availability_ms")
        _require_nonnegative(self.line_number, "line_number")
        if self.exchange_time_ms is not None:
            _require_nonnegative(self.exchange_time_ms, "exchange_time_ms")
        _require_nonempty(self.kind, "kind")
        _require_nonempty(self.source_key, "source_key")
        _require_nonempty(self.input_path, "input_path")
        if self.market is not None:
            _require_nonempty(self.market, "market")
        canonical_json_bytes(self.payload)


@dataclass(frozen=True, slots=True)
class TradeAnalytics:
    market: str
    direction: str
    position_id: str
    strategy_decision_id: str
    risk_decision_id: str
    entry_timestamp_ms: int
    exit_timestamp_ms: int
    entry_vwap: Decimal
    exit_vwap: Decimal
    gross_realized_pnl: Decimal
    fees: Decimal
    funding: Decimal
    slippage_attribution: Decimal
    net_pnl: Decimal
    approved_risk_amount: Decimal
    net_r: Decimal
    mfe_currency: Decimal | None
    mae_currency: Decimal | None
    mfe_r: Decimal | None
    mae_r: Decimal | None
    exit_reason: str
    reason_codes: tuple[str, ...]
    evidence_class: EvidenceClass
    replay_id: str
    metric_source: str | None = None
    metric_unknown_reason: str | None = None

    def __post_init__(self) -> None:
        for text_field, text_value in (
            ("market", self.market),
            ("direction", self.direction),
            ("position_id", self.position_id),
            ("strategy_decision_id", self.strategy_decision_id),
            ("risk_decision_id", self.risk_decision_id),
            ("exit_reason", self.exit_reason),
            ("replay_id", self.replay_id),
        ):
            _require_nonempty(text_value, text_field)
        _require_nonnegative(self.entry_timestamp_ms, "entry_timestamp_ms")
        _require_nonnegative(self.exit_timestamp_ms, "exit_timestamp_ms")
        if self.exit_timestamp_ms < self.entry_timestamp_ms:
            raise ValueError("exit_timestamp_ms must be >= entry_timestamp_ms")
        decimals: Sequence[tuple[str, Decimal | None]] = (
            ("entry_vwap", self.entry_vwap),
            ("exit_vwap", self.exit_vwap),
            ("gross_realized_pnl", self.gross_realized_pnl),
            ("fees", self.fees),
            ("funding", self.funding),
            ("slippage_attribution", self.slippage_attribution),
            ("net_pnl", self.net_pnl),
            ("approved_risk_amount", self.approved_risk_amount),
            ("net_r", self.net_r),
            ("mfe_currency", self.mfe_currency),
            ("mae_currency", self.mae_currency),
            ("mfe_r", self.mfe_r),
            ("mae_r", self.mae_r),
        )
        for decimal_field, decimal_value in decimals:
            if decimal_value is not None and not decimal_value.is_finite():
                raise ValueError(f"{decimal_field} must be finite")
        if self.entry_vwap <= 0 or self.exit_vwap <= 0:
            raise ValueError("entry_vwap and exit_vwap must be positive")
        if self.fees < 0:
            raise ValueError("fees must be non-negative")
        if self.approved_risk_amount <= 0:
            raise ValueError("approved_risk_amount must be positive")

    @property
    def holding_time_ms(self) -> int:
        return self.exit_timestamp_ms - self.entry_timestamp_ms
