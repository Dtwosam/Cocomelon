from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_dataset import load_candle_source
from cocomelon.research.historical_trade_archive import (
    ARCHIVE_SOURCE,
    HistoricalTradeArchiveError,
    aggregate_trades_to_candles,
    merge_archived_trades,
    parse_node_fills_by_block_jsonl,
    write_archive_candle_source,
)

BTC = MarketId(dex="", coin="BTC")
ETH = MarketId(dex="", coin="ETH")
FIVE = 300_000


def _fill(
    *,
    coin: str,
    tid: int,
    time: int,
    px: str,
    sz: str,
    crossed: bool,
    side: str,
) -> dict[str, object]:
    return {
        "coin": coin,
        "px": px,
        "sz": sz,
        "side": side,
        "time": time,
        "startPosition": "0",
        "dir": "Open Long",
        "closedPnl": "0",
        "hash": "0xabc",
        "oid": tid + 1000,
        "crossed": crossed,
        "fee": "0.01",
        "feeToken": "USDC",
        "tid": tid,
    }


def _archive_bytes(events: list[list[object]]) -> bytes:
    payload = {"block_number": 123, "events": events}
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def test_archive_parser_deduplicates_participant_fills_by_tid_and_keeps_taker() -> None:
    data = _archive_bytes(
        [
            [
                "0xmaker",
                _fill(
                    coin="BTC",
                    tid=7,
                    time=1000,
                    px="100",
                    sz="2",
                    crossed=False,
                    side="A",
                ),
            ],
            [
                "0xtaker",
                _fill(
                    coin="BTC",
                    tid=7,
                    time=1000,
                    px="100",
                    sz="2",
                    crossed=True,
                    side="B",
                ),
            ],
            [
                "0xother",
                _fill(
                    coin="ETH",
                    tid=8,
                    time=1001,
                    px="200",
                    sz="3",
                    crossed=True,
                    side="B",
                ),
            ],
        ]
    )

    trades = parse_node_fills_by_block_jsonl(data, markets=(BTC,))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.market == BTC
    assert trade.tid == 7
    assert trade.crossed is True
    assert trade.side == "B"
    assert trade.px == Decimal("100")
    assert trade.sz == Decimal("2")
    assert trade.source == ARCHIVE_SOURCE


def test_archive_parser_rejects_conflicting_duplicate_trade_identity() -> None:
    data = _archive_bytes(
        [
            [
                "0xmaker",
                _fill(
                    coin="BTC",
                    tid=7,
                    time=1000,
                    px="100",
                    sz="2",
                    crossed=False,
                    side="A",
                ),
            ],
            [
                "0xtaker",
                _fill(
                    coin="BTC",
                    tid=7,
                    time=1000,
                    px="101",
                    sz="2",
                    crossed=True,
                    side="B",
                ),
            ],
        ]
    )

    with pytest.raises(
        HistoricalTradeArchiveError,
        match="CONFLICTING_TRADE_DUPLICATE",
    ):
        parse_node_fills_by_block_jsonl(data, markets=(BTC,))


def test_archive_merge_deduplicates_tid_across_hourly_files() -> None:
    first = parse_node_fills_by_block_jsonl(
        _archive_bytes(
            [[
                "0xtaker",
                _fill(
                    coin="BTC",
                    tid=9,
                    time=FIVE - 1,
                    px="100",
                    sz="1",
                    crossed=True,
                    side="B",
                ),
            ]]
        ),
        markets=(BTC,),
    )
    second = parse_node_fills_by_block_jsonl(
        _archive_bytes(
            [[
                "0xmaker",
                _fill(
                    coin="BTC",
                    tid=9,
                    time=FIVE - 1,
                    px="100",
                    sz="1",
                    crossed=False,
                    side="A",
                ),
            ]]
        ),
        markets=(BTC,),
    )

    merged = merge_archived_trades((first, second))

    assert len(merged) == 1
    assert merged[0].crossed is True


