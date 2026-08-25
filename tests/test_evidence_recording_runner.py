from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.market import (
    Candle,
    FundingRate,
    MarketId,
    PerpMarketContext,
    PerpMarketMeta,
    PerpMarketSnapshot,
)
from cocomelon.evidence.contracts import (
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
)
from cocomelon.evidence.recording import (
    RecordingBootstrap,
    load_recording_session,
    run_bounded_recording,
    verify_recording_resume,
    write_recording_session,
)
from cocomelon.recorder import DurableRecorder

MARKET = MarketId("", "SOL")
RECEIVED = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)


def _snapshot(received_at_ms: int = 2_000) -> PerpMarketSnapshot:
    return PerpMarketSnapshot(
        meta=PerpMarketMeta(
            market=MARKET,
            wire_name="SOL",
            sz_decimals=3,
            max_leverage=20,
            margin_table_id=None,
            only_isolated=False,
            is_delisted=False,
            margin_mode=None,
        ),
        context=PerpMarketContext(
            market=MARKET,
            mark_px=Decimal("180"),
            mid_px=Decimal("180"),
            oracle_px=Decimal("180"),
            funding=Decimal("0.00001"),
            open_interest=Decimal("100000"),
            day_ntl_vlm=Decimal("500000000"),
            premium=Decimal("0"),
            prev_day_px=Decimal("178"),
        ),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _candle(received_at_ms: int = 2_100) -> Candle:
    return Candle(
        market=MARKET,
        interval="15m",
        start_ms=0,
        end_ms=900_000,
        open_px=Decimal("178"),
        high_px=Decimal("181"),
        low_px=Decimal("177"),
        close_px=Decimal("180"),
        volume=Decimal("1000"),
        trade_count=100,
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _funding(received_at_ms: int = 2_200) -> FundingRate:
    return FundingRate(
        market=MARKET,
        time_ms=1_000,
        funding_rate=Decimal("0.00001"),
        premium=Decimal("0"),
        source="hyperliquid-mainnet-info",
        received_at_ms=received_at_ms,
        schema_version=1,
    )


def _config(*, duration_seconds: float = 0.05) -> EvidenceRecordingConfig:
    return EvidenceRecordingConfig(
        duration_seconds=duration_seconds,  # type: ignore[arg-type]
        deep_limit=1,
        context_poll_seconds=1,
        funding_poll_seconds=1,
    )


def _session(config: EvidenceRecordingConfig | None = None) -> EvidenceRecordingSession:
    resolved = config or _config()
    return EvidenceRecordingSession(
        started_at_ms=1_500,
        recorder_code_revision="a" * 40,
        selected=(
            SelectedEvidenceMarket(
                market=MARKET,
                rank=1,
                feature_snapshot_id="feature-sol",
                score=Decimal("90"),
            ),
        ),
        recording_config_digest=resolved.config_digest,
        api_url=resolved.api_url,
        ws_url=resolved.ws_url,
        selection_policy_id=resolved.selection_policy_id,
    )


def _bootstrap(config: EvidenceRecordingConfig | None = None) -> RecordingBootstrap:
    resolved = config or _config()
    return RecordingBootstrap(
        session=_session(resolved),
        snapshots=(_snapshot(),),
        candles=(_candle(),),
        funding_rates=(_funding(),),
        subscriptions=({"type": "allMids"},),
    )


class FakeReader:
    def __init__(self, *, fail_context: bool = False) -> None:
        self.fail_context = fail_context
        self.funding_calls = 0

    def perp_dexs(self) -> object:
        return [None]

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        assert dex == ""
        if self.fail_context:
            raise RuntimeError("context unavailable")
        return [
            {
                "universe": [
                    {
                        "name": "SOL",
                        "szDecimals": 3,
                        "maxLeverage": 20,
                        "isDelisted": False,
                    }
                ]
            },
            [
                {
                    "markPx": "181",
                    "midPx": "181",
                    "oraclePx": "181",
                    "funding": "0.00001",
                    "openInterest": "100100",
                    "dayNtlVlm": "500100000",
                    "premium": "0",
                    "prevDayPx": "178",
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
        raise AssertionError("bounded runner must not refetch candle warmup")

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object:
        self.funding_calls += 1
        assert market == MARKET
        return [
            {
                "coin": "SOL",
                "time": 1_000,
                "fundingRate": "0.00001",
                "premium": "0",
            }
        ]


class FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.closed = False
        self._delivered = False

    async def send_json(self, message: dict[str, object]) -> None:
        self.sent.append(dict(message))

    async def recv_json(self) -> dict[str, object]:
        if not self._delivered:
            self._delivered = True
            return {"channel": "allMids", "data": {"mids": {"SOL": "181"}}}
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closed = True


class FailingEventRecorder(DurableRecorder):
    def append_event(self, event):  # type: ignore[no-untyped-def]
        raise OSError("injected recorder failure")


def _jsonl_rows(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            rows.append(json.loads(line))
    return rows


def test_session_metadata_round_trips_and_conflicts_fail_closed(tmp_path: Path) -> None:
    session = _session()
    write_recording_session(tmp_path, session)

    assert load_recording_session(tmp_path) == session
    verify_recording_resume(tmp_path, session)

    changed = replace(session, recorder_code_revision="b" * 40)
    with pytest.raises(ValueError, match="recording session"):
        verify_recording_resume(tmp_path, changed)


def test_resume_opens_new_recorder_segment_for_same_session(tmp_path: Path) -> None:
    session = _session()
    write_recording_session(tmp_path, session)
    first = DurableRecorder(tmp_path, max_records=100)
    first_path = first.append_market_snapshot(_snapshot(2_000))

    verify_recording_resume(tmp_path, session)
    second = DurableRecorder(tmp_path, max_records=100)
    second_path = second.append_market_snapshot(_snapshot(3_000))

    assert first_path != second_path
    assert first_path.name == "segment-000001.jsonl"
    assert second_path.name == "segment-000002.jsonl"


def test_populated_root_without_session_metadata_cannot_be_claimed(tmp_path: Path) -> None:
    (tmp_path / "unexpected.txt").write_text("evidence", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        verify_recording_resume(tmp_path, _session())


def test_bounded_runner_records_bootstrap_ws_periodic_context_and_dedupes_funding(
    tmp_path: Path,
) -> None:
    # REST polls are intentionally offloaded to worker threads. Give both serialized
    # context and funding polls enough wall-clock budget to start on loaded CI runners.
    config = _config(duration_seconds=0.5)
    bootstrap = _bootstrap(config)
    reader = FakeReader()
    connection = FakeConnection()
    recorder = DurableRecorder(tmp_path)
    tick = 3_000

    def clock_ms() -> int:
        nonlocal tick
        tick += 1
        return tick

    async def connection_factory() -> FakeConnection:
        return connection

    summary = asyncio.run(
        run_bounded_recording(
            bootstrap=bootstrap,
            reader=reader,
            connection_factory=connection_factory,
            recorder=recorder,
            config=config,
            clock_ms=clock_ms,
            utcnow=lambda: RECEIVED,
        )
    )

    rows = _jsonl_rows(tmp_path)
    event_rows = [row for row in rows if row.get("record_type") == "normalized_event"]
    funding_rows = [row for row in event_rows if row.get("kind") == "funding_rate"]
    snapshot_rows = [row for row in event_rows if row.get("kind") == "market_snapshot"]

    assert summary.session_id == bootstrap.session.session_id
    assert summary.selected_markets == ("SOL",)
    assert summary.event_count == len(event_rows)
    assert summary.network_access is True
    assert summary.live_orders is False
    assert len(funding_rows) == 1
    assert len(snapshot_rows) >= 2
    assert any(row.get("kind") == "all_mids" for row in event_rows)
    assert reader.funding_calls >= 1
    assert connection.closed is True


def test_rest_poll_failure_records_gap_instead_of_fabricating_data(tmp_path: Path) -> None:
    config = _config()
    bootstrap = _bootstrap(config)
    reader = FakeReader(fail_context=True)
    connection = FakeConnection()
    recorder = DurableRecorder(tmp_path)

    async def connection_factory() -> FakeConnection:
        return connection

    summary = asyncio.run(
        run_bounded_recording(
            bootstrap=bootstrap,
            reader=reader,
            connection_factory=connection_factory,
            recorder=recorder,
            config=config,
            clock_ms=lambda: 5_000,
            utcnow=lambda: RECEIVED,
        )
    )

    rows = _jsonl_rows(tmp_path)
    gap_rows = [row for row in rows if row.get("record_type") == "data_gap"]
    assert summary.gap_count == len(gap_rows)
