from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ReplacementFundingBoundaryEvidence,
)
from cocomelon.research.prospective_long_trend_5m_exit import (
    ProspectiveLongTrend5mExitError,
    prospective_long_trend_5m_exit_summary,
)
from cocomelon.research.prospective_long_trend_5m_exit_source import (
    FROZEN_STARTED_AT_MS,
    ProspectiveLongTrend5mExitSourceError,
    ProspectiveLongTrend5mExitState,
    prospective_long_trend_5m_exit_source,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow import (
    _validate_source as _validate_long_trend_execution_source,
)

def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _records[T](
    root: Path,
    parser: Callable[[object], T],
) -> tuple[T, ...]:
    if not root.is_dir():
        raise ValueError(f"missing evidence records directory: {root}")
    rows: list[T] = []
    for path in sorted(root.glob("*.json")):
        rows.append(parser(_read_json(path)))
    return tuple(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-prospective-long-trend-5m-exit",
        description=(
            "Evaluate the post-freeze reopened pure LONG+trend cohort "
            "with captured entry IOC, observed stop survival, real-L2 "
            "5m exit, fees, and funding from a durable paper-state root."
        ),
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--source-out", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.state_root
        full_stack = _read_json(
            root / "prospective-full-stack-forward-markout-summary.json"
        )
        if not isinstance(full_stack, dict):
            raise ValueError("full-stack summary must be an object")

        long_trend_source = _read_json(
            root / "prospective-long-trend-execution-shadow-source.json"
        )
        _rows, execution_config, _config_source, _schema = (
            _validate_long_trend_execution_source(
                long_trend_source,
                legacy_config=None,
            )
        )

        opportunities = _records(
            root / "opening-opportunities" / "records",
            ContinuousPaperOpeningOpportunityEvidence.from_dict,
        )
        exit_books = _records(
            root / "opening-opportunity-exit-books" / "records",
            OpeningOpportunityExitBookEvidence.from_dict,
        )
        funding = _records(
            root / "replacement-funding-boundaries" / "records",
            ReplacementFundingBoundaryEvidence.from_dict,
        )
        state = ProspectiveLongTrend5mExitState(
            started_at_ms=FROZEN_STARTED_AT_MS
        )
        source = prospective_long_trend_5m_exit_source(
            full_stack,
            opportunities,
            exit_books,
            funding,
            execution_config,
            state,
        )
        summary = prospective_long_trend_5m_exit_summary(source)
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        ProspectiveLongTrend5mExitError,
        ProspectiveLongTrend5mExitSourceError,
    ) as exc:
        raise SystemExit(str(exc)) from exc

    if args.source_out is not None:
        args.source_out.write_text(
            json.dumps(
                source,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
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
                "source_opportunities": summary["source_opportunities"],
                "exact_realized_pnl_options": summary[
                    "exact_realized_pnl_options"
                ],
                "total_exact_realized_pnl": summary[
                    "total_exact_realized_pnl"
                ],
                "market_count": robustness["market_count"],
                "minimum_sample_met": robustness["minimum_sample_met"],
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
