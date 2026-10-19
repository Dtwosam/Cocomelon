"""Forward-style PAPER-only maker entry hypothesis, with no real queue fills."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
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
)
from cocomelon.research.maker_entry_paper_shadow import (
    simulate_strict_through_maker_entry,
)


def _plan(side: OrderSide = OrderSide.BUY) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id="risk-1",
        strategy_decision_id="signal-1",
        market=MarketId("", "BTC"),
        side=side,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("101"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95") if side is OrderSide.BUY else Decimal("105"),
        approved_notional_ceiling=Decimal("210"),
        created_at_ms=1_000,
        earliest_execution_ms=1_250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("15"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.055"),
    )


def _spec(*, sz_decimals: int = 1) -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MarketId("", "BTC"),
        sz_decimals=sz_decimals,
        venue_max_leverage=Decimal("10"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="real-original-metadata",
    )


def _event(
    kind: StreamKind, ms: int, payload: dict[str, object], *,
    key: str | None = None,
    market: str = "BTC",
    exchange_ms: int | None = None,
) -> StreamEvent:
    return StreamEvent(
        kind=kind,
        market=MarketId("", market),
        exchange_time_ms=ms if exchange_ms is None else exchange_ms,
        receive_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=key or f"{kind.value}:{market}:{ms}",
        payload=payload,
    )


def _book() -> StreamEvent:
    return _event(
        StreamKind.L2_BOOK, 1250,
        {
            "bids": [{"px": Decimal("100"), "sz": Decimal("5")}],
            "asks": [{"px": Decimal("101"), "sz": Decimal("5")}],
        },
    )


def _trade(
    ms: int, side: str, price: str, size: str, *,
    key: str | None = None, market: str = "BTC",
    exchange_ms: int | None = None,
) -> StreamEvent:
    return _event(
        StreamKind.TRADE, ms,
        {
            "side": side,
            "price": Decimal(price),
            "size": Decimal(size),
        },
        key=key, market=market, exchange_ms=exchange_ms,
    )


def _run(
    events: tuple[StreamEvent, ...],
    *,
    plan: PaperOrderPlan | None = None,
    spec: InstrumentExecutionSpec | None = None,
    clean: bool = True,
    end: int = 2500,
    quote_overrides: dict[str, object] | None = None,
    book_override: StreamEvent | None = None,
) -> dict[str, object]:
    original = plan or _plan()
    witness = quote_research_only_maker_entry(
        original_plan=original,
        original_book=_book(),
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"),
        quote_at_ms=1250,
        wait_ms=1000,
    )
    if quote_overrides:
        witness = replace(witness, **quote_overrides)
    return simulate_strict_through_maker_entry(
        witness,
        original_plan=original,
        original_book=book_override or _book(),
        instrument=spec or _spec(),
        execution_config=PaperExecutionConfig(),
        original_events=events,
        observation_end_ms=end,
        source_integrity_passed=clean,
    )


def test_touch_prints_only_consume_queue_and_never_create_a_fill() -> None:
    result = _run((
        _trade(1300, "A", "100", "9"),
        _trade(1500, "B", "101", "9"),
    ))
    assert result["at_touch_trade_prints"] == 1
    assert result["modelled_entry_status"] == "no_fill"
    assert Decimal(result["remaining_assumed_queue_ahead_quantity"]) == 0
    assert result["conditional_modelled_entry_quantity"] == "0"
    assert result["conditional_modelled_unfilled_quantity"] == "2"
    assert result["conditional_modelled_entry_fee_usd"] == "0"
    assert result["maker_order_submitted_or_confirmed_by_venue"] is False
    assert result["guaranteed_real_entry_fill_quantity"] == "0"
    assert result["whole_account_after_cost_pnl_usd"] is None
    assert result["execution_authority"] is False


def test_through_prints_first_consume_queue_then_model_partial_and_expire() -> None:
    result = _run((
        _trade(1300, "A", "100", "4"),
        _trade(1400, "A", "99", "0.7"),
        _trade(1500, "A", "99", "0.8"),
        _trade(2400, "A", "99", "500"),
    ))
    # initial best bid visible queue = 5, first at-touch 4, first through
    # 0.7 consumes queue; second through spends 0.3 queue then models 0.5.
    assert result["modelled_entry_status"] == "partial"
    assert result["conditional_modelled_entry_quantity"] == "0.5"
    assert result["conditional_modelled_unfilled_quantity"] == "1.5"
    assert Decimal(result["conditional_modelled_entry_notional_usd"]) == 50
    assert Decimal(result["conditional_modelled_entry_fee_usd"]) == Decimal(
        "0.0075"
    )
    assert len(result["conditional_modelled_trade_events"]) == 1
    assert result["conditional_modelled_trade_events"][0][
        "original_trade_event_key"
    ] == "trade:BTC:1500"
    assert result["realized_fee_savings_usd"] is None


def test_strict_through_can_model_full_but_never_verify_a_venue_fill() -> None:
    result = _run((
        _trade(1400, "A", "99", "8"),
    ))
    assert result["modelled_entry_status"] == "full"
    assert result["conditional_modelled_entry_quantity"] == "2"
    assert Decimal(result["conditional_modelled_entry_fee_usd"]) == Decimal(
        "0.0300"
    )
    assert result["guaranteed_real_entry_fill_quantity"] == "0"
    assert result["maker_order_submitted_or_confirmed_by_venue"] is False
    assert result["modelled_position_exits_or_funding"] is False
    assert result["whole_account_after_cost_pnl_usd"] is None
    assert result["promotion_authority"] is False


def test_selling_requires_buy_aggressor_strictly_above_ask() -> None:
    result = _run(
        (
            _trade(1300, "A", "99", "100"),
            _trade(1400, "B", "101", "3"),
            _trade(1500, "B", "102", "4"),
        ),
        plan=_plan(OrderSide.SELL),
    )
    # Original best ask queue 5: 3 at touch and then 4 through
    # consumes remaining 2 ahead and model-fills 2 conditional units.
    assert result["conditional_modelled_entry_quantity"] == "2"
    assert result["modelled_entry_status"] == "full"


def test_small_through_prints_accumulate_only_quantized_model_quantity() -> None:
    result = _run((
        _trade(1300, "A", "100", "5"),
        _trade(1400, "A", "99", "0.04"),
        _trade(1500, "A", "99", "0.04"),
        _trade(1600, "A", "99", "0.05"),
    ))
    assert result["conditional_modelled_entry_quantity"] == "0.1"
    assert result["conditional_modelled_unfilled_quantity"] == "1.9"


def test_entry_quantized_size_is_hard_clipped_by_original_notional_and_risk() -> None:
    plan = replace(_plan(), approved_notional_ceiling=Decimal("115"))
    result = _run((_trade(1350, "A", "99", "12"),), plan=plan)
    assert result["original_risk_capped_max_quantity"] == "1.1"
    assert result["conditional_modelled_entry_quantity"] == "1.1"
    assert result["modelled_entry_status"] == "partial"
    # When an original stop is close enough, risk cap rather than
    # the commission discount determines allowed size.
    tight = replace(
        _plan(),
        stop_price=Decimal("90"),
        approved_risk_amount_ceiling=Decimal("10"),
    )
    result = _run((_trade(1350, "A", "99", "12"),), plan=tight)
    assert result["original_risk_capped_max_quantity"] == "0.9"
    assert result["conditional_modelled_entry_quantity"] == "0.9"


@pytest.mark.parametrize(("events", "clean", "end", "error"), [
    ((), False, 2500, "gaps"),
    ((), True, 2200, "not fully observed"),
    (
        (_trade(1300, "A", "99", "4", key="same"),
         _trade(1400, "A", "99", "4", key="same")),
        True, 2500, "duplicate",
    ),
    (
        (_trade(1400, "A", "99", "4"),
         _trade(1300, "A", "99", "4")),
        True, 2500, "reversed",
    ),
    (
        (_trade(1400, "A", "99", "4", market="ETH"),),
        True, 2500, "exact-market",
    ),
    (
        (_trade(1400, "A", "99", "4", exchange_ms=1420),),
        True, 2500, "exchange/receipt clock",
    ),
    (
        (_trade(1400, "?", "99", "4"),),
        True, 2500, "aggressor",
    ),
])
def test_invalid_or_incomplete_original_source_never_creates_shadow_fills(
    events: tuple[StreamEvent, ...], clean: bool, end: int, error: str,
) -> None:
    with pytest.raises(MakerEntryWitnessError, match=error):
        _run(events, clean=clean, end=end)


@pytest.mark.parametrize(("quote_overrides", "error"), [
    ({"market": "ETH"}, "lineage"),
    ({"side": "sell"}, "lineage"),
    ({"quote_price": Decimal("110")}, "stop/slippage"),
    ({"displayed_best_level_quantity": Decimal("0")}, "queue depth"),
    ({"hypothetical_maker_fee_rate": Decimal("0.00045")}, "fee"),
    ({"requested_quantity": Decimal("8")}, "fee, size"),
    ({"expire_at_ms": 1250 + 300_001}, "lineage"),
])
def test_cannot_smuggle_invalid_maker_quote_or_reduce_risk_envelope(
    quote_overrides: dict[str, object], error: str,
) -> None:
    with pytest.raises(MakerEntryWitnessError, match=error):
        _run((), quote_overrides=quote_overrides)


def test_original_instrument_lineage_is_mandatory() -> None:
    with pytest.raises(MakerEntryWitnessError, match="lineage"):
        _run((), spec=replace(_spec(), metadata_received_at_ms=901))



def test_risk_clipped_below_native_minimum_refuses_maker_order() -> None:
    low = replace(
        _plan(),
        approved_risk_amount_ceiling=Decimal("0.5"),
    )
    with pytest.raises(MakerEntryWitnessError, match="venue-sized"):
        _run((), plan=low)


def test_maker_source_trade_future_exchange_time_is_rejected() -> None:
    with pytest.raises(MakerEntryWitnessError, match="exchange/receipt"):
        _run((_trade(1400, "A", "99", "8", exchange_ms=1500),))



def test_forged_resting_quote_price_cannot_create_modeled_cash() -> None:
    # A passive candidate cannot insert a lower bid than the actual source.
    with pytest.raises(MakerEntryWitnessError, match="book/witness"):
        _run(
            (_trade(1400, "A", "98", "20"),),
            quote_overrides={"quote_price": Decimal("99")},
        )


def test_forged_visible_queue_depth_cannot_jump_original_queue() -> None:
    with pytest.raises(MakerEntryWitnessError, match="book/witness"):
        _run(
            (_trade(1400, "A", "99", "20"),),
            quote_overrides={"displayed_best_level_quantity": Decimal("0.1")},
        )


def test_supplied_book_must_match_source_timed_original_quote() -> None:
    changed = replace(
        _book(),
        event_key="original-tampered-book",
    )
    with pytest.raises(MakerEntryWitnessError, match="book/witness"):
        _run(
            (_trade(1400, "A", "99", "20"),),
            book_override=changed,
        )


def test_stale_original_book_does_not_get_maker_shadow_fills() -> None:
    stale = replace(
        _book(),
        receive_time=datetime.fromtimestamp(0, tz=UTC),
        exchange_time_ms=0,
    )
    with pytest.raises(MakerEntryWitnessError, match="stale"):
        _run((_trade(1400, "A", "99", "20"),), book_override=stale)
