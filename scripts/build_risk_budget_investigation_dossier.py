from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_risk_budget_investigation_dossier import (
    build_risk_budget_investigation_dossier,
    validate_risk_budget_investigation_dossier,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build-risk-budget-investigation-dossier",
        description=(
            "Join source-aligned risk-rejected return and original-stop "
            "evidence into a research-only conjunctive readiness dossier."
        ),
    )
    parser.add_argument("return_ledger", type=Path)
    parser.add_argument("stop_ledger", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_risk_budget_investigation_dossier(
        _load(args.return_ledger),
        _load(args.stop_ledger),
    )
    validate_risk_budget_investigation_dossier(report)
    args.json_out.write_text(
        json.dumps(
            report,
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
                "status": report["status"],
                "source_aligned": report["source_aligned"],
                "integrity_clean": report["integrity_clean"],
                "ready_reasons": report["ready_reasons"],
                "weekly_drawdown_5m_status": report[
                    "weekly_drawdown_5m_candidate"
                ]["status"],
                "weekly_drawdown_5m_review_rows": report[
                    "weekly_drawdown_5m_candidate"
                ]["review_rows"],
                "report_sha256": report["report_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
