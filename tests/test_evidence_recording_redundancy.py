from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId, PerpMarketContext, PerpMarketMeta, PerpMarketSnapshot
from cocomelon.evidence.contracts import (
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
)
from cocomelon.evidence.recording import RecordingBootstrap, run_bounded_recording
from cocomelon.recorder import DurableRecorder

MARKET = MarketId("", "BTC")
RECEIVED = datetime(2026, 8, 25, tzinfo=UTC)


def _snapshot() -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=MARKET,
            wire_name="BTC",
            sz_decimals=5,
            max_leverage=40,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=MARKET,
            mark_px=Decimal("100"),
            mid_px=Decimal("100"),
            oracle_px=Decimal("100"),
            funding=Decimal("0"),
            open_interest=Decimal("1000"),
            day_ntl_vlm=Decimal("100000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("99"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=1_000,
        schema_version=1,
    )


def _bootstrap(config: EvidenceRecordingConfig) -> RecordingBootstrap:
    session = EvidenceRecordingSession(
        started_at_ms=1_000,
        recorder_code_revision="a" * 40,
        selected=(
            SelectedEvidenceMarket(
                market=MARKET,
                rank=1,
                feature_snapshot_id="feature-btc",
                score=Decimal("90"),
            ),
        ),
        recording_config_digest=config.config_digest,
        api_url=config.api_url,
        ws_url=config.ws_url,
        selection_policy_id=config.selection_policy_id,
    )
    return RecordingBootstrap(
        session=session,
        snapshots=(_snapshot(),),
        candles=(),
        funding_rates=(),
        subscriptions=({"type": "trades", "coin": "BTC"},),
    )


def _trade(tid: int, time_ms: int) -> dict[str, object]:
    return {
        "channel": "trades",
        "data": [
            {
                "coin": "BTC",
                "side": "B",
                "px": "100",
                "sz": "1",
                "hash": f"0x{tid}",
                "time": time_ms,
                "tid": tid,
                "users": ["a", "b"],
            }
        ],
    }


class ScriptedConnection:
    def __init__(
        self,
        rows: list[object],
        *,
        row_delays_seconds: list[float] | None = None,
    ) -> None:
        self._rows = list(rows)
        self._row_delays_seconds = (
            list(row_delays_seconds)
            if row_delays_seconds is not None
            else [0.0] * len(rows)
        )
        if len(self._row_delays_seconds) != len(self._rows):
            raise ValueError("row delays must match scripted rows")
        if any(delay < 0 for delay in self._row_delays_seconds):
            raise ValueError("row delays must be non-negative")
        self.closed = False

    async def send_json(self, message: dict[str, object]) -> None:
        return None

    async def recv_json(self) -> dict[str, object]:
        if self._rows:
            delay = self._row_delays_seconds.pop(0)
            if delay:
                await asyncio.sleep(delay)
            row = self._rows.pop(0)
            if isinstance(row, BaseException):
                raise row
            assert isinstance(row, dict)
            return row
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closed = True


class Reader:
    def perp_dexs(self) -> object:
        return [None]

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        return [
            {
                "universe": [
                    {
                        "name": "BTC",
                        "szDecimals": 5,
                        "maxLeverage": 40,
                        "isDelisted": False,
                    }
                ]
            },
            [
                {
                    "markPx": "100",
                    "midPx": "100",
                    "oraclePx": "100",
                    "funding": "0",
                    "openInterest": "1000",
                    "dayNtlVlm": "100000000",
                    "premium": "0",
                    "prevDayPx": "99",
                }
            ],
        ]

    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object:
        return []

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        return []


def _rows(root: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.jsonl")):
        result.extend(json.loads(line) for line in path.read_text().splitlines())
    return result


def test_bounded_recording_single_lane_disconnect_uses_redundant_coverage(
    tmp_path: Path,
) -> None:
    config = EvidenceRecordingConfig(
        duration_seconds=0.20,  # type: ignore[arg-type]
        deep_limit=1,
        context_poll_seconds=60,
        funding_poll_seconds=60,
    )
    primary = ScriptedConnection(
        [_trade(1, 1_000), ConnectionError("primary dropped")],
        row_delays_seconds=[0.0, 0.04],
    )
    standby = ScriptedConnection(
        [_trade(1, 1_000), _trade(2, 2_000)],
        row_delays_seconds=[0.0, 0.08],
    )
    pool = [primary, standby]
    factory_calls = 0
    tick = 2_000

    async def connection_factory() -> ScriptedConnection:
        nonlocal factory_calls
        factory_calls += 1
        return pool.pop(0)

    def clock_ms() -> int:
        nonlocal tick
        tick += 1
        return tick

    summary = asyncio.run(
        run_bounded_recording(
            bootstrap=_bootstrap(config),
            reader=Reader(),
            connection_factory=connection_factory,
            recorder=DurableRecorder(tmp_path),
            config=config,
            clock_ms=clock_ms,
            utcnow=lambda: RECEIVED,
        )
    )

    rows = _rows(tmp_path)
    trade_rows = [
        row
        for row in rows
        if row.get("record_type") == "normalized_event" and row.get("kind") == "trade"
    ]
    gap_rows = [row for row in rows if row.get("record_type") == "data_gap"]

    assert factory_calls >= 2
    assert [row["event_key"] for row in trade_rows] == [
        "trades:BTC:1000:1",
        "trades:BTC:2000:2",
    ]
    assert gap_rows == []
    assert summary.gap_count == 0
    assert summary.reconnect_count >= 1
    assert primary.closed is True
    assert standby.closed is True


def test_subscribed_standby_covers_disconnect_before_its_first_market_event(
    tmp_path: Path,
) -> None:
    config = EvidenceRecordingConfig(
        duration_seconds=0.20,  # type: ignore[arg-type]
        deep_limit=1,
        context_poll_seconds=60,
        funding_poll_seconds=60,
    )
    primary = ScriptedConnection(
        [_trade(1, 1_000), ConnectionError("primary dropped")],
        row_delays_seconds=[0.0, 0.04],
    )
    standby = ScriptedConnection(
        [_trade(2, 2_000)],
        row_delays_seconds=[0.08],
    )
    pool = [primary, standby]
    tick = 3_000

    async def connection_factory() -> ScriptedConnection:
        return pool.pop(0)

    def clock_ms() -> int:
        nonlocal tick
        tick += 1
        return tick

    summary = asyncio.run(
        run_bounded_recording(
            bootstrap=_bootstrap(config),
            reader=Reader(),
            connection_factory=connection_factory,
            recorder=DurableRecorder(tmp_path),
            config=config,
            clock_ms=clock_ms,
            utcnow=lambda: RECEIVED,
        )
    )

    rows = _rows(tmp_path)
    trade_rows = [
        row
        for row in rows
        if row.get("record_type") == "normalized_event" and row.get("kind") == "trade"
    ]
    gap_rows = [row for row in rows if row.get("record_type") == "data_gap"]

    assert [row["event_key"] for row in trade_rows] == [
        "trades:BTC:1000:1",
        "trades:BTC:2000:2",
    ]
    assert gap_rows == []
    assert summary.gap_count == 0
    assert summary.reconnect_count >= 1
