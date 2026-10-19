"""Original L2 maker-entry probe cannot invent queue fills or fee savings."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    OrderSide,
    OrderType,
    PaperExecutionConfig,
    PaperOrderPlan,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.research.maker_entry_feasibility import (
    MakerEntryWitnessError,
    quote_research_only_maker_entry,
    review_original_trade_through,
)


def _event(
    kind: StreamKind, ms: int, payload: dict[str, object], *,
    market: str = "BTC", key: str | None = None,
) -> StreamEvent:
    return StreamEvent(
        kind=kind,
        market=MarketId("", market),
        exchange_time_ms=ms,
        receive_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=key or f"{kind.value}:{market}:{ms}",
        payload=payload,
    )


def _plan(side: OrderSide = OrderSide.BUY) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="r1",
        strategy_decision_id="s1",
        market=MarketId("", "BTC"),
        side=side,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("101"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95"),
        approved_notional_ceiling=Decimal("210"),
        created_at_ms=1000,
        earliest_execution_ms=1250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("15"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.055"),
    )


def _book(ms: int = 1250) -> StreamEvent:
    return _event(
        StreamKind.L2_BOOK, ms,
        {
            "bids": [{"px": Decimal("100"), "sz": Decimal("7")}],
            "asks": [{"px": Decimal("101"), "sz": Decimal("5")}],
        },
    )


def _trade(
    ms: int, side: str, price: str, size: str, *, key: str | None = None,
) -> StreamEvent:
    return _event(
        StreamKind.TRADE, ms,
        {"side": side, "price": Decimal(price), "size": Decimal(size)},
        key=key,
    )


def test_buy_post_only_quote_is_cheaper_if_hypothetically_filled() -> None:
    witness = quote_research_only_maker_entry(
        original_plan=_plan(), original_book=_book(),
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"),
        quote_at_ms=1250, wait_ms=1000,
    )
    assert witness.quote_price == Decimal("100")
    assert witness.displayed_best_level_quantity == Decimal("7")
    assert witness.fee_savings_if_entire_entry_filled_same_notional == Decimal(
        "0.06000"
    )
    assert witness.payload()["resting_order_submitted"] is False
    result = review_original_trade_through(
        witness,
        original_events=(
            _trade(1300, "B", "101", "20"),
            _trade(1400, "A", "100", "0.4"),
            _trade(1800, "A", "99", "0.7"),
            _trade(2300, "A", "99", "10"),
        ),
        observation_end_ms=2500,
        source_integrity_passed=True,
    )
    assert result["crossing_original_trade_count"] == 2
    assert result["possible_entry_fill_quantity_upper_bound"] == "1.1"
    assert result["guaranteed_entry_fill_quantity"] == "0"
    assert result["maker_fee_savings_realized_usd"] is None
    assert result["candidate_after_cost_pnl_usd"] is None
    assert result["promotion_authority"] is False


def test_sell_quote_requires_buy_aggressor_cross() -> None:
    witness = quote_research_only_maker_entry(
        original_plan=_plan(OrderSide.SELL), original_book=_book(),
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"), quote_at_ms=1250,
        wait_ms=1000,
    )
    assert witness.quote_price == Decimal("101")
    result = review_original_trade_through(
        witness,
        original_events=(
            _trade(1400, "A", "100", "7"),
            _trade(1600, "B", "100.9", "7"),
            _trade(1700, "B", "101", "5"),
        ),
        observation_end_ms=2250,
        source_integrity_passed=True,
    )
    assert result["possible_entry_fill_quantity_upper_bound"] == "2"
    assert result["maker_fill_certified"] is False


def test_no_trades_does_not_turn_a_cheaper_quote_into_free_profit() -> None:
    witness = quote_research_only_maker_entry(
        original_plan=_plan(), original_book=_book(),
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"),
        quote_at_ms=1250, wait_ms=1000,
    )
    result = review_original_trade_through(
        witness, original_events=(), observation_end_ms=2250,
        source_integrity_passed=True,
    )
    assert result["possible_entry_fill_quantity_upper_bound"] == "0"
    assert result["guaranteed_entry_fill_quantity"] == "0"
    assert result["candidate_after_cost_pnl_usd"] is None


@pytest.mark.parametrize(
    ("book", "quote_at", "rate", "error"),
    [
        (_book(), 1250, Decimal("0.00045"), "maker rate"),
        (_book(), 2251, Decimal("0.00015"), "stale"),
        (_book(1500), 1250, Decimal("0.00015"), "future"),
        (_event(StreamKind.L2_BOOK, 1250, {
            "bids": [{"px": Decimal("101"), "sz": Decimal("1")}],
            "asks": [{"px": Decimal("101"), "sz": Decimal("1")}],
        }), 1250, Decimal("0.00015"), "crossed"),
        (_event(StreamKind.L2_BOOK, 1250, {
            "bids": [{"px": Decimal("100"), "sz": Decimal("1")}],
            "asks": [{"px": Decimal("101"), "sz": Decimal("0")}],
        }), 1250, Decimal("0.00015"), "positive"),
    ],
)
def test_bad_book_or_fee_schedule_refused(
    book: StreamEvent, quote_at: int, rate: Decimal, error: str,
) -> None:
    with pytest.raises(MakerEntryWitnessError, match=error):
        quote_research_only_maker_entry(
            original_plan=_plan(), original_book=book,
            execution=PaperExecutionConfig(),
            maker_fee_rate=rate, quote_at_ms=quote_at,
        )


def test_quote_cannot_jump_original_plan_latency_or_market() -> None:
    with pytest.raises(MakerEntryWitnessError, match="bounded wait"):
        quote_research_only_maker_entry(
            original_plan=_plan(), original_book=_book(),
            execution=PaperExecutionConfig(),
            maker_fee_rate=Decimal("0.00015"), quote_at_ms=1249,
        )
    with pytest.raises(MakerEntryWitnessError, match="lineage"):
        quote_research_only_maker_entry(
            original_plan=_plan(),
            original_book=replace(_book(), market=MarketId("", "ETH")),
            execution=PaperExecutionConfig(),
            maker_fee_rate=Decimal("0.00015"), quote_at_ms=1250,
        )


@pytest.mark.parametrize(
    ("events", "source_clean", "end", "message"),
    [
        ((), False, 2250, "gaps"),
        ((), True, 2249, "not fully observed"),
        ((
            _trade(1400, "A", "100", "1", key="same"),
            _trade(1500, "A", "100", "1", key="same"),
        ), True, 2250, "duplicate"),
        ((
            _trade(1600, "A", "100", "1"),
            _trade(1500, "A", "100", "1"),
        ), True, 2250, "reversed"),
        ((_trade(1400, "A", "100", "1", key="t1"),
          _event(StreamKind.TRADE, 1500, {
              "side": "A", "price": Decimal("100"), "size": Decimal("1"),
          }, market="ETH", key="t2")), True, 2250, "exact-market"),
        ((_trade(1400, "?", "100", "1"),), True, 2250, "aggressor"),
    ],
)
def test_trade_tape_and_source_integrity_fail_closed(
    events: tuple[StreamEvent, ...],
    source_clean: bool,
    end: int,
    message: str,
) -> None:
    witness = quote_research_only_maker_entry(
        original_plan=_plan(), original_book=_book(),
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"), quote_at_ms=1250,
        wait_ms=1000,
    )
    with pytest.raises(MakerEntryWitnessError, match=message):
        review_original_trade_through(
            witness, original_events=events, observation_end_ms=end,
            source_integrity_passed=source_clean,
        )


def test_same_millisecond_original_trade_is_not_assumed_after_quote() -> None:
    witness = quote_research_only_maker_entry(
        original_plan=_plan(), original_book=_book(),
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"), quote_at_ms=1250,
        wait_ms=1000,
    )
    result = review_original_trade_through(
        witness,
        original_events=(
            _trade(1250, "A", "99", "30", key="ambiguous"),
            _trade(1300, "A", "100", "0.25"),
        ),
        observation_end_ms=2250,
        source_integrity_passed=True,
    )
    assert result["possible_entry_fill_quantity_upper_bound"] == "0.25"
    assert result["maker_fill_certified"] is False
