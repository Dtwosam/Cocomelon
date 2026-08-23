from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from urllib.parse import quote

from cocomelon.domain.stream import DataGap, StreamEvent

MANIFEST_SCHEMA_VERSION = 1
DEFAULT_MAX_RECORDS = 100_000
DEFAULT_MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _SegmentState:
    segment: int
    records: int
    bytes: int


class DurableRecorder:
    def __init__(
        self,
        root: str | Path,
        *,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")

        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_records = max_records
        self.max_bytes = max_bytes
        self.manifest_path = self.root / "manifest.json"
        self._states: dict[str, _SegmentState] = {}
        self._resume_partitions: set[str] = set()
        self._load_manifest()

    def append_event(self, event: StreamEvent) -> Path:
        receive_time = _format_datetime(event.receive_time)
        receive_date = event.receive_time.astimezone(UTC).date().isoformat()
        market_path = quote(event.market.canonical, safe="-_.")
        partition = (
            Path("events") / receive_date / event.kind.value / market_path
        ).as_posix()
        record: dict[str, object] = {
            "record_type": "normalized_event",
            "schema_version": event.schema_version,
            "source": event.source,
            "kind": event.kind.value,
            "market": event.market.canonical,
            "exchange_time_ms": event.exchange_time_ms,
            "receive_time": receive_time,
            "event_key": event.event_key,
            "payload": _json_value(event.payload),
        }
        return self._append(partition, record)

    def append_gap(self, gap: DataGap) -> Path:
        started_at = datetime.fromtimestamp(gap.started_ms / 1000, tz=UTC)
        partition = (Path("gaps") / started_at.date().isoformat()).as_posix()
        record: dict[str, object] = {
            "record_type": "data_gap",
            "schema_version": gap.schema_version,
            "source": gap.source,
            "stream_id": gap.stream_id,
            "started_ms": gap.started_ms,
            "ended_ms": gap.ended_ms,
            "reason": gap.reason,
        }
        return self._append(partition, record)

    def _append(self, partition: str, record: Mapping[str, object]) -> Path:
        encoded = _encode_json_line(record)
        base_state = self._state_for_write(partition, len(encoded))
        path = self._segment_path(partition, base_state.segment)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("ab") as handle:
            written = handle.write(encoded)
            if written != len(encoded):
                raise OSError(f"short recorder write: {written} of {len(encoded)} bytes")
            handle.flush()
            os.fsync(handle.fileno())

        self._states[partition] = _SegmentState(
            segment=base_state.segment,
            records=base_state.records + 1,
            bytes=base_state.bytes + len(encoded),
        )
        self._resume_partitions.discard(partition)
        self._write_manifest()
        return path

    def _state_for_write(self, partition: str, line_bytes: int) -> _SegmentState:
        current = self._states.get(partition)
        start_new = current is None
        if current is not None:
            current_path = self._segment_path(partition, current.segment)
            start_new = (
                partition in self._resume_partitions
                or current.records >= self.max_records
                or (current.records > 0 and current.bytes + line_bytes > self.max_bytes)
                or (current.records > 0 and not current_path.exists())
            )
            if not start_new:
                return current

        segment = 1 if current is None else current.segment + 1
        candidate = _SegmentState(segment=segment, records=0, bytes=0)
        while self._segment_path(partition, candidate.segment).exists():
            candidate = _SegmentState(segment=candidate.segment + 1, records=0, bytes=0)
        return candidate

    def _segment_path(self, partition: str, segment: int) -> Path:
        return self.root / partition / f"segment-{segment:06d}.jsonl"

    def _load_manifest(self) -> None:
        if not self.manifest_path.exists():
            return
        raw: object = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("recorder manifest must be a JSON object")
        if raw.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported recorder manifest schema_version")
        partitions = raw.get("partitions")
        if not isinstance(partitions, dict):
            raise ValueError("recorder manifest partitions must be an object")

        states: dict[str, _SegmentState] = {}
        for partition, value in partitions.items():
            if not isinstance(partition, str) or not isinstance(value, dict):
                raise ValueError("invalid recorder manifest partition entry")
            segment = _manifest_int(value.get("segment"), "segment", positive=True)
            records = _manifest_int(value.get("records"), "records", positive=False)
            byte_count = _manifest_int(value.get("bytes"), "bytes", positive=False)
            states[partition] = _SegmentState(segment, records, byte_count)

        self._states = states
        self._resume_partitions = set(states)

    def _write_manifest(self) -> None:
        payload: dict[str, object] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "partitions": {
                partition: {
                    "segment": state.segment,
                    "records": state.records,
                    "bytes": state.bytes,
                }
                for partition, state in sorted(self._states.items())
            },
        }
        encoded = (
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
        temporary = self.root / "manifest.json.tmp"
        with temporary.open("wb") as handle:
            written = handle.write(encoded)
            if written != len(encoded):
                raise OSError(f"short manifest write: {written} of {len(encoded)} bytes")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.manifest_path)


def _manifest_int(value: object, field: str, *, positive: bool) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"manifest {field} must be an integer")
    minimum = 1 if positive else 0
    if value < minimum:
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"manifest {field} must be {qualifier}")
    return value


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON mapping keys must be strings")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported recorder value type: {type(value).__name__}")


def _encode_json_line(record: Mapping[str, object]) -> bytes:
    normalized = _json_value(record)
    return (
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
