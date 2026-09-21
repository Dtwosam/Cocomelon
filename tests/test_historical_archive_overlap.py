from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import Candle, MarketId
from cocomelon.research.historical_archive_overlap import (
    HistoricalArchiveOverlapError,
    validate_archive_native_overlap,
)
from cocomelon.research.historical_trade_archive import (
    ARCHIVE_SOURCE,
    write_archive_candle_source,
)

BTC = MarketId(dex="", coin="BTC")
FIVE = 300_000


def _archive_candle(start_ms: int, px: str) -> Candle:
    value = Decimal(px)
    return Candle(
        market=BTC,
        interval="5m",
        start_ms=start_ms,
        end_ms=start_ms + FIVE - 1,
        open_px=value,
        high_px=value,
        low_px=value,
        close_px=value,
        volume=Decimal("10"),
        trade_count=5,
        source=ARCHIVE_SOURCE,
        received_at_ms=10_000_000,
        schema_version=1,
    )


def _raw_candle(start_ms: int, px: str) -> dict[str, object]:
    return {
        "t": start_ms,
        "T": start_ms + FIVE - 1,
        "s": "BTC",
        "i": "5m",
        "o": px,
        "c": px,
        "h": px,
        "l": px,
        "v": "10",
        "n": 5,
    }


def _write_archive_source(root: Path) -> None:
    candles = tuple(
        _archive_candle(index * FIVE, str(100 + index))
        for index in range(4)
    )
    write_archive_candle_source(
        root / "BTC" / "candles" / "5m",
        candles=candles,
        market=BTC,
        interval="5m",
        start_ms=0,
        end_ms=3 * FIVE,
        raw_archive_digests=(hashlib.sha256(b"archive").hexdigest(),),
    )


class FakeCandleClient:
    def __init__(self, *, mismatch: bool = False) -> None:
        self.mismatch = mismatch
        self.calls: list[tuple[int, int]] = []

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        assert market == BTC
        assert interval == "5m"
        self.calls.append((start_ms, end_ms))
        rows = []
        cursor = start_ms
        while cursor <= end_ms:
            index = cursor // FIVE
            px = str(100 + index)
            if self.mismatch and cursor == end_ms:
                px = "999"
            rows.append(_raw_candle(cursor, px))
            cursor += FIVE
        return rows


def test_native_overlap_uses_last_requested_candles_and_persists_sources(
    tmp_path: Path,
) -> None:
    _write_archive_source(tmp_path)
    client = FakeCandleClient()

    report = validate_archive_native_overlap(
        client,
        source_root=tmp_path,
        markets=(BTC,),
        intervals=("5m",),
        overlap_candles=2,
        clock_ms=lambda: 20_000_000,
    )

    assert client.calls == [(2 * FIVE, 3 * FIVE)]
    assert report.exact is True
    assert report.compared_count == 2
    assert report.entries[0].exact_match_count == 2
    assert report.entries[0].missing_archive_starts == ()
    assert report.entries[0].missing_native_starts == ()
    assert (tmp_path / "archive_native_overlap.json").is_file()
    assert (
        tmp_path
        / "archive_native_overlap"
        / "BTC"
        / "candles"
        / "5m"
        / "manifest.json"
    ).is_file()

    payload = json.loads(
        (tmp_path / "archive_native_overlap.json").read_text(encoding="utf-8")
    )
    assert payload["exact"] is True
    assert payload["report_id"] == report.report_id


def test_native_overlap_persists_mismatch_report_before_failing_closed(
    tmp_path: Path,
) -> None:
    _write_archive_source(tmp_path)

    with pytest.raises(
        HistoricalArchiveOverlapError,
        match="ARCHIVE_NATIVE_OVERLAP_MISMATCH",
    ):
        validate_archive_native_overlap(
            FakeCandleClient(mismatch=True),
            source_root=tmp_path,
            markets=(BTC,),
            intervals=("5m",),
            overlap_candles=2,
            clock_ms=lambda: 20_000_000,
        )

    payload = json.loads(
        (tmp_path / "archive_native_overlap.json").read_text(encoding="utf-8")
    )
    assert payload["exact"] is False
    entry = payload["entries"][0]
    assert entry["compared_count"] == 2
    assert entry["exact_match_count"] == 1
    assert entry["mismatches"]


def test_native_overlap_rejects_overlap_larger_than_native_page_limit(
    tmp_path: Path,
) -> None:
    _write_archive_source(tmp_path)

    with pytest.raises(ValueError, match="overlap_candles must fit"):
        validate_archive_native_overlap(
            FakeCandleClient(),
            source_root=tmp_path,
            markets=(BTC,),
            intervals=("5m",),
            overlap_candles=5_001,
            clock_ms=lambda: 20_000_000,
        )