def test_archive_trades_aggregate_to_exact_ohlcv_and_trade_count() -> None:
    data = _archive_bytes(
        [
            [
                "0xa",
                _fill(
                    coin="BTC",
                    tid=1,
                    time=1000,
                    px="100",
                    sz="1.5",
                    crossed=True,
                    side="B",
                ),
            ],
            [
                "0xb",
                _fill(
                    coin="BTC",
                    tid=2,
                    time=2000,
                    px="103",
                    sz="2",
                    crossed=True,
                    side="B",
                ),
            ],
            [
                "0xc",
                _fill(
                    coin="BTC",
                    tid=3,
                    time=3000,
                    px="99",
                    sz="0.5",
                    crossed=True,
                    side="A",
                ),
            ],
            [
                "0xd",
                _fill(
                    coin="BTC",
                    tid=4,
                    time=FIVE + 1000,
                    px="101",
                    sz="3",
                    crossed=True,
                    side="B",
                ),
            ],
        ]
    )
    trades = parse_node_fills_by_block_jsonl(data, markets=(BTC,))

    candles = aggregate_trades_to_candles(
        trades,
        market=BTC,
        interval="5m",
        start_ms=0,
        end_ms=FIVE,
        received_at_ms=10_000_000,
    )

    assert len(candles) == 2
    first = candles[0]
    assert first.start_ms == 0
    assert first.end_ms == FIVE - 1
    assert first.open_px == Decimal("100")
    assert first.high_px == Decimal("103")
    assert first.low_px == Decimal("99")
    assert first.close_px == Decimal("99")
    assert first.volume == Decimal("4.0")
    assert first.trade_count == 3
    assert first.source == ARCHIVE_SOURCE

    second = candles[1]
    assert second.open_px == second.high_px == second.low_px == second.close_px
    assert second.close_px == Decimal("101")
    assert second.volume == Decimal("3")
    assert second.trade_count == 1


def test_archive_candle_source_is_compatible_with_existing_dataset_loader(
    tmp_path: Path,
) -> None:
    data = _archive_bytes(
        [
            [
                "0xa",
                _fill(
                    coin="BTC",
                    tid=1,
                    time=1000,
                    px="100",
                    sz="1",
                    crossed=True,
                    side="B",
                ),
            ],
            [
                "0xb",
                _fill(
                    coin="BTC",
                    tid=2,
                    time=FIVE + 1000,
                    px="101",
                    sz="2",
                    crossed=True,
                    side="B",
                ),
            ],
        ]
    )
    trades = parse_node_fills_by_block_jsonl(data, markets=(BTC,))
    candles = aggregate_trades_to_candles(
        trades,
        market=BTC,
        interval="5m",
        start_ms=0,
        end_ms=FIVE,
        received_at_ms=20_000_000,
    )
    raw_digest = hashlib.sha256(b"compressed archive bytes").hexdigest()

    manifest = write_archive_candle_source(
        tmp_path,
        candles=candles,
        market=BTC,
        interval="5m",
        start_ms=0,
        end_ms=FIVE,
        raw_archive_digests=(raw_digest,),
    )
    loaded_manifest, loaded = load_candle_source(tmp_path)

    assert loaded_manifest == manifest
    assert loaded == candles
    assert manifest.complete_requested_grid is True
    assert manifest.gap_ranges == ()


def test_archive_candle_source_preserves_real_empty_interval_as_gap(
    tmp_path: Path,
) -> None:
    data = _archive_bytes(
        [[
            "0xa",
            _fill(
                coin="BTC",
                tid=1,
                time=1000,
                px="100",
                sz="1",
                crossed=True,
                side="B",
            ),
        ]]
    )
    trades = parse_node_fills_by_block_jsonl(data, markets=(BTC,))
    candles = aggregate_trades_to_candles(
        trades,
        market=BTC,
        interval="5m",
        start_ms=0,
        end_ms=FIVE,
        received_at_ms=20_000_000,
    )

    manifest = write_archive_candle_source(
        tmp_path,
        candles=candles,
        market=BTC,
        interval="5m",
        start_ms=0,
        end_ms=FIVE,
        raw_archive_digests=(hashlib.sha256(data).hexdigest(),),
    )

    assert manifest.complete_requested_grid is False
    assert manifest.gap_ranges == ((FIVE, FIVE),)
    assert len(candles) == 1
