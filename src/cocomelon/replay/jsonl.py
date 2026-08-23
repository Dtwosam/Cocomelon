from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cocomelon.domain.journal import canonical_json
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayEvidence,
    ReplayInputFile,
    SourceCoordinate,
)

SUPPORTED_SCHEMA_VERSION = 1
SEGMENT_PATTERN = re.compile(r"^segment-(\d+)\.jsonl$")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class ReplayValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedSegment:
    path: Path
    input_file: ReplayInputFile
    evidence_class: EvidenceClass
    rows: tuple[ReplayEvidence, ...]


def _fail(message: str) -> ReplayValidationError:
    return ReplayValidationError(message)


def _reject_constant(value: str) -> object:
    raise _fail(f"non-standard JSON constant is forbidden: {value}")


def _require_mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _fail(f"{field} must be a JSON object")
    return value


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(f"{field} must be a non-empty string")
    return value


def _require_int(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(f"{field} must be an integer")
    if value < 0:
        raise _fail(f"{field} must be non-negative")
    return value


def _parse_market(value: object) -> MarketId:
    wire = _require_string(value, "market")
    if ":" in wire:
        dex = wire.split(":", 1)[0]
        try:
            return MarketId.from_wire_name(dex, wire)
        except ValueError as exc:
            raise _fail(f"invalid market: {wire}") from exc
    try:
        return MarketId.from_wire_name("", wire)
    except ValueError as exc:
        raise _fail(f"invalid market: {wire}") from exc


def _utc_epoch_ms(value: object) -> int:
    text = _require_string(value, "receive_time")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _fail("receive_time must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fail("receive_time must be timezone-aware")
    delta = parsed.astimezone(UTC) - EPOCH
    return (
        delta.days * 86_400_000
        + delta.seconds * 1_000
        + delta.microseconds // 1_000
    )


def _relative_path(path: Path, root: Path) -> str:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise _fail("segment path must be inside root") from exc
    return relative.as_posix()


def _segment_number(path: Path) -> int:
    match = SEGMENT_PATTERN.fullmatch(path.name)
    if match is None:
        raise _fail("segment filename must match segment-<number>.jsonl")
    value = int(match.group(1))
    if value <= 0:
        raise _fail("segment number must be positive")
    return value


def _normalized_event(
    raw: dict[str, object],
    *,
    evidence_class: EvidenceClass,
    coordinate: SourceCoordinate,
) -> ReplayEvidence:
    schema_version = _require_int(raw.get("schema_version"), "schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise _fail(f"unsupported schema_version: {schema_version}")
    source = _require_string(raw.get("source"), "source")
    kind = _require_string(raw.get("kind"), "kind")
    market = _parse_market(raw.get("market"))
    exchange_time_ms = _require_int(
        raw.get("exchange_time_ms"),
        "exchange_time_ms",
        optional=True,
    )
    receive_time_ms = _utc_epoch_ms(raw.get("receive_time"))
    event_key = _require_string(raw.get("event_key"), "event_key")
    payload = _require_mapping(raw.get("payload"), "payload")
    return ReplayEvidence(
        evidence_class=evidence_class,
        receive_time_ms=receive_time_ms,
        exchange_time_ms=exchange_time_ms,
        record_type="normalized_event",
        source=source,
        coordinate=coordinate,
        payload_json=canonical_json(payload),
        market=market,
        event_kind=kind,
        event_key=event_key,
    )


def _gap_event(
    raw: dict[str, object],
    *,
    evidence_class: EvidenceClass,
    coordinate: SourceCoordinate,
) -> ReplayEvidence:
    schema_version = _require_int(raw.get("schema_version"), "schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise _fail(f"unsupported schema_version: {schema_version}")
    source = _require_string(raw.get("source"), "source")
    stream_id = _require_string(raw.get("stream_id"), "stream_id")
    started_ms = _require_int(raw.get("started_ms"), "started_ms")
    assert started_ms is not None
    ended_ms = _require_int(raw.get("ended_ms"), "ended_ms", optional=True)
    if ended_ms is not None and ended_ms < started_ms:
        raise _fail("ended_ms must be >= started_ms")
    reason = _require_string(raw.get("reason"), "reason")
    payload = {
        "stream_id": stream_id,
        "started_ms": started_ms,
        "ended_ms": ended_ms,
        "reason": reason,
    }
    return ReplayEvidence(
        evidence_class=evidence_class,
        receive_time_ms=started_ms,
        exchange_time_ms=None,
        record_type="data_gap",
        source=source,
        coordinate=coordinate,
        payload_json=canonical_json(payload),
    )


def validate_jsonl_segment(
    path: str | Path,
    *,
    root: str | Path,
    evidence_class: EvidenceClass,
) -> ValidatedSegment:
    segment_path = Path(path)
    root_path = Path(root)
    if segment_path.suffix != ".jsonl":
        raise _fail("replay input must be a .jsonl segment")
    relative_path = _relative_path(segment_path, root_path)
    segment = _segment_number(segment_path)
    try:
        raw_bytes = segment_path.read_bytes()
    except OSError as exc:
        raise _fail(f"unable to read replay segment: {segment_path}") from exc
    if raw_bytes and not raw_bytes.endswith(b"\n"):
        raise _fail("replay segment must end with a final newline")

    sha256 = hashlib.sha256(raw_bytes).hexdigest()
    rows: list[ReplayEvidence] = []
    for line_number, raw_line in enumerate(raw_bytes.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            decoded = raw_line.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _fail(f"line {line_number} is not valid UTF-8") from exc
        try:
            parsed = json.loads(decoded, parse_constant=_reject_constant)
        except ReplayValidationError:
            raise
        except (json.JSONDecodeError, TypeError) as exc:
            raise _fail(f"invalid JSON at line {line_number}") from exc
        raw = _require_mapping(parsed, f"line {line_number}")
        record_type = _require_string(raw.get("record_type"), "record_type")
        coordinate = SourceCoordinate(relative_path, segment, line_number)
        if record_type == "normalized_event":
            rows.append(
                _normalized_event(
                    raw,
                    evidence_class=evidence_class,
                    coordinate=coordinate,
                )
            )
        elif record_type == "data_gap":
            rows.append(
                _gap_event(
                    raw,
                    evidence_class=evidence_class,
                    coordinate=coordinate,
                )
            )
        else:
            raise _fail(f"unsupported record_type: {record_type}")

    return ValidatedSegment(
        path=segment_path,
        input_file=ReplayInputFile(
            relative_path=relative_path,
            size_bytes=len(raw_bytes),
            sha256=sha256,
            schema_version=SUPPORTED_SCHEMA_VERSION,
        ),
        evidence_class=evidence_class,
        rows=tuple(rows),
    )
