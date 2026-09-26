from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.continuous_paper import (
    RUN_ID,
    ContinuousPaperConfig,
    _record_from_gap,
    _record_from_payload,
    _record_from_stream,
    _record_payload,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import SourceRecordKind
from cocomelon.domain.stream import DataGap, StreamEvent, StreamKind


def test_continuous_config_requires_aligned_refresh_interval() -> None:
    with pytest.raises(ValueError, match="divisible"):
        ContinuousPaperConfig(
            duration_seconds=60,
            context_poll_seconds=60,
            selection_refresh_seconds=61,
        )


def test_gap_record_preserves_recovered_interval() -> None:
    gap = DataGap(
        stream_id="l2Book:BTC",
        started_ms=1_000,
        ended_ms=1_500,
        reason="recovered",
    )
    record = _record_from_gap(gap)
    assert record.record_kind is SourceRecordKind.DATA_GAP
    assert record.available_at_ms == 1_000
    assert record.payload == {
        "ended_ms": 1_500,
        "reason": "recovered",
        "started_ms": 1_000,
        "stream_id": "l2Book:BTC",
    }


def test_stream_record_round_trip_is_canonical() -> None:
    event = StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MarketId("", "BTC"),
        exchange_time_ms=2_000,
        receive_time=datetime.fromtimestamp(2, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="ctx-1",
        payload={
            "mark_px": Decimal("100"),
            "mid_px": Decimal("100.1"),
            "oracle_px": Decimal("99.9"),
            "funding": Decimal("0.0001"),
            "open_interest": Decimal("50"),
        },
    )
    record = _record_from_stream(event)
    restored = _record_from_payload(_record_payload(record))
    assert restored == record
    assert RUN_ID == "continuous-paper-mainnet-v1"



def test_runtime_source_exposes_structured_live_heartbeat() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8")
    assert "COCOMELON_PAPER_HEARTBEAT " in source
    assert '"paper_only": True' in source
    assert '"live_orders": False' in source
    assert '"positions": positions' in source
    assert '"stop_price": str(position.stop_price)' in source
    assert '"session_decision_epochs"' in source
    assert '"session_decisions"' in source
    assert '"session_risk"' in source
