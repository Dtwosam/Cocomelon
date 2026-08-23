from __future__ import annotations

import importlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

from cocomelon.domain.replay import EvidenceClass
from cocomelon.replay.compaction import (
    ResearchDependencyError,
    compact_recording,
)
from cocomelon.replay.source import validate_recording


def _write_event(
    root: Path,
    *,
    event_key: str,
    receive_time: str,
    segment: int = 1,
) -> Path:
    path = root / f"events/2026-08-23/trade/SOL/segment-{segment:06d}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "record_type": "normalized_event",
        "schema_version": 1,
        "source": "hyperliquid-mainnet-ws",
        "kind": "trade",
        "market": "SOL",
        "exchange_time_ms": 1_000 + segment,
        "receive_time": receive_time,
        "event_key": event_key,
        "payload": {"price": "100", "size": "1"},
    }
    path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _recording(tmp_path: Path) -> tuple[Path, tuple[object, ...]]:
    root = tmp_path / "recordings"
    _write_event(
        root,
        event_key="trades:SOL:1001:1",
        receive_time="2026-08-23T00:00:01Z",
    )
    return root, validate_recording(root)


def test_base_runtime_does_not_depend_on_pyarrow() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    base = config["project"]["dependencies"]
    research = config["project"]["optional-dependencies"]["research"]

    assert all("pyarrow" not in item.lower() for item in base)
    assert any(item.startswith("pyarrow>=25") and "<26" in item for item in research)


def test_importing_compactor_does_not_eagerly_import_pyarrow() -> None:
    sys.modules.pop("pyarrow", None)
    module = importlib.import_module("cocomelon.replay.compaction")

    assert module is not None
    assert "pyarrow" not in sys.modules


def test_compaction_surfaces_clear_optional_dependency_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, segments = _recording(tmp_path)
    module = importlib.import_module("cocomelon.replay.compaction")

    def missing(name: str):
        if name.startswith("pyarrow"):
            raise ImportError("missing pyarrow")
        return importlib.import_module(name)

    monkeypatch.setattr(module.importlib, "import_module", missing)

    with pytest.raises(ResearchDependencyError, match="research"):
        compact_recording(root, tmp_path / "datasets", segments)


def test_true_parquet_preserves_canonical_rows_and_provenance(tmp_path: Path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    root, segments = _recording(tmp_path)
    source_bytes = {
        segment.relative_path: (root / segment.relative_path).read_bytes() for segment in segments
    }

    manifest = compact_recording(root, tmp_path / "datasets", segments)

    assert len(manifest.dataset_id) == 64
    assert len(manifest.logical_sha256) == 64
    assert manifest.row_count == 1
    assert manifest.evidence_class is EvidenceClass.MICROSTRUCTURE
    assert len(manifest.output_files) == 1
    output = manifest.dataset_root / manifest.output_files[0].relative_path
    assert output.suffix == ".parquet"
    assert output.read_bytes()[:4] == b"PAR1"
    table = parquet.read_table(output)
    assert table.num_rows == 1
    row = table.to_pylist()[0]
    assert row["source_relative_path"] == segments[0].relative_path
    assert row["source_sha256"] == segments[0].sha256
    assert row["source_line_number"] == 1
    assert row["record_kind"] == "normalized_event"
    assert row["event_kind"] == "trade"
    assert row["market"] == "SOL"
    assert row["payload_json"] == '{"price":"100","size":"1"}'
    for relative_path, expected in source_bytes.items():
        assert (root / relative_path).read_bytes() == expected


def test_dataset_identity_is_stable_across_segment_enumeration_order(tmp_path: Path) -> None:
    pytest.importorskip("pyarrow")
    root = tmp_path / "recordings"
    _write_event(
        root,
        event_key="trades:SOL:1001:1",
        receive_time="2026-08-23T00:00:01Z",
        segment=1,
    )
    _write_event(
        root,
        event_key="trades:SOL:1002:2",
        receive_time="2026-08-23T00:00:02Z",
        segment=2,
    )
    segments = validate_recording(root)

    forward = compact_recording(root, tmp_path / "forward", segments)
    reverse = compact_recording(root, tmp_path / "reverse", tuple(reversed(segments)))

    assert forward.dataset_id == reverse.dataset_id
    assert forward.logical_sha256 == reverse.logical_sha256
    assert forward.row_count == reverse.row_count == 2
