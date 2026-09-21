from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_backfill import backfill_candles, backfill_funding
from cocomelon.research.historical_dataset import (
    HistoricalDatasetIntegrityError,
    build_training_rows_from_source_root,
    export_training_dataset,
    load_candle_source,
    load_funding_source,
)

MARKET = MarketId(dex="", coin="ETH")
FIVE = 300_000
FIFTEEN = 900_000
HOUR = 3_600_000


def _clock(values: list[int]) -> Callable[[], int]:
    remaining = iter(values)
    return lambda: next(remaining)


def _raw_candle(
    market: MarketId,
    *,
    interval: str,
    start_ms: int,
    close: int,
) -> dict[str, object]:
    width = FIVE if interval == "5m" else FIFTEEN
    return {
        "t": start_ms,
        "T": start_ms + width - 1,
        "s": market.wire_name,
        "i": interval,
        "o": str(close - 1),
        "c": str(close),
        "h": str(close + 1),
        "l": str(close - 2),
        "v": str(100 + close),
        "n": 10,
    }


class FakeClient:
    def __init__(self, market: MarketId) -> None:
        self.market = market

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        assert market == self.market
        width = FIVE if interval == "5m" else FIFTEEN
        return [
            _raw_candle(
                market,
                interval=interval,
                start_ms=timestamp,
                close=100 + index,
            )
            for index, timestamp in enumerate(range(start_ms, end_ms + 1, width))
        ]

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        assert market == self.market
        assert end_ms is not None
        return [
            {
                "coin": market.wire_name,
                "fundingRate": str(0.0001 + index * 0.0001),
                "premium": str(0.0002 + index * 0.0001),
                "time": timestamp,
            }
            for index, timestamp in enumerate(range(start_ms, end_ms + 1, HOUR))
        ]


def _build_source_root(tmp_path: Path, market: MarketId = MARKET) -> Path:
    root = tmp_path / "sources"
    client = FakeClient(market)
    market_root = root / market.canonical
    backfill_candles(
        client,
        market=market,
        interval="5m",
        start_ms=0,
        end_ms=24 * FIVE,
        root=market_root / "candles" / "5m",
        clock_ms=lambda: 99_000_000,
    )
    backfill_candles(
        client,
        market=market,
        interval="15m",
        start_ms=0,
        end_ms=8 * FIFTEEN,
        root=market_root / "candles" / "15m",
        clock_ms=lambda: 99_000_001,
    )
    backfill_funding(
        client,
        market=market,
        start_ms=0,
        end_ms=2 * HOUR,
        root=market_root / "funding",
        clock_ms=lambda: 99_000_002,
    )
    return root


def test_source_reader_authenticates_candle_and_funding_manifests(tmp_path: Path) -> None:
    root = _build_source_root(tmp_path)
    candle_manifest, candles = load_candle_source(root / "ETH" / "candles" / "5m")
    funding_manifest, rates = load_funding_source(root / "ETH" / "funding")

    assert candle_manifest.market == "ETH"
    assert candle_manifest.candle_count == len(candles) == 25
    assert funding_manifest.market == "ETH"
    assert funding_manifest.funding_count == len(rates) == 3
    assert candles[0].market == MARKET
    assert rates[-1].time_ms == 2 * HOUR


def test_source_reader_rejects_mutated_normalized_payload(tmp_path: Path) -> None:
    root = _build_source_root(tmp_path)
    path = root / "ETH" / "candles" / "5m" / "candles.jsonl"
    path.write_bytes(path.read_bytes() + b"{}\n")

    with pytest.raises(HistoricalDatasetIntegrityError, match="sha256"):
        load_candle_source(root / "ETH" / "candles" / "5m")


def test_build_training_rows_from_source_root_uses_exact_horizons(tmp_path: Path) -> None:
    root = _build_source_root(tmp_path)

    rows = build_training_rows_from_source_root(
        root,
        markets=(MARKET,),
        horizons_ms=(FIVE, 3 * FIVE),
    )

    assert rows
    assert {row.market for row in rows} == {MARKET}
    assert {row.horizon_ms for row in rows} == {FIVE, 3 * FIVE}
    assert all(row.feature.availability_basis == "exchange_timestamp" for row in rows)
    assert all(row.feature.source_manifest_ids for row in rows)


def test_export_training_dataset_writes_versioned_parquet_and_manifest(tmp_path: Path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    root = _build_source_root(tmp_path)
    rows = build_training_rows_from_source_root(
        root,
        markets=(MARKET,),
        horizons_ms=(FIVE,),
    )

    manifest = export_training_dataset(rows, tmp_path / "dataset")

    assert manifest.row_count == len(rows)
    assert manifest.markets == ("ETH",)
    assert manifest.horizons_ms == (FIVE,)
    assert len(manifest.dataset_id) == 64
    assert len(manifest.logical_sha256) == 64
    assert len(manifest.output_sha256) == 64

    manifest_payload = json.loads(
        (tmp_path / "dataset" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_payload["dataset_id"] == manifest.dataset_id
    assert manifest_payload["output_sha256"] == manifest.output_sha256

    table = parquet.read_table(tmp_path / "dataset" / "training.parquet")
    assert table.num_rows == len(rows)
    assert "long_gross_return" in table.column_names
    assert "short_gross_return" in table.column_names
    assert "unavailable_features_json" in table.column_names



def test_training_rows_reject_horizon_off_the_5m_grid(tmp_path: Path) -> None:
    root = _build_source_root(tmp_path)

    with pytest.raises(ValueError, match="5m base interval"):
        build_training_rows_from_source_root(
            root,
            markets=(MARKET,),
            horizons_ms=(420_000,),
        )
