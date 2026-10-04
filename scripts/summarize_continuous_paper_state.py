from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Final

SCHEMA_VERSION: Final = 2
DEFAULT_LARGEST_FILE_LIMIT: Final = 20


def _allocated_bytes(stat: os.stat_result) -> int:
    blocks = getattr(stat, "st_blocks", None)
    if isinstance(blocks, int) and blocks >= 0:
        return blocks * 512
    return stat.st_size


def _sqlite_utilization(path: Path, root: Path) -> dict[str, int | str]:
    connection = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
    )
    try:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist_count = int(
            connection.execute("PRAGMA freelist_count").fetchone()[0]
        )
    finally:
        connection.close()
    return {
        "path": path.relative_to(root).as_posix(),
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "page_bytes": page_size * page_count,
        "freelist_bytes": page_size * freelist_count,
        "live_page_bytes": page_size * max(0, page_count - freelist_count),
    }


def summarize_state(
    root: Path,
    *,
    largest_file_limit: int = DEFAULT_LARGEST_FILE_LIMIT,
) -> dict[str, Any]:
    if largest_file_limit < 0:
        raise ValueError("largest_file_limit must be non-negative")
    if not root.is_dir():
        raise ValueError("state root must be an existing directory")

    top_level: dict[str, dict[str, int | str]] = {}
    largest_files: list[dict[str, int | str]] = []
    logical_bytes = 0
    allocated_bytes = 0
    file_count = 0
    sqlite_databases: list[dict[str, int | str]] = []

    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        stat = path.stat()
        relative = path.relative_to(root)
        top_name = relative.parts[0]
        logical = stat.st_size
        allocated = _allocated_bytes(stat)

        bucket = top_level.setdefault(
            top_name,
            {
                "name": top_name,
                "logical_bytes": 0,
                "allocated_bytes": 0,
                "file_count": 0,
            },
        )
        bucket["logical_bytes"] = int(bucket["logical_bytes"]) + logical
        bucket["allocated_bytes"] = (
            int(bucket["allocated_bytes"]) + allocated
        )
        bucket["file_count"] = int(bucket["file_count"]) + 1

        logical_bytes += logical
        allocated_bytes += allocated
        file_count += 1
        largest_files.append(
            {
                "path": relative.as_posix(),
                "logical_bytes": logical,
                "allocated_bytes": allocated,
            }
        )
        if path.suffix == ".sqlite3":
            sqlite_databases.append(
                _sqlite_utilization(path, root)
            )

    ordered_top = sorted(
        top_level.values(),
        key=lambda item: (
            -int(item["logical_bytes"]),
            str(item["name"]),
        ),
    )
    ordered_files = sorted(
        largest_files,
        key=lambda item: (
            -int(item["logical_bytes"]),
            str(item["path"]),
        ),
    )[:largest_file_limit]

    return {
        "schema_version": SCHEMA_VERSION,
        "logical_bytes": logical_bytes,
        "allocated_bytes": allocated_bytes,
        "file_count": file_count,
        "top_level": ordered_top,
        "largest_files": ordered_files,
        "sqlite_databases": sorted(
            sqlite_databases,
            key=lambda item: (
                -int(item["page_bytes"]),
                str(item["path"]),
            ),
        ),
    }


def write_summary(summary: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            summary,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "## Continuous paper durable state size",
        "",
        (
            "- total logical bytes / allocated bytes / files: "
            f"`{summary['logical_bytes']} / "
            f"{summary['allocated_bytes']} / "
            f"{summary['file_count']}`"
        ),
        "",
        "| Top-level state | Logical bytes | Allocated bytes | Files |",
        "| --- | ---: | ---: | ---: |",
    ]
    raw_top = summary.get("top_level")
    if isinstance(raw_top, list):
        for item in raw_top:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| {item.get('name')} | "
                f"{item.get('logical_bytes')} | "
                f"{item.get('allocated_bytes')} | "
                f"{item.get('file_count')} |"
            )

    lines.extend(
        [
            "",
            "### Largest state files",
            "",
            "| File | Logical bytes | Allocated bytes |",
            "| --- | ---: | ---: |",
        ]
    )
    raw_files = summary.get("largest_files")
    if isinstance(raw_files, list):
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| `{item.get('path')}` | "
                f"{item.get('logical_bytes')} | "
                f"{item.get('allocated_bytes')} |"
            )

    lines.extend(
        [
            "",
            "### SQLite page utilization",
            "",
            (
                "| Database | Page bytes | Live-page bytes | "
                "Freelist bytes | Free pages | Total pages |"
            ),
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    raw_sqlite = summary.get("sqlite_databases")
    if isinstance(raw_sqlite, list):
        for item in raw_sqlite:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"| `{item.get('path')}` | "
                f"{item.get('page_bytes')} | "
                f"{item.get('live_page_bytes')} | "
                f"{item.get('freelist_bytes')} | "
                f"{item.get('freelist_count')} | "
                f"{item.get('page_count')} |"
            )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize continuous-paper durable state size without "
            "modifying the state."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument(
        "--largest-file-limit",
        type=int,
        default=DEFAULT_LARGEST_FILE_LIMIT,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = summarize_state(
        args.root,
        largest_file_limit=args.largest_file_limit,
    )
    write_summary(summary, args.json_out)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.write_text(
        render_markdown(summary),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
