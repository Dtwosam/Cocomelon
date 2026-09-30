from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections.abc import Sequence

from cocomelon.research.cadence_opportunity_audit import (
    CadenceOpportunityAuditError,
    load_cadence_outcomes,
)
from cocomelon.research.cadence_opportunity_learning import (
    evaluate_cadence_opportunity_learning,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-cadence-opportunity-learning",
        description=(
            "Evaluate the research-only cadence opportunity learner from an "
            "exact durable cadence-shadow-state.json snapshot."
        ),
    )
    parser.add_argument(
        "state_path",
        type=Path,
        help="Path to cadence-shadow-state.json",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional file path for canonical JSON output.",
    )
    return parser


def evaluate_state(state_path: Path) -> dict[str, object]:
    outcomes = load_cadence_outcomes(state_path)
    return evaluate_cadence_opportunity_learning(outcomes)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = evaluate_state(args.state_path)
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
