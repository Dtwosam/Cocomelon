from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.evidence.contracts import (
    EvidenceRecordingConfig,
    EvidenceRecordingSession,
    SelectedEvidenceMarket,
)
from cocomelon.evidence.recording import RecordingBootstrap, run_bounded_recording
from cocomelon.recorder import DurableRecorder

MARKET = MarketId("", "SOL")
RECEIVED = datetime(2026, 8, 25, 17, 10, tzinfo=UTC)


class BlockingReader:
    def __init__(self, standby_started: threading.Event) -> None:
        self._standby_started = standby_started
        self.context_poll_entered = False
        self.timed_out_waiting_for_standby = False

    def perp_dexs(self) -> object:
        return [None]

    def meta_and_asset_ctxs(self, dex: str = "") -> object:
        assert dex == ""
        self.context_poll_entered = True
        if not self._standby_started.wait(timeout=0.20):
            self.timed_out_waiting_for_standby = True
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
                    "markPx": "180",
                    "midPx": "180",
                    "oraclePx": "180",
                    "funding": "0.00001",
                    "openInterest": "100000",
                    "dayNtlVlm": "500000000",
                    "premium": "0",
                    "prevDayPx": "179",
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
        assert market == MARKET
        return []


class QuietConnection:
    async def send_json(self, message: dict[str, object]) -> None:
        return None

    async def recv_json(self) -> dict[str, object]:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")

    async def close(self) -> None:
        return None


def _config() -> EvidenceRecordingConfig:
    return EvidenceRecordingConfig(
        duration_seconds=0.08,  # type: ignore[arg-type]
        deep_limit=1,
        context_poll_seconds=1,
        funding_poll_seconds=1,
    )


def _bootstrap(config: EvidenceRecordingConfig) -> RecordingBootstrap:
    session = EvidenceRecordingSession(
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
        recording_config_digest=config.config_digest,
        api_url=config.api_url,
        ws_url=config.ws_url,
        selection_policy_id=config.selection_policy_id,
    )
    return RecordingBootstrap(
        session=session,
        snapshots=(),
        candles=(),
        funding_rates=(),
        subscriptions=({"type": "allMids"},),
    )


def test_blocking_rest_poll_does_not_starve_standby_websocket_start(tmp_path: Path) -> None:
    config = _config()
    standby_started = threading.Event()
    reader = BlockingReader(standby_started)
    calls = 0

    async def connection_factory() -> QuietConnection:
        nonlocal calls
        calls += 1
        if calls == 2:
            await asyncio.sleep(0.02)
            standby_started.set()
        return QuietConnection()

    asyncio.run(
        run_bounded_recording(
            bootstrap=_bootstrap(config),
            reader=reader,
            connection_factory=connection_factory,
            recorder=DurableRecorder(tmp_path),
            config=config,
            clock_ms=lambda: 5_000,
            utcnow=lambda: RECEIVED,
        )
    )

    assert reader.context_poll_entered is True
    assert standby_started.is_set() is True
    assert reader.timed_out_waiting_for_standby is False
