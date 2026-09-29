from __future__ import annotations

import json
from pathlib import Path

from scripts.summarize_continuous_paper_state import (
    render_markdown,
    summarize_state,
    write_summary,
)


def test_state_size_summary_groups_top_level_and_largest_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    (root / "trade-paths" / "records").mkdir(parents=True)
    (root / "opening-opportunities").mkdir(parents=True)
    (root / "paper.sqlite3").write_bytes(b"x" * 7)
    (root / "trade-paths" / "records" / "a.json").write_bytes(
        b"a" * 11
    )
    (root / "trade-paths" / "records" / "b.json").write_bytes(
        b"b" * 5
    )
    (root / "opening-opportunities" / "c.json").write_bytes(
        b"c" * 3
    )

    summary = summarize_state(root, largest_file_limit=2)

    assert summary["logical_bytes"] == 26
    assert summary["file_count"] == 4
    assert [
        (item["name"], item["logical_bytes"], item["file_count"])
        for item in summary["top_level"]
    ] == [
        ("trade-paths", 16, 2),
        ("paper.sqlite3", 7, 1),
        ("opening-opportunities", 3, 1),
    ]
    assert [
        item["path"] for item in summary["largest_files"]
    ] == [
        "trade-paths/records/a.json",
        "paper.sqlite3",
    ]


def test_state_size_summary_json_and_markdown_are_stable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    root.mkdir()
    (root / "journal.sqlite3").write_bytes(b"journal")

    summary = summarize_state(root)
    output = tmp_path / "state-size.json"
    write_summary(summary, output)

    restored = json.loads(output.read_text(encoding="utf-8"))
    assert restored == summary
    markdown = render_markdown(summary)

    assert "## Continuous paper durable state size" in markdown
    assert "| journal.sqlite3 | 7 |" in markdown
    assert "### Largest state files" in markdown
    assert "`journal.sqlite3`" in markdown
