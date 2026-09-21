from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from cocomelon.domain.market import MarketId
from cocomelon.replay.compaction import ResearchDependencyError
from cocomelon.research.historical_baselines import (
    ExecutionCostAssumptions,
    HistoricalBaselineError,
)
from cocomelon.research.historical_dataset import HistoricalDatasetIntegrityError
from cocomelon.research.historical_experiment import (
    HistoricalExperimentConfig,
    HistoricalExperimentError,
    run_historical_experiment_from_sources,
)


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


def _parse_market(value: str) -> MarketId:
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("market must not be empty")
    if ":" not in stripped:
        return MarketId(dex="", coin=stripped)
    dex, coin = stripped.split(":", 1)
    if not dex or not coin or ":" in coin:
        raise argparse.ArgumentTypeError(f"invalid canonical market: {value!r}")
    return MarketId(dex=dex, coin=coin)


def _parse_decimal(value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise argparse.ArgumentTypeError("decimal values must be finite")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-experiment",
        description="Run a touched historical directional-learning experiment",
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--market", required=True, action="append", type=_parse_market)
    parser.add_argument("--horizon-ms", required=True, action="append", type=int)
    parser.add_argument(
        "--round-trip-fee-fraction",
        required=True,
        type=_parse_decimal,
    )
    parser.add_argument(
        "--round-trip-slippage-fraction",
        required=True,
        type=_parse_decimal,
    )
    parser.add_argument(
        "--funding-reserve-fraction-per-hour",
        required=True,
        type=_parse_decimal,
    )
    parser.add_argument(
        "--candidate-threshold",
        required=True,
        action="append",
        type=_parse_decimal,
    )
    parser.add_argument("--min-train-anchors", required=True, type=int)
    parser.add_argument("--validation-anchors", required=True, type=int)
    parser.add_argument("--test-anchors", required=True, type=int)
    parser.add_argument("--step-anchors", required=True, type=int)
    parser.add_argument("--embargo-anchors", required=True, type=int)
    parser.add_argument("--min-state-samples", required=True, type=int)
    parser.add_argument("--min-coin-samples", required=True, type=int)
    parser.add_argument("--min-sample-count", required=True, type=int)
    parser.add_argument("--min-validation-trades", required=True, type=int)
    parser.add_argument(
        "--min-validation-mean-net-return",
        type=_parse_decimal,
        default=Decimal("0"),
    )
    return parser


def run_experiment(
    *,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    min_train_anchors: int,
    validation_anchors: int,
    test_anchors: int,
    step_anchors: int,
    embargo_anchors: int,
    min_state_samples: int,
    min_coin_samples: int,
    min_sample_count: int,
    min_validation_trades: int,
    min_validation_mean_net_return: Decimal = Decimal("0"),
) -> dict[str, object]:
    config = HistoricalExperimentConfig(
        costs=costs,
        candidate_thresholds=tuple(candidate_thresholds),
        min_train_anchors=min_train_anchors,
        validation_anchors=validation_anchors,
        test_anchors=test_anchors,
        step_anchors=step_anchors,
        embargo_anchors=embargo_anchors,
        min_state_samples=min_state_samples,
        min_coin_samples=min_coin_samples,
        min_sample_count=min_sample_count,
        min_validation_trades=min_validation_trades,
        min_validation_mean_net_return=min_validation_mean_net_return,
    )
    report = run_historical_experiment_from_sources(
        source_root=source_root,
        output_root=output_root,
        markets=markets,
        horizons_ms=horizons_ms,
        config=config,
    )
    return {
        "command": "historical-experiment",
        "dataset_id": report.dataset_id,
        "evidence_class": report.evidence_class,
        "fold_count": len(report.folds),
        "horizons_ms": report.horizons_ms,
        "markets": report.markets,
        "output_root": str(output_root),
        "report_id": report.report_id,
        "row_count": report.dataset_row_count,
        "source_manifest_count": len(report.source_manifest_ids),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = run_experiment(
            source_root=args.source_root,
            output_root=args.output_root,
            markets=args.market,
            horizons_ms=args.horizon_ms,
            costs=ExecutionCostAssumptions(
                round_trip_fee_fraction=args.round_trip_fee_fraction,
                round_trip_slippage_fraction=args.round_trip_slippage_fraction,
                funding_reserve_fraction_per_hour=args.funding_reserve_fraction_per_hour,
            ),
            candidate_thresholds=args.candidate_threshold,
            min_train_anchors=args.min_train_anchors,
            validation_anchors=args.validation_anchors,
            test_anchors=args.test_anchors,
            step_anchors=args.step_anchors,
            embargo_anchors=args.embargo_anchors,
            min_state_samples=args.min_state_samples,
            min_coin_samples=args.min_coin_samples,
            min_sample_count=args.min_sample_count,
            min_validation_trades=args.min_validation_trades,
            min_validation_mean_net_return=args.min_validation_mean_net_return,
        )
    except (
        OSError,
        ValueError,
        HistoricalBaselineError,
        HistoricalDatasetIntegrityError,
        HistoricalExperimentError,
        ResearchDependencyError,
    ) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
