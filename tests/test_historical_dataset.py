from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
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
BTC = MarketId(dex="", coin="BTC")
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
    width = {"5m": FIVE, "15m": FIFTEEN, "1h": HOUR}[interval]
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
        width = {"5m": FIVE, "15m": FIFTEEN, "1h": HOUR}[interval]
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
    backfill_candles(
        client,
        market=market,
        interval="1h",
        start_ms=0,
        end_ms=8 * HOUR,
        root=market_root / "candles" / "1h",
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


def test_training_rows_include_authenticated_same_anchor_basket_context(
    tmp_path: Path,
) -> None:
    root = _build_source_root(tmp_path, MARKET)
    _build_source_root(tmp_path, BTC)

    rows = build_training_rows_from_source_root(
        root,
        markets=(MARKET, BTC),
        horizons_ms=(FIVE,),
    )

    eth = next(
        row
        for row in rows
        if row.market == MARKET and row.feature.return_5m is not None
    )
    assert eth.feature.btc_return_5m == eth.feature.return_5m
    assert eth.feature.eth_return_5m == eth.feature.return_5m
    assert eth.feature.basket_return_count_5m == Decimal("2")
    assert eth.feature.basket_median_return_5m == eth.feature.return_5m
    assert eth.feature.relative_return_5m_vs_basket == Decimal("0")
    assert eth.feature.basket_return_dispersion_5m == Decimal("0")
    assert eth.feature.relative_return_zscore_5m_vs_basket is None
    assert eth.feature.schema_version == 3
    assert eth.schema_version == 3
    assert len(eth.feature.source_manifest_ids) >= 4


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
    assert "basket_median_return_5m" in table.column_names
    assert "basket_return_dispersion_5m" in table.column_names
    assert "relative_return_zscore_1h_vs_basket" in table.column_names
    assert "btc_return_1h" in table.column_names



def test_training_rows_reject_horizon_off_the_5m_grid(tmp_path: Path) -> None:
    root = _build_source_root(tmp_path)

    with pytest.raises(ValueError, match="5m base interval"):
        build_training_rows_from_source_root(
            root,
            markets=(MARKET,),
            horizons_ms=(420_000,),
        )



def test_build_training_rows_supports_15m_anchor_with_basket_context(
    tmp_path: Path,
) -> None:
    root = _build_source_root(tmp_path, MARKET)
    _build_source_root(tmp_path, BTC)

    rows = build_training_rows_from_source_root(
        root,
        markets=(MARKET, BTC),
        horizons_ms=(FIFTEEN, HOUR),
        anchor_interval="15m",
    )

    assert rows
    assert {row.outcome.interval for row in rows} == {"15m"}
    assert {row.horizon_ms for row in rows} == {FIFTEEN, HOUR}
    assert all(row.feature.return_5m is None for row in rows)
    enriched = next(
        row
        for row in rows
        if row.market == MARKET and row.feature.return_15m is not None
    )
    assert enriched.feature.schema_version == 3
    assert enriched.feature.btc_return_15m is not None
    assert enriched.feature.basket_return_count_15m == Decimal("2")
    assert enriched.feature.basket_return_dispersion_15m == Decimal("0")


def test_training_rows_reject_horizon_off_15m_grid(tmp_path: Path) -> None:
    root = _build_source_root(tmp_path)

    with pytest.raises(ValueError, match="15m base interval"):
        build_training_rows_from_source_root(
            root,
            markets=(MARKET,),
            horizons_ms=(FIVE,),
            anchor_interval="15m",
        )


def test_export_training_dataset_records_anchor_interval(tmp_path: Path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    root = _build_source_root(tmp_path)
    rows = build_training_rows_from_source_root(
        root,
        markets=(MARKET,),
        horizons_ms=(FIFTEEN,),
        anchor_interval="15m",
    )

    manifest = export_training_dataset(rows, tmp_path / "dataset-15m")
    table = parquet.read_table(tmp_path / "dataset-15m" / "training.parquet")

    assert manifest.anchor_interval == "15m"
    assert manifest.schema_version == 4
    assert manifest.converter_version == "historical-directional-training-v4-dispersion"
    assert set(table.column("anchor_interval").to_pylist()) == {"15m"}


def test_export_training_dataset_rejects_mixed_anchor_intervals(
    tmp_path: Path,
) -> None:
    root = _build_source_root(tmp_path)
    rows_5m = build_training_rows_from_source_root(
        root,
        markets=(MARKET,),
        horizons_ms=(FIFTEEN,),
        anchor_interval="5m",
    )
    rows_15m = build_training_rows_from_source_root(
        root,
        markets=(MARKET,),
        horizons_ms=(FIFTEEN,),
        anchor_interval="15m",
    )

    with pytest.raises(
        HistoricalDatasetIntegrityError,
        match="exactly one supported anchor interval",
    ):
        export_training_dataset(
            (rows_5m[0], rows_15m[0]),
            tmp_path / "dataset-mixed",
        )



def test_build_training_rows_supports_1h_anchor_with_basket_context(
    tmp_path: Path,
) -> None:
    root = _build_source_root(tmp_path, MARKET)
    _build_source_root(tmp_path, BTC)

    rows = build_training_rows_from_source_root(
        root,
        markets=(MARKET, BTC),
        horizons_ms=(HOUR, 4 * HOUR),
        anchor_interval="1h",
    )

    assert rows
    assert {row.outcome.interval for row in rows} == {"1h"}
    assert {row.horizon_ms for row in rows} == {HOUR, 4 * HOUR}
    assert all(row.feature.return_5m is None for row in rows)
    assert all(row.feature.return_15m is None for row in rows)
    assert all(row.feature.realized_vol_15m is None for row in rows)
    enriched = next(
        row
        for row in rows
        if row.market == MARKET and row.feature.return_1h is not None
    )
    assert enriched.feature.btc_return_1h is not None
    assert enriched.feature.eth_return_1h is not None
    assert enriched.feature.basket_return_count_1h == Decimal("2")
    assert enriched.feature.basket_return_dispersion_1h == Decimal("0")
    assert enriched.feature.trend_regime.value == "unknown"


def test_training_rows_reject_horizon_off_1h_grid(tmp_path: Path) -> None:
    root = _build_source_root(tmp_path)

    with pytest.raises(ValueError, match="1h base interval"):
        build_training_rows_from_source_root(
            root,
            markets=(MARKET,),
            horizons_ms=(FIFTEEN,),
            anchor_interval="1h",
        )


def test_export_training_dataset_records_1h_anchor_interval(tmp_path: Path) -> None:
    parquet = pytest.importorskip("pyarrow.parquet")
    root = _build_source_root(tmp_path)
    rows = build_training_rows_from_source_root(
        root,
        markets=(MARKET,),
        horizons_ms=(HOUR,),
        anchor_interval="1h",
    )

    manifest = export_training_dataset(rows, tmp_path / "dataset-1h")
    table = parquet.read_table(tmp_path / "dataset-1h" / "training.parquet")

    assert manifest.anchor_interval == "1h"
    assert manifest.schema_version == 4
    assert manifest.converter_version == "historical-directional-training-v4-dispersion"
    assert set(table.column("anchor_interval").to_pylist()) == {"1h"}
