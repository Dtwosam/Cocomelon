from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.frozen_no_trade_shadow import (
    MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1,
    build_frozen_no_trade_shadow_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-frozen-no-trade-shadow",
        description=(
            "Evaluate the frozen MON normal-volatility SHORT abstention "
            "candidate only on post-embargo paper evidence"
        ),
    )
    parser.add_argument("--input", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input report must be an object")
        report = build_frozen_no_trade_shadow_report(payload)
    except (
        OSError,
        json.JSONDecodeError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "command": "frozen-no-trade-shadow",
                "candidate": MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1.identity_payload(),
                **report.to_dict(),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
