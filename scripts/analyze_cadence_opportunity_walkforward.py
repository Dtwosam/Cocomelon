from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.cadence_opportunity_audit import (
    CadenceOpportunityAuditError,
    load_cadence_outcomes,
)
from cocomelon.research.cadence_opportunity_walkforward import (
    evaluate_cadence_opportunity_walkforward,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="analyze-cadence-opportunity-walkforward",
        description=(
            "Run disjoint purged walk-forward diagnostics for the cadence "
            "opportunity learner from exact durable cadence state."
        ),
    )
    parser.add_argument("state_path", type=Path)
    parser.add_argument("--json-out", type=Path)
    return parser


def analyze_state(state_path: Path) -> dict[str, object]:
    outcomes = load_cadence_outcomes(state_path)
    return evaluate_cadence_opportunity_walkforward(outcomes)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = analyze_state(args.state_path)
    except CadenceOpportunityAuditError as exc:
        raise SystemExit(str(exc)) from exc
    encoded = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
