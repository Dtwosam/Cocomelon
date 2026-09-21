from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.historical_experiment_cli import _parse_market, run_experiment
from cocomelon.research.historical_backfill import backfill_candles, backfill_funding
from cocomelon.research.historical_baselines import ExecutionCostAssumptions

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000
FIFTEEN = 900_000
HOUR = 3_600_000


class FakeClient:
    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        assert market == MARKET
        width = FIVE if interval == "5m" else FIFTEEN
        values: list[dict[str, object]] = []
        for index, timestamp in enumerate(range(start_ms, end_ms + 1, width)):
            close = Decimal("100") + Decimal(index) / Decimal("10")
            values.append(
                {
                    "t": timestamp,
                    "T": timestamp + width - 1,
                    "s": market.wire_name,
                    "i": interval,
                    "o": str(close - Decimal("0.05")),
                    "c": str(close),
                    "h": str(close + Decimal("0.10")),
                    "l": str(close - Decimal("0.10")),
                    "v": str(Decimal("1000") + Decimal(index)),
                    "n": 10 + index,
                }
            )
        return values

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        assert market == MARKET
        assert end_ms is not None
        return [
            {
                "coin": market.wire_name,
                "fundingRate": "0.0001",
                "premium": "0.0002",
                "time": timestamp,
            }
            for timestamp in range(start_ms, end_ms + 1, HOUR)
        ]


def _source_root(tmp_path: Path) -> Path:
    source_root = tmp_path / "sources"
    market_root = source_root / "ETH"
    client = FakeClient()
    backfill_candles(
        client,
        market=MARKET,
        interval="5m",
        start_ms=0,
        end_ms=36 * FIVE,
        root=market_root / "candles" / "5m",
        clock_ms=lambda: 99_000_000,
    )
    backfill_candles(
        client,
        market=MARKET,
        interval="15m",
        start_ms=0,
        end_ms=12 * FIFTEEN,
        root=market_root / "candles" / "15m",
        clock_ms=lambda: 99_000_001,
    )
    backfill_funding(
        client,
        market=MARKET,
        start_ms=0,
        end_ms=3 * HOUR,
        root=market_root / "funding",
        clock_ms=lambda: 99_000_002,
    )
    return source_root


def test_parse_market_supports_native_and_hip3() -> None:
    assert _parse_market("BTC") == MarketId(dex="", coin="BTC")
    assert _parse_market("xyz:NVDA") == MarketId(dex="xyz", coin="NVDA")


def test_run_experiment_builds_dataset_and_touched_report_end_to_end(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pyarrow.parquet")
    source_root = _source_root(tmp_path)
    output_root = tmp_path / "experiment"

    result = run_experiment(
        source_root=source_root,
        output_root=output_root,
        markets=(MARKET,),
        horizons_ms=(FIVE,),
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.0007"),
            round_trip_slippage_fraction=Decimal("0.0005"),
            funding_reserve_fraction_per_hour=Decimal("0.0001"),
        ),
        candidate_thresholds=(Decimal("0"), Decimal("0.001")),
        min_train_anchors=12,
        validation_anchors=6,
        test_anchors=6,
        step_anchors=6,
        embargo_anchors=1,
        min_state_samples=2,
        min_coin_samples=20,
        min_sample_count=2,
        min_validation_trades=1,
    )

    assert result["evidence_class"] == "touched_development"
    assert result["markets"] == ("ETH",)
    assert result["horizons_ms"] == (FIVE,)
    assert result["fold_count"] >= 1
    assert result["row_count"] > 0
    assert len(result["dataset_id"]) == 64
    assert len(result["report_id"]) == 64
    assert (output_root / "dataset" / "training.parquet").is_file()
    assert (output_root / "dataset" / "manifest.json").is_file()
    assert (output_root / "experiment.json").is_file()
