from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
    run_historical_model_comparison_from_sources,
)
from cocomelon.research.historical_tree import TreeModelConfig


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


def _market(value: str) -> MarketId:
    stripped = value.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("market must not be empty")
    if ":" not in stripped:
        return MarketId(dex="", coin=stripped)
    dex, coin = stripped.split(":", 1)
    if not dex or not coin or ":" in coin:
        raise argparse.ArgumentTypeError(f"invalid canonical market: {value!r}")
    return MarketId(dex=dex, coin=coin)


def _decimal(value: str) -> Decimal:
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid decimal: {value!r}") from exc
    if not resolved.is_finite():
        raise argparse.ArgumentTypeError("decimal values must be finite")
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-model-comparison",
        description="Compare touched directional historical learners",
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--market", required=True, action="append", type=_market)
    parser.add_argument("--horizon-ms", required=True, action="append", type=int)
    parser.add_argument("--round-trip-fee-fraction", required=True, type=_decimal)
    parser.add_argument("--round-trip-slippage-fraction", required=True, type=_decimal)
    parser.add_argument(
        "--funding-reserve-fraction-per-hour",
        required=True,
        type=_decimal,
    )
    parser.add_argument(
        "--candidate-threshold",
        required=True,
        action="append",
        type=_decimal,
    )
    parser.add_argument(
        "--candidate-ridge-alpha",
        required=True,
        action="append",
        type=_decimal,
    )
    parser.add_argument("--min-train-anchors", required=True, type=int)
    parser.add_argument("--validation-anchors", required=True, type=int)
    parser.add_argument("--test-anchors", required=True, type=int)
    parser.add_argument("--step-anchors", required=True, type=int)
    parser.add_argument("--embargo-anchors", required=True, type=int)
    parser.add_argument("--baseline-min-state-samples", required=True, type=int)
    parser.add_argument("--baseline-min-coin-samples", required=True, type=int)
    parser.add_argument("--ridge-min-market-samples", required=True, type=int)
    parser.add_argument("--tree-min-market-samples", type=int, default=100)
    parser.add_argument("--tree-max-leaf-nodes", type=int, default=7)
    parser.add_argument("--tree-min-samples-leaf", type=int, default=100)
    parser.add_argument("--tree-learning-rate", type=_decimal, default=Decimal("0.05"))
    parser.add_argument("--tree-max-iter", type=int, default=100)
    parser.add_argument(
        "--tree-l2-regularization",
        type=_decimal,
        default=Decimal("1"),
    )
    parser.add_argument("--min-sample-count", required=True, type=int)
    parser.add_argument("--min-validation-trades", required=True, type=int)
    parser.add_argument(
        "--min-validation-mean-net-return",
        type=_decimal,
        default=Decimal("0"),
    )
    parser.add_argument("--stability-blocks", type=int, default=2)
    parser.add_argument("--min-validation-block-trades", type=int, default=1)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = HistoricalModelComparisonConfig(
            costs=ExecutionCostAssumptions(
                round_trip_fee_fraction=args.round_trip_fee_fraction,
                round_trip_slippage_fraction=args.round_trip_slippage_fraction,
                funding_reserve_fraction_per_hour=args.funding_reserve_fraction_per_hour,
            ),
            candidate_thresholds=tuple(args.candidate_threshold),
            candidate_ridge_alphas=tuple(args.candidate_ridge_alpha),
            min_train_anchors=args.min_train_anchors,
            validation_anchors=args.validation_anchors,
            test_anchors=args.test_anchors,
            step_anchors=args.step_anchors,
            embargo_anchors=args.embargo_anchors,
            baseline_min_state_samples=args.baseline_min_state_samples,
            baseline_min_coin_samples=args.baseline_min_coin_samples,
            ridge_min_market_samples=args.ridge_min_market_samples,
            min_sample_count=args.min_sample_count,
            min_validation_trades=args.min_validation_trades,
            min_validation_mean_net_return=args.min_validation_mean_net_return,
            stability_blocks=args.stability_blocks,
            min_validation_block_trades=args.min_validation_block_trades,
            tree_min_market_samples=args.tree_min_market_samples,
            tree_config=TreeModelConfig(
                max_leaf_nodes=args.tree_max_leaf_nodes,
                min_samples_leaf=args.tree_min_samples_leaf,
                learning_rate=args.tree_learning_rate,
                max_iter=args.tree_max_iter,
                l2_regularization=args.tree_l2_regularization,
            ),
        )
        report = run_historical_model_comparison_from_sources(
            source_root=args.source_root,
            output_root=args.output_root,
            markets=args.market,
            horizons_ms=args.horizon_ms,
            config=config,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "historical-model-comparison",
            "report_id": report.report_id,
            "dataset_id": report.dataset_id,
            "evidence_class": report.evidence_class,
            "row_count": report.dataset_row_count,
            "fold_count": len(report.baseline_folds),
            "markets": report.markets,
            "horizons_ms": report.horizons_ms,
            "output_root": str(args.output_root),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
