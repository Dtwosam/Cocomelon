from __future__ import annotations

import hashlib
import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cocomelon.domain.replay import EvidenceClass, ReplayRecord, SourceSegment
from cocomelon.replay.source import RecordingValidationError, _read_segment

COMPACTION_SCHEMA_VERSION = 1
COMPACTION_VERSION = "phase8-parquet-v1"
PARQUET_COLUMNS = (
    "record_kind",
    "available_at_ms",
    "source",
    "schema_version",
    "market",
    "exchange_time_ms",
    "event_key",
    "event_kind",
    "payload_json",
    "source_relative_path",
    "source_partition",
    "source_sha256",
    "source_line_number",
)


class ResearchDependencyError(RuntimeError):
    pass


def _require_sha256(value: str, field: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field} must be a lowercase 64-character sha256 hex digest")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_relative_path(value: str, field: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or path.as_posix() != value
    ):
        raise ValueError(f"{field} must be a safe canonical relative POSIX path")


@dataclass(frozen=True, slots=True)
class CompactedFile:
    relative_path: str
    sha256: str
    byte_count: int
    row_count: int

    def __post_init__(self) -> None:
        _safe_relative_path(self.relative_path, "relative_path")
        _require_sha256(self.sha256, "sha256")
        if self.byte_count <= 0:
            raise ValueError("byte_count must be positive")
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
            "row_count": self.row_count,
        }


@dataclass(frozen=True, slots=True)
class CompactionManifest:
    dataset_root: Path
    evidence_class: EvidenceClass
    source_segments: tuple[SourceSegment, ...]
    output_files: tuple[CompactedFile, ...]
    row_count: int
    logical_sha256: str
    converter_version: str = COMPACTION_VERSION
    schema_version: int = COMPACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.source_segments:
            raise ValueError("source_segments must not be empty")
        if not self.output_files:
            raise ValueError("output_files must not be empty")
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")
        _require_sha256(self.logical_sha256, "logical_sha256")
        if not self.converter_version.strip():
            raise ValueError("converter_version must not be empty")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        object.__setattr__(
            self,
            "source_segments",
            tuple(sorted(self.source_segments, key=lambda item: item.relative_path)),
        )
        object.__setattr__(
            self,
            "output_files",
            tuple(sorted(self.output_files, key=lambda item: item.relative_path)),
        )
        if sum(item.row_count for item in self.output_files) != self.row_count:
            raise ValueError("output row counts must reconcile to row_count")

    @property
    def dataset_id(self) -> str:
        return _canonical_sha256(
            {
                "evidence_class": self.evidence_class.value,
                "source_segments": tuple(
                    item.canonical_payload() for item in self.source_segments
                ),
                "row_count": self.row_count,
                "logical_sha256": self.logical_sha256,
                "columns": PARQUET_COLUMNS,
                "converter_version": self.converter_version,
                "schema_version": self.schema_version,
            }
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "evidence_class": self.evidence_class.value,
            "source_segments": tuple(item.canonical_payload() for item in self.source_segments),
            "output_files": tuple(item.canonical_payload() for item in self.output_files),
            "row_count": self.row_count,
            "logical_sha256": self.logical_sha256,
            "columns": PARQUET_COLUMNS,
            "converter_version": self.converter_version,
            "schema_version": self.schema_version,
        }


def _load_pyarrow() -> tuple[Any, Any]:
    try:
        pyarrow = importlib.import_module("pyarrow")
        parquet = importlib.import_module("pyarrow.parquet")
    except ImportError as exc:
        raise ResearchDependencyError(
            'offline Parquet compaction requires the research extra: pip install -e ".[research]"'
        ) from exc
    return pyarrow, parquet


def _row_payload(
    record: ReplayRecord,
    *,
    segment: SourceSegment,
    line_number: int,
) -> dict[str, object]:
    return {
        "record_kind": record.record_kind.value,
        "available_at_ms": record.available_at_ms,
        "source": record.source,
        "schema_version": record.schema_version,
        "market": record.market,
        "exchange_time_ms": record.exchange_time_ms,
        "event_key": record.event_key,
        "event_kind": record.event_kind,
        "payload_json": record.payload_json,
        "source_relative_path": segment.relative_path,
        "source_partition": segment.partition,
        "source_sha256": segment.sha256,
        "source_line_number": line_number,
    }


