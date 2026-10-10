"""Read-only forensic CLI for an authenticated, separately obtained source pair.

This script does NOT download artifacts, verify GitHub run authority, mutate
published ledgers, or declare trading readiness. Obtain both source files
from independently authenticated GitHub Actions artifacts first.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_risk_rejected_forward_markout_ledger import (
    ProspectiveRiskRejectedForwardMarkoutLedgerError,
    load_risk_rejected_forward_markout_ledger,
)
from cocomelon.research.terminal_source_parity import (
    TerminalSourceParityError,
    audit_terminal_source_parity,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Produce a redacted, read-only immutable ledger/source parity audit"
    )
    parser.add_argument("--previous-ledger", type=Path, required=True)
    parser.add_argument("--rebuilt-summary", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if (
        args.json_out.resolve() == args.previous_ledger.resolve()
        or args.json_out.resolve() == args.rebuilt_summary.resolve()
    ):
        raise SystemExit("audit output cannot overwrite an input source")
    try:
        previous = load_risk_rejected_forward_markout_ledger(
            args.previous_ledger
        )
        source = json.loads(args.rebuilt_summary.read_text(encoding="utf-8"))
        result = audit_terminal_source_parity(previous, source)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        ProspectiveRiskRejectedForwardMarkoutLedgerError,
        TerminalSourceParityError,
    ) as exc:
        raise SystemExit(f"redacted terminal source parity audit failed: {type(exc).__name__}") from exc

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "previous_terminal_rows": result["previous_terminal_rows"],
                "previous_rows_unchanged": result["previous_rows_unchanged"],
                "previous_rows_changed": result["previous_rows_changed"],
                "previous_rows_missing": result["previous_rows_missing"],
                "changed_rows_markout_drift": result["changed_rows_markout_drift"],
                "historical_parity_blocked": result["historical_parity_blocked"],
                "research_readiness_blocked": result["research_readiness_blocked"],
                "execution_authority": False,
                "promotion_authority": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
