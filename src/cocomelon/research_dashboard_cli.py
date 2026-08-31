from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.dashboard import (
    build_research_status,
    render_research_status_markdown,
)
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError


def _emit_json(value: object, *, stream: TextIO) -> None:
    print(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=stream,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-research-status",
        description="Read-only touched/non-promotional research status",
    )
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    registry_path: Path = args.registry
    if not registry_path.is_file():
        _emit_json(
            {
                "error": f"research registry does not exist: {registry_path}",
                "error_type": "FileNotFoundError",
            },
            stream=sys.stderr,
        )
        return 2

    registry: ResearchRegistry | None = None
    try:
        registry = ResearchRegistry(registry_path)
        snapshot = build_research_status(registry)
        if args.format == "json":
            _emit_json(snapshot, stream=sys.stdout)
        else:
            print(render_research_status_markdown(snapshot), end="")
    except (OSError, ValueError, ResearchRegistryError, json.JSONDecodeError) as exc:
        _emit_json(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    finally:
        if registry is not None:
            registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