def _row_sort_key(row: dict[str, object]) -> tuple[int, str, str, str, str, int]:
    available = row["available_at_ms"]
    line_number = row["source_line_number"]
    if not isinstance(available, int) or not isinstance(line_number, int):
        raise TypeError("compaction row timestamps and line numbers must be integers")
    return (
        available,
        str(row["event_kind"] or row["record_kind"]),
        str(row["market"] or ""),
        str(row["event_key"] or row["payload_json"]),
        str(row["source_relative_path"]),
        line_number,
    )


def _validated_rows(root: Path, segments: tuple[SourceSegment, ...]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for segment in sorted(segments, key=lambda item: item.relative_path):
        path = root / segment.relative_path
        if not path.is_file():
            raise RecordingValidationError(
                f"missing validated source segment: {segment.relative_path}"
            )
        raw = path.read_bytes()
        actual_sha = hashlib.sha256(raw).hexdigest()
        if actual_sha != segment.sha256:
            raise RecordingValidationError(
                f"sha256 mismatch for {segment.relative_path}: "
                f"expected {segment.sha256}, got {actual_sha}"
            )
        records = _read_segment(path)
        if len(records) != segment.row_count:
            raise RecordingValidationError(
                f"row count mismatch for {segment.relative_path}: "
                f"expected {segment.row_count}, got {len(records)}"
            )
        for line_number, record in enumerate(records, start=1):
            rows.append(_row_payload(record, segment=segment, line_number=line_number))
    rows.sort(key=_row_sort_key)
    return rows


def _logical_sha256(rows: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(_canonical_json(row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_manifest(path: Path, manifest: CompactionManifest) -> None:
    encoded = (_canonical_json(manifest.canonical_payload()) + "\n").encode("utf-8")
    temporary = path.with_suffix(".json.tmp")
    with temporary.open("wb") as handle:
        written = handle.write(encoded)
        if written != len(encoded):
            raise OSError(f"short compaction manifest write: {written} of {len(encoded)} bytes")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def compact_recording(
    root: str | Path,
    output_root: str | Path,
    segments: tuple[SourceSegment, ...],
    *,
    evidence_class: EvidenceClass = EvidenceClass.MICROSTRUCTURE,
) -> CompactionManifest:
    if not segments:
        raise ValueError("segments must not be empty")
    source_root = Path(root)
    if not source_root.is_dir():
        raise RecordingValidationError("recording root must be an existing directory")

    rows = _validated_rows(source_root, segments)
    if not rows:
        raise RecordingValidationError("validated source segments contain no records")
    logical_sha = _logical_sha256(rows)
    canonical_segments = tuple(sorted(segments, key=lambda item: item.relative_path))
    semantic_id = _canonical_sha256(
        {
            "evidence_class": evidence_class.value,
            "source_segments": tuple(item.canonical_payload() for item in canonical_segments),
            "row_count": len(rows),
            "logical_sha256": logical_sha,
            "columns": PARQUET_COLUMNS,
            "converter_version": COMPACTION_VERSION,
            "schema_version": COMPACTION_SCHEMA_VERSION,
        }
    )

    pyarrow, parquet = _load_pyarrow()
    dataset_root = Path(output_root) / "v1" / semantic_id
    dataset_root.mkdir(parents=True, exist_ok=True)
    output_path = dataset_root / "records.parquet"
    temporary = dataset_root / "records.parquet.tmp"

    columns = {name: [row[name] for row in rows] for name in PARQUET_COLUMNS}
    table = pyarrow.table(columns)
    parquet.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
    )
    _fsync_file(temporary)
    os.replace(temporary, output_path)
    _fsync_file(output_path)

    output_bytes = output_path.read_bytes()
    output_file = CompactedFile(
        relative_path="records.parquet",
        sha256=hashlib.sha256(output_bytes).hexdigest(),
        byte_count=len(output_bytes),
        row_count=len(rows),
    )
    manifest = CompactionManifest(
        dataset_root=dataset_root,
        evidence_class=evidence_class,
        source_segments=canonical_segments,
        output_files=(output_file,),
        row_count=len(rows),
        logical_sha256=logical_sha,
    )
    if manifest.dataset_id != semantic_id:
        raise RuntimeError("compaction semantic identity changed during write")
    _write_manifest(dataset_root / "manifest.json", manifest)
    return manifest
