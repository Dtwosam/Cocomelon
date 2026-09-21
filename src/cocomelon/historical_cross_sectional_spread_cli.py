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
from cocomelon.research.historical_cross_sectional_spread import (
    run_cross_sectional_spread_from_sources,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-cross-sectional-spread",
        description="Build touched leader-laggard momentum/reversal spread diagnostics",
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
    parser.add_argument("--round-trip-fee-fraction", required=True, type=_decimal)
    parser.add_argument("--round-trip-slippage-fraction", required=True, type=_decimal)
    parser.add_argument(
        "--funding-reserve-fraction-per-hour",
        required=True,
        type=_decimal,
    )
    parser.add_argument("--stability-blocks", type=int, default=4)
    parser.add_argument("--min-markets-per-anchor", type=int, default=4)
    parser.add_argument("--min-block-observations", type=int, default=50)
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
        report = run_cross_sectional_spread_from_sources(
            source_root=args.source_root,
            output_root=args.output_root,
            markets=args.market,
            horizons_ms=args.horizon_ms,
            anchor_interval=args.anchor_interval,
            costs=ExecutionCostAssumptions(
                round_trip_fee_fraction=args.round_trip_fee_fraction,
                round_trip_slippage_fraction=args.round_trip_slippage_fraction,
                funding_reserve_fraction_per_hour=args.funding_reserve_fraction_per_hour,
            ),
            stability_blocks=args.stability_blocks,
            min_markets_per_anchor=args.min_markets_per_anchor,
            min_block_observations=args.min_block_observations,
            min_block_mean_net_return=args.min_block_mean_net_return,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2

    _emit(
        {
            "command": "historical-cross-sectional-spread",
            "report_id": report.report_id,
            "dataset_id": report.dataset_id,
            "evidence_class": report.evidence_class,
            "anchor_interval": report.anchor_interval,
            "row_count": report.dataset_row_count,
            "markets": report.markets,
            "horizons_ms": report.horizons_ms,
            "stable_momentum_horizons": tuple(
                entry.horizon_ms for entry in report.entries if entry.stable_momentum
            ),
            "stable_reversal_horizons": tuple(
                entry.horizon_ms for entry in report.entries if entry.stable_reversal
            ),
            "output_root": str(args.output_root),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
