from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_weekly_drawdown_5m_exit import (
    ProspectiveWeeklyDrawdown5mExitError,
    prospective_weekly_drawdown_5m_exit_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-prospective-weekly-drawdown-5m-exit",
        description=(
            "Replay the frozen weekly-drawdown-only full-stack ADMIT "
            "candidate through exact captured entry, observed stop-path, "
            "real-L2 5m exit, fee, and funding evidence."
        ),
    )
    parser.add_argument("source_path", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = json.loads(
            args.source_path.read_text(encoding="utf-8")
        )
        summary = prospective_weekly_drawdown_5m_exit_summary(
            source
        )
    except (
        OSError,
        json.JSONDecodeError,
        ProspectiveWeeklyDrawdown5mExitError,
        ValueError,
    ) as exc:
        raise SystemExit(str(exc)) from exc

    args.json_out.write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    robustness = summary["robustness"]
    assert isinstance(robustness, dict)
    print(
        json.dumps(
            {
                "source_opportunities": summary[
                    "source_opportunities"
                ],
                "exact_realized_pnl_options": summary[
                    "exact_realized_pnl_options"
                ],
                "total_exact_realized_pnl": summary[
                    "total_exact_realized_pnl"
                ],
                "market_count": robustness["market_count"],
                "minimum_sample_met": robustness[
                    "minimum_sample_met"
                ],
                "candidate_investigation_ready": summary[
                    "candidate_investigation_ready"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
