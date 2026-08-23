import importlib
import json
import sys
from pathlib import Path

import pytest

from cocomelon.domain.replay import EvidenceClass
from cocomelon.replay.jsonl import validate_jsonl_segment
from cocomelon.replay.compact import (
    ColumnarDependencyError,
    compact_validated_segments,
)


def write_event(path: Path, *, event_key: str, receive_time: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "record_type": "normalized_event",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "kind": "trade",
        "market": "SOL",
        "exchange_time_ms": 1_000,
        "receive_time": receive_time,
        "event_key": event_key,
        "payload": {"price": "100", "size": "1"},
    }
    path.write_text(json.dumps(row, separators=(",", ":")) + "\n", encoding="utf-8")


def validated(tmp_path: Path):
    root = tmp_path / "recordings"
    path = root / "events/2026-08-23/trade/SOL/segment-000001.jsonl"
    write_event(path, event_key="trade:1", receive_time="2026-08-23T00:00:01Z")
    return validate_jsonl_segment(
        path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )


def test_importing_compactor_does_not_eagerly_import_polars() -> None:
    sys.modules.pop("polars", None)
    module = importlib.import_module("cocomelon.replay.compact")

    assert module is not None
    assert "polars" not in sys.modules


def test_compaction_surfaces_clear_optional_dependency_error(tmp_path: Path, monkeypatch) -> None:
    segment = validated(tmp_path)
    compact = importlib.import_module("cocomelon.replay.compact")

    def missing(name: str):
        if name == "polars":
            raise ImportError("missing polars")
        return importlib.import_module(name)

    monkeypatch.setattr(compact.importlib, "import_module", missing)

    with pytest.raises(ColumnarDependencyError, match="research"):
        compact_validated_segments([segment], tmp_path / "datasets")


def test_true_parquet_preserves_logical_rows_and_provenance(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    segment = validated(tmp_path)

    manifest = compact_validated_segments([segment], tmp_path / "datasets")

    assert len(manifest.dataset_id) == 64
    assert manifest.row_count == 1
    assert len(manifest.output_files) == 1
    output = tmp_path / "datasets" / "v1" / manifest.dataset_id / manifest.output_files[0].relative_path
    assert output.suffix == ".parquet"
    assert output.read_bytes()[:4] == b"PAR1"
    frame = pl.read_parquet(output)
    assert frame.height == 1
    row = frame.row(0, named=True)
    assert row["source_relative_path"] == segment.input_file.relative_path
    assert row["source_segment"] == 1
    assert row["source_line_number"] == 1
    assert row["source_sha256"] == segment.input_file.sha256
    assert row["event_kind"] == "trade"
    assert row["market"] == "SOL"
    assert row["payload_json"] == '{"price":"100","size":"1"}'


def test_dataset_identity_is_stable_across_input_enumeration_order(tmp_path: Path) -> None:
    pl = pytest.importorskip("polars")
    del pl
    root = tmp_path / "recordings"
    first_path = root / "events/a/segment-000001.jsonl"
    second_path = root / "events/b/segment-000002.jsonl"
    write_event(first_path, event_key="trade:1", receive_time="2026-08-23T00:00:01Z")
    write_event(second_path, event_key="trade:2", receive_time="2026-08-23T00:00:02Z")
    first = validate_jsonl_segment(
        first_path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )
    second = validate_jsonl_segment(
        second_path,
        root=root,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
    )

    forward = compact_validated_segments([first, second], tmp_path / "forward")
    reverse = compact_validated_segments([second, first], tmp_path / "reverse")

    assert forward.dataset_id == reverse.dataset_id
    assert forward.logical_sha256 == reverse.logical_sha256
    assert forward.row_count == reverse.row_count == 2
