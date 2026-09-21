from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.historical_backfill_cli import _parse_market, acquire_historical_sources

MARKET = MarketId(dex="", coin="ETH")
STEP = 300_000


def _raw_candle(start_ms: int) -> dict[str, object]:
    return {
        "t": start_ms,
        "T": start_ms + STEP - 1,
        "s": "ETH",
        "i": "5m",
        "o": "100",
        "c": "100",
        "h": "100",
        "l": "100",
        "v": "10",
        "n": 5,
    }


class FakeHistoricalClient:
    def __init__(self) -> None:
        self.candle_calls: list[tuple[str, int, int]] = []
        self.funding_calls: list[tuple[int, int | None]] = []

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        assert market == MARKET
        assert interval == "5m"
        self.candle_calls.append((interval, start_ms, end_ms))
        return [_raw_candle(0), _raw_candle(STEP)]

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        assert market == MARKET
        self.funding_calls.append((start_ms, end_ms))
        return [
            {
                "coin": "ETH",
                "fundingRate": "0.0001",
                "premium": "0.0002",
                "time": 0,
            }
        ]


def _clock(values: list[int]) -> Callable[[], int]:
    remaining = iter(values)
    return lambda: next(remaining)


def test_parse_market_supports_native_and_hip3_canonical_names() -> None:
    assert _parse_market("BTC") == MarketId(dex="", coin="BTC")
    assert _parse_market("xyz:NVDA") == MarketId(dex="xyz", coin="NVDA")


def test_acquisition_command_deduplicates_inputs_and_writes_coverage(
    tmp_path: Path,
) -> None:
    client = FakeHistoricalClient()

    result = acquire_historical_sources(
        client,
        root=tmp_path,
        markets=(MARKET, MARKET),
        intervals=("5m", "5m"),
        start_ms=0,
        end_ms=STEP,
        clock_ms=_clock([10_000_000, 10_000_001]),
    )

    assert client.candle_calls == [("5m", 0, STEP)]
    assert client.funding_calls == [(0, STEP)]
    assert result["market_count"] == 1
    assert result["candle_manifests"] == 1
    assert result["funding_manifests"] == 1
    assert result["source_count"] == 2

    coverage_path = tmp_path / "coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert coverage["report_id"] == result["report_id"]
    assert [source["kind"] for source in coverage["sources"]] == ["candles", "funding"]
    assert (tmp_path / "ETH" / "candles" / "5m" / "manifest.json").exists()
    assert (tmp_path / "ETH" / "funding" / "manifest.json").exists()
