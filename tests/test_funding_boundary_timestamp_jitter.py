from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import FundingRate, MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.baseline import RecordedStateBook
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.funding import FundingAccrual, FundingGap, reconcile_funding_boundary

MARKET = MarketId(dex="", coin="SOL")
BOUNDARY_MS = 3_600_000
SOURCE_JITTER_MS = 49


def _position() -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=PositionSide.LONG,
        quantity=Decimal("2"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id="open-1",
        opened_at_ms=1_000,
        updated_at_ms=1_000,
    )


def _oracle_ctx() -> StreamEvent:
    received_ms = BOUNDARY_MS - 100
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=None,
        receive_time=datetime.fromtimestamp(received_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"ctx:{MARKET.canonical}:{received_ms}",
        payload={
            "mark_px": Decimal("100"),
            "mid_px": Decimal("100"),
            "oracle_px": Decimal("100"),
            "funding": Decimal("0.001"),
            "open_interest": Decimal("1000"),
        },
    )


def _funding_rate(*, time_ms: int) -> FundingRate:
    return FundingRate(
        market=MARKET,
        time_ms=time_ms,
        funding_rate=Decimal("0.001"),
        premium=Decimal("0"),
        source="hyperliquid-mainnet-info",
        received_at_ms=BOUNDARY_MS + 1_000,
        schema_version=1,
    )


def _funding_record(*, time_ms: int) -> ReplayRecord:
    return ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=BOUNDARY_MS + 1_000,
        source="hyperliquid-mainnet-info",
        schema_version=1,
        market="SOL",
        exchange_time_ms=None,
        event_key=f"funding:SOL:{time_ms}",
        payload_json=json.dumps(
            {
                "time_ms": time_ms,
                "funding_rate": "0.001",
                "premium": "0",
            }
        ),
        event_kind="funding_rate",
    )


def test_state_book_indexes_small_post_boundary_jitter_at_exact_boundary() -> None:
    book = RecordedStateBook(microstructure_window_ms=60_000)
    source_time_ms = BOUNDARY_MS + SOURCE_JITTER_MS

    book.apply(
        _funding_record(time_ms=source_time_ms),
        now_ms=BOUNDARY_MS + 1_000,
    )

    stored = book.state(MARKET).funding_by_boundary[BOUNDARY_MS]
    assert stored.time_ms == source_time_ms


def test_reconciliation_accepts_mainnet_post_boundary_timestamp_jitter() -> None:
    result = reconcile_funding_boundary(
        _position(),
        BOUNDARY_MS,
        _oracle_ctx(),
        _funding_rate(time_ms=BOUNDARY_MS + SOURCE_JITTER_MS),
        now_ms=BOUNDARY_MS + 2_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(result, FundingAccrual)
    assert result.boundary_ms == BOUNDARY_MS
    assert result.cash_delta == Decimal("-0.200")


def test_reconciliation_rejects_record_outside_boundary_jitter_window() -> None:
    result = reconcile_funding_boundary(
        _position(),
        BOUNDARY_MS,
        _oracle_ctx(),
        _funding_rate(time_ms=BOUNDARY_MS + 1_001),
        now_ms=BOUNDARY_MS + 2_000,
        config=PaperExecutionConfig(),
    )

    assert isinstance(result, FundingGap)
    assert result.reason == "FUNDING_TIME_MISMATCH"
