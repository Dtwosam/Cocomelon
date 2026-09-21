from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from cocomelon.research.historical_backfill import (
    HistoricalBackfillError,
    backfill_candles,
)

from cocomelon.domain.market import MarketId

MARKET = MarketId(dex="", coin="ETH")
STEP = 300_000


def _raw_candle(start_ms: int, close: str) -> dict[str, object]:
    return {
        "t": start_ms,
        "T": start_ms + STEP - 1,
        "s": "ETH",
        "i": "5m",
        "o": close,
        "c": close,
        "h": close,
        "l": close,
        "v": "10",
        "n": 5,
    }


class FakeClient:
    def __init__(self, pages: dict[tuple[int, int], list[dict[str, object]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, int, int]] = []

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
        self.calls.append((interval, start_ms, end_ms))
        return self.pages[(start_ms, end_ms)]


class NoNetworkClient:
    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        raise AssertionError("resume must reuse cached raw pages")


def _clock(values: list[int]) -> Callable[[], int]:
    remaining = iter(values)
    return lambda: next(remaining)


def test_backfill_candles_persists_raw_pages_normalized_jsonl_and_manifest(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            (0, STEP): [_raw_candle(0, "100"), _raw_candle(STEP, "101")],
            (2 * STEP, 3 * STEP): [
                _raw_candle(2 * STEP, "102"),
                _raw_candle(3 * STEP, "103"),
            ],
        }
    )

    result = backfill_candles(
        client,
        market=MARKET,
        interval="5m",
        start_ms=0,
        end_ms=3 * STEP,
        root=tmp_path,
        clock_ms=_clock([10_000_000, 10_000_001]),
        max_candles=2,
    )

    assert client.calls == [
        ("5m", 0, STEP),
        ("5m", 2 * STEP, 3 * STEP),
    ]
    assert result.manifest.market == "ETH"
    assert result.manifest.interval == "5m"
    assert result.manifest.candle_count == 4
    assert result.manifest.page_count == 2
    assert result.manifest.gap_ranges == ()
    assert result.manifest.complete_requested_grid is True
    assert result.manifest.raw_page_digests
    assert len(result.manifest.normalized_sha256) == 64
    assert len(result.manifest.manifest_id) == 24

    normalized_path = tmp_path / "candles.jsonl"
    rows = [
        json.loads(line)
        for line in normalized_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["start_ms"] for row in rows] == [0, STEP, 2 * STEP, 3 * STEP]
    assert [row["close_px"] for row in rows] == ["100", "101", "102", "103"]

    manifest_payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["manifest_id"] == result.manifest.manifest_id
    assert manifest_payload["normalized_sha256"] == result.manifest.normalized_sha256
    assert (tmp_path / "raw" / "candles-00000.json").exists()
    assert (tmp_path / "raw" / "candles-00001.json").exists()


def test_backfill_candles_resume_reuses_cached_raw_pages_deterministically(
    tmp_path: Path,
) -> None:
    pages = {
        (0, STEP): [_raw_candle(0, "100"), _raw_candle(STEP, "101")],
        (2 * STEP, 3 * STEP): [
            _raw_candle(2 * STEP, "102"),
            _raw_candle(3 * STEP, "103"),
        ],
    }
    first = backfill_candles(
        FakeClient(pages),
        market=MARKET,
        interval="5m",
        start_ms=0,
        end_ms=3 * STEP,
        root=tmp_path,
        clock_ms=_clock([10_000_000, 10_000_001]),
        max_candles=2,
    )

    second = backfill_candles(
        NoNetworkClient(),
        market=MARKET,
        interval="5m",
        start_ms=0,
        end_ms=3 * STEP,
        root=tmp_path,
        clock_ms=lambda: 99_999_999,
        max_candles=2,
    )

    assert second.manifest == first.manifest
    assert second.candles == first.candles


def test_backfill_candles_reports_missing_requested_grid_without_inventing_data(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            (0, 3 * STEP): [
                _raw_candle(0, "100"),
                _raw_candle(STEP, "101"),
                _raw_candle(3 * STEP, "103"),
            ]
        }
    )

    result = backfill_candles(
        client,
        market=MARKET,
        interval="5m",
        start_ms=0,
        end_ms=3 * STEP,
        root=tmp_path,
        clock_ms=lambda: 10_000_000,
        max_candles=5_000,
    )

    assert [item.start_ms for item in result.candles] == [0, STEP, 3 * STEP]
    assert result.manifest.gap_ranges == ((2 * STEP, 2 * STEP),)
    assert result.manifest.complete_requested_grid is False


def test_backfill_candles_rejects_conflicting_duplicate_timestamps(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        {
            (0, STEP): [
                _raw_candle(0, "100"),
                _raw_candle(0, "101"),
            ]
        }
    )

    with pytest.raises((HistoricalBackfillError, ValueError)):
        backfill_candles(
            client,
            market=MARKET,
            interval="5m",
            start_ms=0,
            end_ms=STEP,
            root=tmp_path,
            clock_ms=lambda: 10_000_000,
            max_candles=5_000,
        )


def test_backfill_candles_rejects_cached_page_for_different_request(
    tmp_path: Path,
) -> None:
    backfill_candles(
        FakeClient({(0, STEP): [_raw_candle(0, "100"), _raw_candle(STEP, "101")]}),
        market=MARKET,
        interval="5m",
        start_ms=0,
        end_ms=STEP,
        root=tmp_path,
        clock_ms=lambda: 10_000_000,
        max_candles=5_000,
    )

    with pytest.raises(HistoricalBackfillError, match="CACHED_PAGE_REQUEST_MISMATCH"):
        backfill_candles(
            NoNetworkClient(),
            market=MARKET,
            interval="5m",
            start_ms=0,
            end_ms=2 * STEP,
            root=tmp_path,
            clock_ms=lambda: 10_000_001,
            max_candles=5_000,
        )
