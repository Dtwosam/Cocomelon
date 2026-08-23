from datetime import UTC, datetime
from decimal import Decimal

import pytest
from cocomelon.domain.stream import DataGap, FreshnessState, StreamEvent, StreamKind

from cocomelon.domain.market import MarketId


def test_stream_event_preserves_provenance_and_times() -> None:
    event = StreamEvent(
        kind=StreamKind.TRADE,
        market=MarketId(dex="", coin="BTC"),
        exchange_time_ms=1_787_500_000_000,
        receive_time=datetime(2026, 8, 23, tzinfo=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key="BTC:trade:123",
        payload={"price": Decimal("100")},
    )

    assert event.source == "hyperliquid-mainnet-ws"
    assert event.payload["price"] == Decimal("100")
    assert event.receive_time.tzinfo is UTC


def test_stream_event_requires_timezone_aware_receive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        StreamEvent(
            kind=StreamKind.TRADE,
            market=MarketId(dex="", coin="BTC"),
            exchange_time_ms=1,
            receive_time=datetime(2026, 8, 23),
            schema_version=1,
            source="hyperliquid-mainnet-ws",
            event_key="BTC:trade:1",
            payload={},
        )


def test_gap_requires_non_negative_duration() -> None:
    with pytest.raises(ValueError, match="ended_ms"):
        DataGap(
            stream_id="trades:BTC",
            started_ms=20,
            ended_ms=10,
            reason="disconnect",
        )


def test_open_gap_is_allowed_until_stream_recovers() -> None:
    gap = DataGap(
        stream_id="trades:BTC",
        started_ms=20,
        ended_ms=None,
        reason="disconnect",
    )
    assert gap.ended_ms is None


def test_freshness_state_can_be_stale_without_inventing_data() -> None:
    state = FreshnessState(stream_id="l2Book:BTC", last_message_ms=1000, stale_after_ms=5000)

    assert state.is_stale(now_ms=5999) is False
    assert state.is_stale(now_ms=6000) is True


def test_freshness_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="stale_after_ms"):
        FreshnessState(stream_id="trades:BTC", last_message_ms=None, stale_after_ms=-1)
