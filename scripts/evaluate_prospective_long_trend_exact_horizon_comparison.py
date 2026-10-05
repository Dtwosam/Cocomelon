from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ReplacementFundingBoundaryEvidence,
)
from cocomelon.research.prospective_full_stack_forward_markout import (
    LONG_TREND_CARVEOUT_CANDIDATE_ID,
)
from cocomelon.research.prospective_long_trend_5m_exit import (
    ProspectiveLongTrend5mExitError,
    prospective_long_trend_5m_exit_summary,
)
from cocomelon.research.prospective_long_trend_5m_exit_source import (
    ProspectiveLongTrend5mExitSourceError,
    ProspectiveLongTrend5mExitState,
    prospective_long_trend_5m_exit_source,
)
from cocomelon.research.prospective_long_trend_15m_exit import (
    ProspectiveLongTrend15mExitError,
    prospective_long_trend_15m_exit_summary,
)
from cocomelon.research.prospective_long_trend_15m_exit_source import (
    ProspectiveLongTrend15mExitSourceError,
    ProspectiveLongTrend15mExitState,
    prospective_long_trend_15m_exit_source,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow import (
    _execution_config_from_payload,
    _sha256,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    SCHEMA_VERSION as LONG_TREND_SOURCE_SCHEMA_VERSION,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    SOURCE_KIND as LONG_TREND_SOURCE_KIND,
)
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    WEEKLY_DRAWDOWN_REASON,
)
from cocomelon.research.prospective_long_trend_exact_horizon_comparison import (
    COMMON_FROZEN_STARTED_AT_MS,
    ProspectiveLongTrendExactHorizonComparisonError,
    prospective_long_trend_exact_horizon_comparison,
)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _records[T](
    root: Path,
    parser: Callable[[object], T],
) -> tuple[T, ...]:
    if not root.is_dir():
        raise ValueError(f"missing evidence records directory: {root}")
    return tuple(
        parser(_read_json(path))
        for path in sorted(root.glob("*.json"))
    )


def _execution_config_from_durable_long_trend_source(
    raw: object,
) -> PaperExecutionConfig:
    if not isinstance(raw, dict):
        raise ValueError("durable LONG+trend source must be an object")
    if raw.get("schema_version") != LONG_TREND_SOURCE_SCHEMA_VERSION:
        raise ValueError("durable LONG+trend source schema is unsupported")
    if raw.get("kind") != LONG_TREND_SOURCE_KIND:
        raise ValueError("durable LONG+trend source kind is unsupported")
    if raw.get("candidate_id") != LONG_TREND_CARVEOUT_CANDIDATE_ID:
        raise ValueError("durable LONG+trend candidate lineage mismatch")
    if raw.get("baseline_risk_reason") != WEEKLY_DRAWDOWN_REASON:
        raise ValueError("durable LONG+trend risk reason drift")
    for key, expected in (
        ("research_only", True),
        ("execution_authority", False),
        ("promotion_authority", False),
        ("changes_execution", False),
        ("changes_risk_limits", False),
        ("changes_candidate_readiness", False),
        ("durable_gate_required", True),
    ):
        if raw.get(key) is not expected:
            raise ValueError(f"durable LONG+trend authority drift: {key}")

    config_payload = raw.get("execution_config")
    config_sha256 = raw.get("execution_config_sha256")
    if (
        not isinstance(config_sha256, str)
        or len(config_sha256) != 64
        or _sha256(config_payload) != config_sha256
    ):
        raise ValueError("durable LONG+trend execution config digest mismatch")
    return _execution_config_from_payload(config_payload)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate-prospective-long-trend-exact-horizon-comparison",
        description=(
            "Pair exact 5m and 15m reopened LONG+trend execution outcomes "
            "on the same post-freeze opportunities."
        ),
    )
    parser.add_argument("state_root", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--five-minute-out", type=Path)
    parser.add_argument("--fifteen-minute-out", type=Path)
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

        durable_long_trend = _read_json(
            root / "prospective-long-trend-execution-shadow-source.json"
        )
        execution_config = _execution_config_from_durable_long_trend_source(
            durable_long_trend
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

        five_state = ProspectiveLongTrend5mExitState(
            started_at_ms=COMMON_FROZEN_STARTED_AT_MS
        )
        fifteen_state = ProspectiveLongTrend15mExitState(
            started_at_ms=COMMON_FROZEN_STARTED_AT_MS
        )
        five_source = prospective_long_trend_5m_exit_source(
            full_stack,
            opportunities,
            exit_books,
            funding,
            execution_config,
            five_state,
        )
        fifteen_source = prospective_long_trend_15m_exit_source(
            full_stack,
            opportunities,
            exit_books,
            funding,
            execution_config,
            fifteen_state,
        )
        five_summary = prospective_long_trend_5m_exit_summary(five_source)
        fifteen_summary = prospective_long_trend_15m_exit_summary(
            fifteen_source
        )
        comparison = prospective_long_trend_exact_horizon_comparison(
            five_summary,
            fifteen_summary,
        )
    except (
        OSError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        ProspectiveLongTrend5mExitError,
        ProspectiveLongTrend5mExitSourceError,
        ProspectiveLongTrend15mExitError,
        ProspectiveLongTrend15mExitSourceError,
        ProspectiveLongTrendExactHorizonComparisonError,
    ) as exc:
        raise SystemExit(str(exc)) from exc

    _write_json(args.json_out, comparison)
    if args.five_minute_out is not None:
        _write_json(args.five_minute_out, five_summary)
    if args.fifteen_minute_out is not None:
        _write_json(args.fifteen_minute_out, fifteen_summary)

    print(
        json.dumps(
            {
                "paired_exact_options": comparison["paired_exact_options"],
                "market_count": comparison["market_count"],
                "total_pnl_delta_5m_minus_15m": comparison[
                    "total_pnl_delta_5m_minus_15m"
                ],
                "minimum_sample_met": comparison["minimum_sample_met"],
                "preferred_horizon": comparison["preferred_horizon"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
