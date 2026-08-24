from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from pathlib import Path

from cocomelon.domain.replay import ReplayManifest, ReplayRecord, SourceRecordKind
from cocomelon.replay.clock import canonical_record_order
from cocomelon.replay.compaction import (
    PARQUET_COLUMNS,
    CompactionManifest,
    ResearchDependencyError,
    _load_pyarrow,
    _logical_sha256,
    _row_sort_key,
)
from cocomelon.replay.source import CANDLE_CONTEXT_KINDS


class ParquetReplayError(ValueError):
    pass


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ParquetReplayError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field)


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParquetReplayError(f"{field} must be an integer")
    if value < 0:
        raise ParquetReplayError(f"{field} must be non-negative")
    return value


def _optional_int(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field)


def _source_identity(manifest: ReplayManifest) -> tuple[dict[str, object], ...]:
    return tuple(item.canonical_payload() for item in manifest.segments)


def _compaction_source_identity(
    manifest: CompactionManifest,
) -> tuple[dict[str, object], ...]:
    return tuple(item.canonical_payload() for item in manifest.source_segments)


def _replay_record(row: Mapping[str, object]) -> ReplayRecord:
    record_kind_raw = _require_string(row.get("record_kind"), "record_kind")
    try:
        record_kind = SourceRecordKind(record_kind_raw)
    except ValueError as exc:
        raise ParquetReplayError(f"unsupported record_kind: {record_kind_raw}") from exc
    return ReplayRecord(
        record_kind=record_kind,
        available_at_ms=_require_int(row.get("available_at_ms"), "available_at_ms"),
        source=_require_string(row.get("source"), "source"),
        schema_version=_require_int(row.get("schema_version"), "schema_version"),
        market=_optional_string(row.get("market"), "market"),
        exchange_time_ms=_optional_int(row.get("exchange_time_ms"), "exchange_time_ms"),
        event_key=_optional_string(row.get("event_key"), "event_key"),
        payload_json=_require_string(row.get("payload_json"), "payload_json"),
        event_kind=_optional_string(row.get("event_kind"), "event_kind"),
    )


class ParquetReplaySource:
    def __init__(
        self,
        dataset_root: str | Path,
        compaction_manifest: CompactionManifest,
    ) -> None:
        self.dataset_root = Path(dataset_root)
        self.compaction_manifest = compaction_manifest

    def _validate_manifest(self, replay_manifest: ReplayManifest) -> None:
        expected_dataset = self.compaction_manifest.dataset_id
        if replay_manifest.dataset_manifest_id != expected_dataset:
            raise ParquetReplayError(
                "replay dataset manifest does not match compaction dataset manifest"
            )
        if replay_manifest.evidence_class is not self.compaction_manifest.evidence_class:
            raise ParquetReplayError("replay evidence class does not match compacted dataset")
        if _source_identity(replay_manifest) != _compaction_source_identity(
            self.compaction_manifest
        ):
            raise ParquetReplayError("replay source segments do not match compacted source set")
        if self.dataset_root != self.compaction_manifest.dataset_root:
            raise ParquetReplayError("dataset root does not match compaction manifest")

    def _validated_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        _, parquet = _load_pyarrow()
        for output in self.compaction_manifest.output_files:
            path = self.dataset_root / output.relative_path
            if not path.is_file():
                raise ParquetReplayError(f"missing compacted output: {output.relative_path}")
            raw = path.read_bytes()
            actual_sha = hashlib.sha256(raw).hexdigest()
            if actual_sha != output.sha256:
                raise ParquetReplayError(
                    f"sha256 mismatch for {output.relative_path}: "
                    f"expected {output.sha256}, got {actual_sha}"
                )
            table = parquet.read_table(path)
            if tuple(table.column_names) != PARQUET_COLUMNS:
                raise ParquetReplayError("Parquet schema does not match Phase 8 compaction columns")
            if table.num_rows != output.row_count:
                raise ParquetReplayError(
                    f"row count mismatch for {output.relative_path}: "
                    f"expected {output.row_count}, got {table.num_rows}"
                )
            for raw_row in table.to_pylist():
                if not isinstance(raw_row, dict):
                    raise ParquetReplayError("Parquet row must decode to a mapping")
                rows.append({name: raw_row.get(name) for name in PARQUET_COLUMNS})
        if len(rows) != self.compaction_manifest.row_count:
            raise ParquetReplayError("Parquet dataset row count does not match compaction manifest")
        rows.sort(key=_row_sort_key)
        logical_sha = _logical_sha256(rows)
        if logical_sha != self.compaction_manifest.logical_sha256:
            raise ParquetReplayError(
                "Parquet logical digest does not match compaction manifest"
            )
        return rows

    def iter_records(self, manifest: ReplayManifest) -> Iterator[ReplayRecord]:
        self._validate_manifest(manifest)
        try:
            rows = self._validated_rows()
        except ResearchDependencyError:
            raise
        records = canonical_record_order(_replay_record(row) for row in rows)
        for record in records:
            if not manifest.start_ms <= record.available_at_ms <= manifest.end_ms:
                continue
            if (
                manifest.evidence_class.value == "candle_context"
                and record.record_kind is SourceRecordKind.NORMALIZED_EVENT
                and record.event_kind not in CANDLE_CONTEXT_KINDS
            ):
                continue
            yield record
