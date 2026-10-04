import asyncio
import inspect
import json
from pathlib import Path

from cocomelon.continuous_paper import (
    _write_json_payload_batch_cooperatively,
)


def test_cooperative_checkpoint_writer_persists_each_file(
    tmp_path: Path,
) -> None:
    first = tmp_path / "runtime-state.json"
    second = tmp_path / "shadow-state.json"

    ms_by_file, bytes_by_file = asyncio.run(
        _write_json_payload_batch_cooperatively(
            (
                (first, {"value": 1}),
                (second, {"value": 2}),
            )
        )
    )

    assert json.loads(first.read_text(encoding="utf-8")) == {"value": 1}
    assert json.loads(second.read_text(encoding="utf-8")) == {"value": 2}
    assert set(ms_by_file) == {first.name, second.name}
    assert all(value >= 0 for value in ms_by_file.values())
    assert bytes_by_file[first.name] == len(first.read_bytes())
    assert bytes_by_file[second.name] == len(second.read_bytes())


def test_cooperative_checkpoint_writer_yields_between_files() -> None:
    source = inspect.getsource(_write_json_payload_batch_cooperatively)

    assert "await asyncio.to_thread(" in source
    assert "_write_json_atomic" in source
    assert "await asyncio.sleep(0)" in source
