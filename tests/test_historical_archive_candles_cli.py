from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.historical_archive_candles_cli import ingest_archive_candles
from cocomelon.research.historical_dataset import load_candle_source
from cocomelon.research.historical_trade_archive import HistoricalTradeArchiveError

lz4 = pytest.importorskip("lz4.frame")

BTC = MarketId(dex="", coin="BTC")
FIVE = 300_000


def _fill(
    *,
    tid: int,
    time: int,
    px: str,
    sz: str,
    crossed: bool,
    side: str,
) -> dict[str, object]:
    return {
        "coin": "BTC",
        "px": px,
        "sz": sz,
        "side": side,
        "time": time,
        "startPosition": "0",
        "dir": "Open Long",
        "closedPnl": "0",
        "hash": "0xabc",
        "oid": tid + 100,
        "crossed": crossed,
        "fee": "0.01",
        "feeToken": "USDC",
        "tid": tid,
    }


def _write_archive(path: Path, events: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"block_number": 123, "events": events},
        separators=(",", ":"),
    ) + "\n"
    with lz4.open(path, mode="wt", encoding="utf-8") as handle:
        handle.write(payload)


def test_archive_cli_streams_lz4_into_existing_historical_source_contract(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    _write_archive(
        archive_root / "hourly" / "20260907" / "0.lz4",
        [
            [
                "0xmaker",
                _fill(
                    tid=1,
                    time=1_000,
                    px="100",
                    sz="1",
                    crossed=False,
                    side="A",
                ),
            ],
            [
                "0xtaker",
                _fill(
                    tid=1,
                    time=1_000,
                    px="100",
                    sz="1",
                    crossed=True,
                    side="B",
                ),
            ],
            [
                "0xtaker2",
                _fill(
                    tid=2,
                    time=FIVE + 1_000,
                    px="101",
                    sz="2",
                    crossed=True,
                    side="B",
                ),
            ],
        ],
    )
    source_root = tmp_path / "sources"

    result = ingest_archive_candles(
        archive_root=archive_root,
        source_root=source_root,
        markets=(BTC,),
        intervals=("5m", "15m"),
        start_ms=0,
        end_ms=FIVE,
        received_at_ms=20_000_000,
    )

    assert result["archive_file_count"] == 1
    assert result["parsed_trade_count"] == 2
    assert result["candle_manifests"] == 2
    assert result["funding_manifests"] == 0
    assert len(result["archive_manifest_id"]) == 24

    manifest, candles = load_candle_source(
        source_root / "BTC" / "candles" / "5m"
    )
    assert manifest.market == "BTC"
    assert manifest.interval == "5m"
    assert manifest.complete_requested_grid is True
    assert [item.close_px for item in candles] == [100, 101]
    assert [item.trade_count for item in candles] == [1, 1]

    fifteen_manifest, fifteen = load_candle_source(
        source_root / "BTC" / "candles" / "15m"
    )
    assert fifteen_manifest.interval == "15m"
    assert fifteen_manifest.requested_start_ms == 0
    assert fifteen_manifest.requested_end_ms == 0
    assert len(fifteen) == 1
    assert fifteen[0].open_px == 100
    assert fifteen[0].close_px == 101
    assert fifteen[0].volume == 3
    assert fifteen[0].trade_count == 2

    coverage = json.loads(
        (source_root / "coverage.json").read_text(encoding="utf-8")
    )
    assert {item["interval"] for item in coverage["sources"]} == {"5m", "15m"}


def test_archive_manifest_identity_does_not_depend_on_local_root(
    tmp_path: Path,
) -> None:
    first_archive = tmp_path / "first" / "archive"
    second_archive = tmp_path / "second" / "archive"
    relative = Path("hourly") / "20260907" / "0.lz4"
    events = [[
        "0xtaker",
        _fill(
            tid=1,
            time=1_000,
            px="100",
            sz="1",
            crossed=True,
            side="B",
        ),
    ]]
    _write_archive(first_archive / relative, events)
    _write_archive(second_archive / relative, events)

    first = ingest_archive_candles(
        archive_root=first_archive,
        source_root=tmp_path / "source-a",
        markets=(BTC,),
        intervals=("5m",),
        start_ms=0,
        end_ms=0,
        received_at_ms=20_000_000,
    )
    second = ingest_archive_candles(
        archive_root=second_archive,
        source_root=tmp_path / "source-b",
        markets=(BTC,),
        intervals=("5m",),
        start_ms=0,
        end_ms=0,
        received_at_ms=20_000_000,
    )

    assert first["archive_manifest_id"] == second["archive_manifest_id"]
    first_manifest = json.loads(
        (tmp_path / "source-a" / "archive_ingest.json").read_text(encoding="utf-8")
    )
    second_manifest = json.loads(
        (tmp_path / "source-b" / "archive_ingest.json").read_text(encoding="utf-8")
    )
    assert first_manifest == second_manifest
    assert "archive_root" not in first_manifest



def test_archive_cli_rejects_start_not_aligned_to_requested_interval(
    tmp_path: Path,
) -> None:
    archive_root = tmp_path / "archive"
    _write_archive(
        archive_root / "hourly" / "20260907" / "0.lz4",
        [[
            "0xtaker",
            _fill(
                tid=1,
                time=FIVE + 1_000,
                px="100",
                sz="1",
                crossed=True,
                side="B",
            ),
        ]],
    )

    with pytest.raises(
        HistoricalTradeArchiveError,
        match="REQUEST_START_GRID_MISALIGNED",
    ):
        ingest_archive_candles(
            archive_root=archive_root,
            source_root=tmp_path / "sources",
            markets=(BTC,),
            intervals=("15m",),
            start_ms=FIVE,
            end_ms=3 * FIVE,
            received_at_ms=20_000_000,
        )
