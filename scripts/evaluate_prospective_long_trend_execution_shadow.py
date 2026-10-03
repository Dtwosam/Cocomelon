from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.prospective_long_trend_carveout_execution_shadow import (
    ProspectiveLongTrendExecutionShadowError,
    prospective_long_trend_execution_shadow_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-prospective-long-trend-execution-shadow",
        description=(
            "Replay weekly-drawdown-rejected LONG+trend carveouts through "
            "the captured paper risk/planner/visible-book IOC path."
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
        summary = prospective_long_trend_execution_shadow_summary(
            source,
            PaperExecutionConfig(),
        )
    except (
        OSError,
        json.JSONDecodeError,
        ProspectiveLongTrendExecutionShadowError,
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
    print(
        json.dumps(
            {
                "source_opportunities": summary[
                    "source_opportunities"
                ],
                "counterfactual_risk_approvals": summary[
                    "counterfactual_risk_approvals"
                ],
                "fillable_opportunities": summary[
                    "fillable_opportunities"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
