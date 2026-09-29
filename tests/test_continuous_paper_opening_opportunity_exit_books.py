from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    ContinuousPaperOpeningOpportunityExitBookError,
    ContinuousPaperOpeningOpportunityExitBookStore,
)


MARKET = MarketId(dex="", coin="SOL")


def _book(*, receive_ms: int, exchange_ms: int | None = None) -> StreamEvent:
    exchange = receive_ms - 5 if exchange_ms is None else exchange_ms
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=exchange,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-info",
        event_key=f"l2Book:SOL:{exchange}:fixture",
        payload={
            "bids": (
                {"px": Decimal("99"), "sz": Decimal("10"), "n": 2},
            ),
            "asks": (
                {"px": Decimal("101"), "sz": Decimal("12"), "n": 3},
            ),
        },
    )


def _instrument(*, metadata_ms: int) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("5"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=metadata_ms,
        metadata_source="hyperliquid-mainnet-info",
    )


def test_exit_book_store_schedules_and_round_trips_real_horizon_book(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperOpeningOpportunityExitBookStore(
        tmp_path / "exit-books",
        capture_started_at_ms=1_000,
        horizons_ms=(300, 900),
        max_capture_lag_ms=120,
    )
    assert store.register(
        opportunity_id="opp-1",
        market="SOL",
        direction="long",
        opportunity_timestamp_ms=1_100,
    ) is True

    assert store.due_requests(now_ms=1_399) == ()
    due = store.due_requests(now_ms=1_400)
    assert len(due) == 1
    assert due[0].horizon_ms == 300
    assert due[0].target_at_ms == 1_400

    assert store.capture(
        due[0],
        _book(receive_ms=1_450),
        _instrument(metadata_ms=1_390),
    ) is True
    assert store.capture(
        due[0],
        _book(receive_ms=1_450),
        _instrument(metadata_ms=1_390),
    ) is False

    evidence = store.load("opp-1", 300)
    assert evidence is not None
    assert evidence.observation_lag_ms == 50
    assert evidence.book_event == _book(receive_ms=1_450)
    assert evidence.instrument == _instrument(metadata_ms=1_390)
    assert store.registration_count == 1
    assert store.capture_count == 1
    assert len(store.state_digest) == 64


def test_exit_book_store_never_backfills_old_or_late_horizons(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperOpeningOpportunityExitBookStore(
        tmp_path / "exit-books",
        capture_started_at_ms=1_000,
        horizons_ms=(300, 900),
        max_capture_lag_ms=120,
    )
    with pytest.raises(
        ContinuousPaperOpeningOpportunityExitBookError,
        match="predates capture protocol",
    ):
        store.register(
            opportunity_id="old",
            market="SOL",
            direction="short",
            opportunity_timestamp_ms=999,
        )

    store.register(
        opportunity_id="opp-1",
        market="SOL",
        direction="short",
        opportunity_timestamp_ms=1_100,
    )
    assert store.due_requests(now_ms=1_521) == ()
    assert store.missed_count(now_ms=1_521) == 1

    request = store.request("opp-1", 300)
    with pytest.raises(
        ContinuousPaperOpeningOpportunityExitBookError,
        match="outside capture lag",
    ):
        store.capture(
            request,
            _book(receive_ms=1_521),
            _instrument(metadata_ms=1_500),
        )


def test_exit_book_store_requires_exact_market_lineage(tmp_path: Path) -> None:
    store = ContinuousPaperOpeningOpportunityExitBookStore(
        tmp_path / "exit-books",
        capture_started_at_ms=1_000,
        horizons_ms=(300,),
        max_capture_lag_ms=120,
    )
    store.register(
        opportunity_id="opp-1",
        market="SOL",
        direction="long",
        opportunity_timestamp_ms=1_100,
    )
    request = store.request("opp-1", 300)
    wrong_market = MarketId(dex="", coin="BTC")
    wrong_book = StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=wrong_market,
        exchange_time_ms=1_440,
        receive_time=datetime.fromtimestamp(1.45, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-info",
        event_key="l2Book:BTC:1440:fixture",
        payload={"bids": (), "asks": ()},
    )

    with pytest.raises(
        ContinuousPaperOpeningOpportunityExitBookError,
        match="market mismatch",
    ):
        store.capture(
            request,
            wrong_book,
            InstrumentExecutionSpec(
                market=wrong_market,
                sz_decimals=2,
                venue_max_leverage=Decimal("5"),
                minimum_order_notional=Decimal("10"),
                metadata_received_at_ms=1_390,
                metadata_source="hyperliquid-mainnet-info",
            ),
        )


def test_exit_book_store_preserves_protocol_start_across_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "exit-books"
    first = ContinuousPaperOpeningOpportunityExitBookStore(
        root,
        capture_started_at_ms=1_000,
        horizons_ms=(300, 900),
        max_capture_lag_ms=120,
    )
    first.register(
        opportunity_id="opp-1",
        market="SOL",
        direction="long",
        opportunity_timestamp_ms=1_100,
    )

    restored = ContinuousPaperOpeningOpportunityExitBookStore(
        root,
        capture_started_at_ms=5_000,
        horizons_ms=(300, 900),
        max_capture_lag_ms=120,
    )

    assert restored.capture_started_at_ms == 1_000
    assert restored.registration_count == 1
    assert restored.request("opp-1", 300).target_at_ms == 1_400
    with pytest.raises(
        ContinuousPaperOpeningOpportunityExitBookError,
        match="predates capture protocol",
    ):
        restored.register(
            opportunity_id="older-than-protocol",
            market="SOL",
            direction="short",
            opportunity_timestamp_ms=999,
        )
