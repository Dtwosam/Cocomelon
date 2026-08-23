from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
    SourceSegment,
)
from cocomelon.domain.stream import StreamKind

SUPPORTED_RECORDER_SCHEMA_VERSIONS = frozenset({1})
CANDLE_CONTEXT_KINDS = frozenset(
    {
        StreamKind.ALL_MIDS.value,
        StreamKind.ACTIVE_ASSET_CTX.value,
        StreamKind.CANDLE.value,
    }
)


class RecordingValidationError(ValueError):
    pass


class ReplaySource(Protocol):
    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]: ...


def _json_loads(raw: str) -> object:
    def reject_constant(value: str) -> object:
        raise RecordingValidationError(f"non-finite JSON constant: {value}")

    try:
        return json.loads(raw, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise RecordingValidationError(f"invalid JSON: {exc.msg}") from exc


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise RecordingValidationError(f"{field} must be an object")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordingValidationError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecordingValidationError(f"{field} must be an integer")
    if nonnegative and value < 0:
        raise RecordingValidationError(f"{field} must be non-negative")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _timestamp_ms(value: object, field: str) -> int:
    raw = _string(value, field)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordingValidationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecordingValidationError(f"{field} must be timezone-aware")
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _segment_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path
                for path in root.rglob("segment-*.jsonl")
                if path.is_file()
                and (path.relative_to(root).parts[0] in {"events", "gaps"})
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def _validate_partition(
    root: Path,
    path: Path,
    row: Mapping[str, object],
    available_at_ms: int,
) -> str:
    relative = path.relative_to(root)
    parts = relative.parts
    record_type = _string(row.get("record_type"), "record_type")
    observed_date = datetime.fromtimestamp(available_at_ms / 1000, tz=UTC).date().isoformat()

    if record_type == SourceRecordKind.NORMALIZED_EVENT.value:
        if len(parts) != 5 or parts[0] != "events":
            raise RecordingValidationError("event row partition path is invalid")
        receive_date, event_kind, market_path = parts[1], parts[2], parts[3]
        row_kind = _string(row.get("kind"), "kind")
        market = _string(row.get("market"), "market")
        expected_market_path = quote(market, safe="-_.")
        if (
            receive_date != observed_date
            or event_kind != row_kind
            or market_path != expected_market_path
        ):
            raise RecordingValidationError("event row does not match partition identity")
        return relative.parent.as_posix()

    if record_type == SourceRecordKind.DATA_GAP.value:
        if len(parts) != 3 or parts[0] != "gaps" or parts[1] != observed_date:
            raise RecordingValidationError("data gap row does not match partition identity")
        return relative.parent.as_posix()

    raise RecordingValidationError(f"unsupported record_type: {record_type}")


def _record_from_row(row: Mapping[str, object]) -> ReplayRecord:
    record_type = _string(row.get("record_type"), "record_type")
    schema_version = _integer(row.get("schema_version"), "schema_version")
    if schema_version not in SUPPORTED_RECORDER_SCHEMA_VERSIONS:
        raise RecordingValidationError(f"unsupported schema_version: {schema_version}")
    source = _string(row.get("source"), "source")

    if record_type == SourceRecordKind.NORMALIZED_EVENT.value:
        available_at_ms = _timestamp_ms(row.get("receive_time"), "receive_time")
        market = _string(row.get("market"), "market")
        event_kind = _string(row.get("kind"), "kind")
        event_key = _string(row.get("event_key"), "event_key")
        payload = _mapping(row.get("payload"), "payload")
        return ReplayRecord(
            record_kind=SourceRecordKind.NORMALIZED_EVENT,
            available_at_ms=available_at_ms,
            source=source,
            schema_version=schema_version,
            market=market,
            exchange_time_ms=_optional_integer(row.get("exchange_time_ms"), "exchange_time_ms"),
            event_key=event_key,
            payload_json=_canonical_json(payload),
            event_kind=event_kind,
        )

    if record_type == SourceRecordKind.DATA_GAP.value:
        started_ms = _integer(row.get("started_ms"), "started_ms")
        ended_ms = _optional_integer(row.get("ended_ms"), "ended_ms")
        if ended_ms is not None and ended_ms < started_ms:
            raise RecordingValidationError("ended_ms must be >= started_ms")
        stream_id = _string(row.get("stream_id"), "stream_id")
        reason = _string(row.get("reason"), "reason")
        payload = {
            "stream_id": stream_id,
            "started_ms": started_ms,
            "ended_ms": ended_ms,
            "reason": reason,
        }
        return ReplayRecord(
            record_kind=SourceRecordKind.DATA_GAP,
            available_at_ms=started_ms,
            source=source,
            schema_version=schema_version,
            market=None,
            exchange_time_ms=None,
            event_key=f"gap:{stream_id}:{started_ms}:{ended_ms}:{reason}",
            payload_json=_canonical_json(payload),
            event_kind=None,
        )

    raise RecordingValidationError(f"unsupported record_type: {record_type}")


def _read_segment(path: Path) -> tuple[ReplayRecord, ...]:
    raw = path.read_bytes()
    if not raw:
        raise RecordingValidationError(f"empty JSONL segment: {path}")
    if not raw.endswith(b"\n"):
        raise RecordingValidationError(f"JSONL segment must end with newline: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecordingValidationError(f"segment is not valid UTF-8: {path}") from exc
    records: list[ReplayRecord] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise RecordingValidationError(f"blank JSONL row at {path}:{line_number}")
        row = _mapping(_json_loads(line), "record")
        try:
            records.append(_record_from_row(row))
        except RecordingValidationError as exc:
            raise RecordingValidationError(f"{path}:{line_number}: {exc}") from exc
    return tuple(records)


def validate_recording(root: str | Path) -> tuple[SourceSegment, ...]:
    base = Path(root)
    if not base.exists() or not base.is_dir():
        raise RecordingValidationError("recording root must be an existing directory")
    paths = _segment_files(base)
    if not paths:
        raise RecordingValidationError("recording contains no JSONL segments")

    seen_event_keys: set[str] = set()
    segments: list[SourceSegment] = []
    for path in paths:
        raw = path.read_bytes()
        records = _read_segment(path)
        partition: str | None = None
        schema_versions: set[int] = set()
        for record in records:
            if record.record_kind is SourceRecordKind.NORMALIZED_EVENT:
                assert record.event_key is not None
                if record.event_key in seen_event_keys:
                    raise RecordingValidationError(f"duplicate event_key: {record.event_key}")
                seen_event_keys.add(record.event_key)
            row_partition = _validate_partition(
                base,
                path,
                _mapping(_json_loads(raw.decode("utf-8").splitlines()[records.index(record)]), "record"),
                record.available_at_ms,
            )
            if partition is None:
                partition = row_partition
            elif partition != row_partition:
                raise RecordingValidationError("segment contains mixed partition identities")
            schema_versions.add(record.schema_version)
        if len(schema_versions) != 1:
            raise RecordingValidationError("segment contains mixed schema versions")
        assert partition is not None
        available = [record.available_at_ms for record in records]
        segments.append(
            SourceSegment(
                relative_path=path.relative_to(base).as_posix(),
                partition=partition,
                sha256=hashlib.sha256(raw).hexdigest(),
                byte_count=len(raw),
                row_count=len(records),
                schema_version=next(iter(schema_versions)),
                first_available_at_ms=min(available),
                last_available_at_ms=max(available),
            )
        )
    return tuple(segments)


class JsonlReplaySource:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]:
        for segment in manifest.segments:
            path = self.root / segment.relative_path
            if not path.is_file():
                raise RecordingValidationError(f"missing manifest segment: {segment.relative_path}")
            raw = path.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            if actual != segment.sha256:
                raise RecordingValidationError(
                    f"sha256 mismatch for {segment.relative_path}: expected {segment.sha256}, got {actual}"
                )
            records = _read_segment(path)
            if len(records) != segment.row_count:
                raise RecordingValidationError(f"row count mismatch for {segment.relative_path}")
            for record in records:
                if record.available_at_ms < manifest.start_ms or record.available_at_ms > manifest.end_ms:
                    continue
                if (
                    manifest.evidence_class is EvidenceClass.CANDLE_CONTEXT
                    and record.record_kind is SourceRecordKind.NORMALIZED_EVENT
                    and record.event_kind not in CANDLE_CONTEXT_KINDS
                ):
                    continue
                yield record
