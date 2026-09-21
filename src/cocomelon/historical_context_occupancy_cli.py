from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TextIO

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import (
    DecisionAction,
    ExecutionCostAssumptions,
)
from cocomelon.research.historical_context_occupancy import (
    run_context_occupancy_from_sources,
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


def _direction(value: str) -> DecisionAction:
    normalized = value.strip().lower()
    if normalized == "long":
        return DecisionAction.LONG
    if normalized == "short":
        return DecisionAction.SHORT
    raise argparse.ArgumentTypeError("direction must be long or short")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-context-occupancy",
        description=(
            "Evaluate a touched historical context under one-position-per-market "
            "occupancy semantics"
        ),
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--market", required=True, action="append", type=_market)
    parser.add_argument("--horizon-ms", required=True, action="append", type=int)
    parser.add_argument(
        "--anchor-interval",
        choices=("5m", "15m", "1h"),
        default="1h",
    )
    parser.add_argument("--discovery-report-id", required=True)
    parser.add_argument("--discovery-dataset-id", required=True)
    parser.add_argument("--candidate-market", required=True, type=_market)
    parser.add_argument("--context-state", required=True)
    parser.add_argument("--direction", required=True, type=_direction)
    parser.add_argument("--candidate-horizon-ms", required=True, type=int)
    parser.add_argument("--round-trip-fee-fraction", required=True, type=_decimal)
    parser.add_argument("--round-trip-slippage-fraction", required=True, type=_decimal)
    parser.add_argument(
        "--funding-reserve-fraction-per-hour",
        required=True,
        type=_decimal,
    )
    parser.add_argument("--stability-blocks", type=int, default=4)
    parser.add_argument("--min-block-trades", type=int, default=20)
    parser.add_argument(
        "--min-block-mean-net-return",
        type=_decimal,
        default=Decimal("0"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = run_context_occupancy_from_sources(
            source_root=args.source_root,
            output_root=args.output_root,
            markets=args.market,
            horizons_ms=args.horizon_ms,
            anchor_interval=args.anchor_interval,
            discovery_report_id=args.discovery_report_id,
            discovery_dataset_id=args.discovery_dataset_id,
            market=args.candidate_market,
            context=args.context_state,
            direction=args.direction,
            horizon_ms=args.candidate_horizon_ms,
            costs=ExecutionCostAssumptions(
                round_trip_fee_fraction=args.round_trip_fee_fraction,
                round_trip_slippage_fraction=args.round_trip_slippage_fraction,
                funding_reserve_fraction_per_hour=args.funding_reserve_fraction_per_hour,
            ),
            stability_blocks=args.stability_blocks,
            min_block_trades=args.min_block_trades,
            min_block_mean_net_return=args.min_block_mean_net_return,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    evaluation = report.evaluation
    _emit(
        {
            "command": "historical-context-occupancy",
            "report_id": report.report_id,
            "dataset_id": report.dataset_id,
            "discovery_report_id": report.discovery_report_id,
            "discovery_dataset_id": report.discovery_dataset_id,
            "evidence_class": report.evidence_class,
            "market": evaluation.market,
            "context_state_1h": evaluation.context_state_1h,
            "direction": evaluation.direction.value,
            "horizon_ms": evaluation.horizon_ms,
            "raw_match_count": evaluation.raw_match_count,
            "trade_count": evaluation.trade_count,
            "occupied_skip_count": evaluation.occupied_skip_count,
            "mean_realized_net_return": (
                None
                if evaluation.mean_realized_net_return is None
                else str(evaluation.mean_realized_net_return)
            ),
            "stable": evaluation.stable,
            "output_root": str(args.output_root),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
