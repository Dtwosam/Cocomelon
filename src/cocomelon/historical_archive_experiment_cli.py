from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.market import MarketId
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.research.historical_archive_experiment import (
    HistoricalArchiveExperimentError,
    run_archive_historical_experiment,
)
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
)
from cocomelon.research.historical_trade_archive import HistoricalTradeArchiveError


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
        prog="cocomelon-historical-archive-experiment",
        description=(
            "Run touched historical learning from a verified local Hyperliquid "
            "fill-archive cache plus public funding history"
        ),
    )
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--market", required=True, action="append", type=_market)
    parser.add_argument("--interval", required=True, action="append")
    parser.add_argument("--horizon-ms", required=True, action="append", type=int)
    parser.add_argument("--start-ms", required=True, type=int)
    parser.add_argument("--end-ms", required=True, type=int)
    parser.add_argument("--max-funding-items", type=int, default=500)
    parser.add_argument("--received-at-ms", type=int)
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
    parser.add_argument("--min-sample-count", required=True, type=int)
    parser.add_argument("--min-validation-trades", required=True, type=int)
    parser.add_argument(
        "--min-validation-mean-net-return",
        type=_decimal,
        default=Decimal("0"),
    )
    parser.add_argument("--stability-blocks", type=int, default=4)
    parser.add_argument("--min-validation-block-trades", type=int, default=5)
    return parser


def _clock(received_at_ms: int | None) -> Callable[[], int]:
    if received_at_ms is None:
        return lambda: time.time_ns() // 1_000_000
    if received_at_ms < 0:
        raise ValueError("received_at_ms must be non-negative")
    return lambda: received_at_ms


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if settings.execution_mode is not ExecutionMode.PAPER:
            raise ValueError("historical archive experiments require paper execution mode")
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
        )
        result = run_archive_historical_experiment(
            InfoClient(settings),
            archive_root=args.archive_root,
            source_root=args.source_root,
            output_root=args.output_root,
            markets=args.market,
            intervals=args.interval,
            horizons_ms=args.horizon_ms,
            start_ms=args.start_ms,
            end_ms=args.end_ms,
            clock_ms=_clock(args.received_at_ms),
            config=config,
            max_funding_items=args.max_funding_items,
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        HistoricalArchiveExperimentError,
        HistoricalTradeArchiveError,
    ) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "historical-archive-experiment",
            "evidence_class": result.comparison.evidence_class,
            "archive_manifest_id": result.archive.manifest_id,
            "archive_shard_count": result.archive.shard_count,
            "archive_total_byte_count": result.archive.total_byte_count,
            "dataset_id": result.dataset_id,
            "report_id": result.report_id,
            "row_count": result.comparison.dataset_row_count,
            "fold_count": len(result.comparison.baseline_folds),
            "markets": result.comparison.markets,
            "horizons_ms": result.comparison.horizons_ms,
            "source_summary": dict(result.source_summary),
            "output_root": str(args.output_root),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
