from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from cocomelon.domain.market import MarketId
from cocomelon.replay.compaction import ResearchDependencyError
from cocomelon.research.historical_dataset import (
    HistoricalDatasetIntegrityError,
    build_training_rows_from_source_root,
    export_training_dataset,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-historical-dataset",
        description="Build authenticated point-in-time directional training datasets",
    )
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--market", required=True, action="append", type=_parse_market)
    parser.add_argument("--horizon-ms", required=True, action="append", type=int)
    return parser


def build_historical_dataset(
    *,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
) -> dict[str, object]:
    if any(value <= 0 for value in horizons_ms):
        raise ValueError("horizon-ms values must be positive")
    rows = build_training_rows_from_source_root(
        source_root,
        markets=markets,
        horizons_ms=horizons_ms,
    )
    manifest = export_training_dataset(rows, output_root)
    return {
        "command": "build-historical-dataset",
        "dataset_id": manifest.dataset_id,
        "horizons_ms": manifest.horizons_ms,
        "markets": manifest.markets,
        "output_root": str(output_root),
        "row_count": manifest.row_count,
        "source_manifest_count": len(manifest.source_manifest_ids),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = build_historical_dataset(
            source_root=args.source_root,
            output_root=args.output_root,
            markets=args.market,
            horizons_ms=args.horizon_ms,
        )
    except (
        OSError,
        ValueError,
        HistoricalDatasetIntegrityError,
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
