from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_backfill import (
    HistoricalBackfillError,
    backfill_funding,
)

MARKET = MarketId(dex="", coin="ETH")


def _raw_funding(time_ms: int, rate: str) -> dict[str, object]:
    return {
        "coin": "ETH",
        "fundingRate": rate,
        "premium": "0.0001",
        "time": time_ms,
    }


class FakeFundingClient:
    def __init__(self, pages: dict[tuple[int, int], list[dict[str, object]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[int, int]] = []

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        assert market == MARKET
        assert end_ms is not None
        self.calls.append((start_ms, end_ms))
        return self.pages[(start_ms, end_ms)]


class NoNetworkFundingClient:
    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        raise AssertionError("resume must reuse cached funding pages")


def _clock(values: list[int]) -> Callable[[], int]:
    remaining = iter(values)
    return lambda: next(remaining)


def test_backfill_funding_pages_forward_from_last_observed_timestamp(
    tmp_path: Path,
) -> None:
    client = FakeFundingClient(
        {
            (1_000, 10_000): [
                _raw_funding(1_000, "0.0001"),
                _raw_funding(2_000, "0.0002"),
            ],
            (2_001, 10_000): [_raw_funding(5_000, "-0.0001")],
        }
    )

    result = backfill_funding(
        client,
        market=MARKET,
        start_ms=1_000,
        end_ms=10_000,
        root=tmp_path,
        clock_ms=_clock([20_000, 20_001]),
        page_limit=2,
    )

    assert client.calls == [(1_000, 10_000), (2_001, 10_000)]
    assert [item.time_ms for item in result.rates] == [1_000, 2_000, 5_000]
    assert result.manifest.market == "ETH"
    assert result.manifest.requested_start_ms == 1_000
    assert result.manifest.requested_end_ms == 10_000
    assert result.manifest.page_count == 2
    assert result.manifest.rate_count == 3
    assert result.manifest.first_time_ms == 1_000
    assert result.manifest.last_time_ms == 5_000
    assert result.manifest.pagination_exhausted is True
    assert len(result.manifest.normalized_sha256) == 64
    assert len(result.manifest.manifest_id) == 24

    rows = [
        json.loads(line)
        for line in (tmp_path / "funding.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["time_ms"] for row in rows] == [1_000, 2_000, 5_000]
    assert [row["funding_rate"] for row in rows] == ["0.0001", "0.0002", "-0.0001"]
    assert (tmp_path / "raw" / "funding-00000.json").exists()
    assert (tmp_path / "raw" / "funding-00001.json").exists()
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["manifest_id"] == result.manifest.manifest_id


def test_backfill_funding_resume_reuses_cached_pages_without_network(
    tmp_path: Path,
) -> None:
    pages = {
        (1_000, 10_000): [
            _raw_funding(1_000, "0.0001"),
            _raw_funding(2_000, "0.0002"),
        ],
        (2_001, 10_000): [_raw_funding(5_000, "-0.0001")],
    }
    first = backfill_funding(
        FakeFundingClient(pages),
        market=MARKET,
        start_ms=1_000,
        end_ms=10_000,
        root=tmp_path,
        clock_ms=_clock([20_000, 20_001]),
        page_limit=2,
    )

    second = backfill_funding(
        NoNetworkFundingClient(),
        market=MARKET,
        start_ms=1_000,
        end_ms=10_000,
        root=tmp_path,
        clock_ms=lambda: 99_999,
        page_limit=2,
    )

    assert second.manifest == first.manifest
    assert second.rates == first.rates


def test_backfill_funding_empty_first_page_is_valid_exhausted_history(
    tmp_path: Path,
) -> None:
    result = backfill_funding(
        FakeFundingClient({(1_000, 10_000): []}),
        market=MARKET,
        start_ms=1_000,
        end_ms=10_000,
        root=tmp_path,
        clock_ms=lambda: 20_000,
        page_limit=500,
    )

    assert result.rates == ()
    assert result.manifest.rate_count == 0
    assert result.manifest.first_time_ms is None
    assert result.manifest.last_time_ms is None
    assert result.manifest.pagination_exhausted is True


def test_backfill_funding_rejects_non_advancing_full_page(
    tmp_path: Path,
) -> None:
    client = FakeFundingClient(
        {
            (1_000, 10_000): [
                _raw_funding(1_000, "0.0001"),
                _raw_funding(2_000, "0.0002"),
            ],
            (2_001, 10_000): [
                _raw_funding(2_001, "0.0003"),
                _raw_funding(2_001, "0.0003"),
            ],
        }
    )

    with pytest.raises((HistoricalBackfillError, ValueError)):
        backfill_funding(
            client,
            market=MARKET,
            start_ms=1_000,
            end_ms=10_000,
            root=tmp_path,
            clock_ms=_clock([20_000, 20_001]),
            page_limit=2,
        )


def test_backfill_funding_rejects_rows_outside_requested_bounds(
    tmp_path: Path,
) -> None:
    client = FakeFundingClient(
        {(1_000, 10_000): [_raw_funding(999, "0.0001")]}
    )

    with pytest.raises(HistoricalBackfillError, match="FUNDING_OUTSIDE_REQUEST_WINDOW"):
        backfill_funding(
            client,
            market=MARKET,
            start_ms=1_000,
            end_ms=10_000,
            root=tmp_path,
            clock_ms=lambda: 20_000,
            page_limit=500,
        )


def test_backfill_funding_rejects_cached_page_for_changed_end_bound(
    tmp_path: Path,
) -> None:
    backfill_funding(
        FakeFundingClient({(1_000, 10_000): []}),
        market=MARKET,
        start_ms=1_000,
        end_ms=10_000,
        root=tmp_path,
        clock_ms=lambda: 20_000,
        page_limit=500,
    )

    with pytest.raises(HistoricalBackfillError, match="CACHED_PAGE_REQUEST_MISMATCH"):
        backfill_funding(
            NoNetworkFundingClient(),
            market=MARKET,
            start_ms=1_000,
            end_ms=20_000,
            root=tmp_path,
            clock_ms=lambda: 20_001,
            page_limit=500,
        )


def test_backfill_funding_rejects_invalid_page_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="page_limit"):
        backfill_funding(
            NoNetworkFundingClient(),
            market=MARKET,
            start_ms=1_000,
            end_ms=10_000,
            root=tmp_path,
            clock_ms=lambda: 20_000,
            page_limit=0,
        )
