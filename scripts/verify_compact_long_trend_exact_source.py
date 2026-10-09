"""Report exact missing inputs without manufacturing LONG-trend evidence."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path


REQUIRED_FILES = (
    "prospective-full-stack-forward-markout-summary.json",
    "prospective-long-trend-execution-shadow-source.json",
)
REQUIRED_DIRS = (
    "opening-opportunities/records",
    "opening-opportunity-exit-books/records",
    "replacement-funding-boundaries/records",
)


def verify_source(root: Path) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for name in REQUIRED_FILES:
        candidate = root / name
        size = candidate.stat().st_size if candidate.is_file() else 0
        records.append(
            {
                "path": name,
                "type": "file",
                "present": size > 0,
                "size_bytes": size,
            }
        )
    for name in REQUIRED_DIRS:
        candidate = root / name
        records.append(
            {
                "path": name,
                "type": "directory",
                "present": candidate.is_dir(),
            }
        )
    ready = all(row["present"] is True for row in records)
    return {
        "schema_version": 1,
        "kind": "compact-long-trend-exact-source-preflight",
        "source_run_id": os.getenv("GITHUB_RUN_ID", ""),
        "source_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "ready": ready,
        "inputs": records,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    args = parser.parse_args(argv)
    report = verify_source(args.state_root)
    args.json_out.write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True))
    if report["ready"] is not True:
        for item in report["inputs"]:
            if item["present"] is not True:
                print(
                    f"::error::missing authenticated LONG-trend input: "
                    f"{item['type']} {item['path']}"
                )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
