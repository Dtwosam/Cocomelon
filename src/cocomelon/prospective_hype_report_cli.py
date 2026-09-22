from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import ProspectiveEvidenceStore
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
    build_prospective_validation_report,
)
from cocomelon.util.time import utc_now_ms


def _emit(payload: dict[str, object], *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=target,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-prospective-hype-report",
        description="Evaluate frozen prospective HYPE evidence under its fixed validation plan",
    )
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--as-of-ms", type=int)
    return parser


def prospective_hype_report_payload(
    *,
    root: Path,
    as_of_ms: int | None = None,
) -> dict[str, object]:
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    store = ProspectiveEvidenceStore(root, spec=spec)
    resolved_as_of_ms = utc_now_ms() if as_of_ms is None else as_of_ms
    report = build_prospective_validation_report(
        store,
        as_of_ms=resolved_as_of_ms,
        plan=HYPE_PROSPECTIVE_VALIDATION_V1,
    )
    return {
        "command": "prospective-hype-report",
        **report.to_dict(),
        "state_digest": store.state_digest,
        "root": str(root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = prospective_hype_report_payload(
            root=args.root,
            as_of_ms=args.as_of_ms,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
