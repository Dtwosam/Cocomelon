"""Research queue-ahead scenarios cannot create booked fills or alpha."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.research.maker_entry_feasibility import (
    MakerEntryQuoteWitness,
    MakerEntryWitnessError,
)
from cocomelon.research.maker_entry_queue_stress import (
    maker_entry_queue_ahead_sensitivity,
)


def _witness(side: str = "buy") -> MakerEntryQuoteWitness:
    return MakerEntryQuoteWitness(
        opening_plan_id="original-plan-1",
        market="BTC",
        side=side,
        quote_price=Decimal("100") if side == "buy" else Decimal("101"),
        requested_quantity=Decimal("2"),
        displayed_best_level_quantity=Decimal("5"),
        quote_at_ms=1250,
        expire_at_ms=2250,
        baseline_taker_fee_rate=Decimal("0.00045"),
        hypothetical_maker_fee_rate=Decimal("0.00015"),
        fee_savings_if_entire_entry_filled_same_notional=Decimal("0.06"),
        book_event_key="original-l2:BTC:1250",
    )


def _print(
    ms: int, side: str, price: str, size: str, *, key: str | None = None,
    market: str = "BTC", exchange_ms: int | None = None,
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.TRADE,
        market=MarketId("", market),
        exchange_time_ms=ms if exchange_ms is None else exchange_ms,
        receive_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=key or f"trades:{market}:{ms}",
        payload={
            "side": side,
            "price": Decimal(price),
            "size": Decimal(size),
        },
    )


def _run(
    witness: MakerEntryQuoteWitness,
    events: tuple[StreamEvent, ...],
    *,
    end: int = 2250,
    clean: bool = True,
) -> dict[str, object]:
    return maker_entry_queue_ahead_sensitivity(
        witness,
        original_events=events,
        observation_end_ms=end,
        source_integrity_passed=clean,
    )


def test_buy_touched_prints_are_not_certified_maker_fills() -> None:
    witness = _witness()
    events = (
        _print(1250, "A", "99", "40"),
        _print(1300, "B", "101", "50"),
        _print(1400, "A", "100", "4"),
        _print(1500, "A", "99.9", "0.5"),
        _print(2400, "A", "99", "500"),
    )
    report = _run(witness, events, end=2400)
    assert report["at_quote_print_quantity"] == "4"
    assert report["strictly_through_print_quantity"] == "0.5"
    assert report["opposite_aggressor_at_quote_prints"] == 1
    assert report["opposite_aggressor_strictly_through_prints"] == 1
    assert report["original_simple_crossing_upper_bound"] == "2"
    scenarios = report["queue_ahead_stress_scenarios"]
    assert [s["conditional_possible_quantity"] for s in scenarios] == [
        "2", "0.5", "0.5"
    ]
    assert [s["full_requested_size_possible_in_scenario"] for s in scenarios] == [
        True, False, False
    ]
    assert [
        Decimal(s["conditional_single_entry_fee_discount_usd"])
        for s in scenarios
    ] == [Decimal("0.06"), Decimal("0.015"), Decimal("0.015")]
    assert report["guaranteed_filled_quantity"] == "0"
    assert report["realized_maker_fee_savings_usd"] is None
    assert report["maker_candidate_after_cost_equity_usd"] is None
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False


def test_sell_uses_buy_aggressor_and_one_venue_queue_ahead() -> None:
    report = _run(
        _witness("sell"),
        (
            _print(1300, "A", "99", "100"),
            _print(1450, "B", "101", "6"),
            _print(1500, "B", "102", "0.4"),
        ),
    )
    scenarios = report["queue_ahead_stress_scenarios"]
    assert [s["conditional_possible_quantity"] for s in scenarios] == [
        "2", "1.4", "0.4"
    ]
    assert report["strictly_through_print_quantity"] == "0.4"
    assert report["maker_quote_actually_resting"] is False


def test_unchanged_tape_no_opposing_prints_never_earns_discount() -> None:
    report = _run(
        _witness(),
        (_print(1400, "B", "101", "20"),),
    )
    assert report["at_quote_print_quantity"] == "0"
    assert all(
        s["conditional_possible_quantity"] == "0"
        for s in report["queue_ahead_stress_scenarios"]
    )
    assert all(
        Decimal(s["conditional_single_entry_fee_discount_usd"]) == 0
        for s in report["queue_ahead_stress_scenarios"]
    )


@pytest.mark.parametrize(("key", "bad"), [
    ("side", "hold"),
    ("quote_price", Decimal("0")),
    ("requested_quantity", Decimal("NaN")),
    ("displayed_best_level_quantity", Decimal("-1")),
    ("baseline_taker_fee_rate", Decimal("Infinity")),
    ("hypothetical_maker_fee_rate", Decimal("-1")),
    ("hypothetical_maker_fee_rate", Decimal("0.0005")),
    ("expire_at_ms", 1000),
])
def test_impossible_quote_identity_rejected(key: str, bad: object) -> None:
    with pytest.raises(MakerEntryWitnessError, match="invalid original maker"):
        _run(replace(_witness(), **{key: bad}), ())


@pytest.mark.parametrize(("events", "clean", "end", "error"), [
    ((), False, 2250, "gaps"),
    ((), True, 2249, "not fully observed"),
    (
        (_print(1300, "A", "100", "1", key="same"),
         _print(1400, "A", "100", "1", key="same")),
        True, 2250, "duplicate",
    ),
    (
        (_print(1450, "A", "100", "1"),
         _print(1300, "A", "100", "1")),
        True, 2250, "reversed",
    ),
    (
        (_print(1300, "A", "100", "1", market="ETH"),),
        True, 2250, "exact-market",
    ),
    (
        (_print(1300, "A", "100", "1", exchange_ms=1350),),
        True, 2250, "exchange clock",
    ),
    (
        (_print(1300, "?", "100", "1"),),
        True, 2250, "aggressor",
    ),
])
def test_source_failures_are_not_converted_to_fee_credits(
    events: tuple[StreamEvent, ...],
    clean: bool, end: int, error: str,
) -> None:
    with pytest.raises(MakerEntryWitnessError, match=error):
        _run(_witness(), events, clean=clean, end=end)


def test_unordered_same_millisecond_trade_is_not_post_quote_fill() -> None:
    report = _run(
        _witness(),
        (
            _print(1250, "A", "90", "100"),
            _print(1300, "A", "100", "1"),
        ),
    )
    assert report["at_quote_print_quantity"] == "1"
    assert report["strictly_through_print_quantity"] == "0"
    assert report["queue_ahead_stress_scenarios"][1][
        "conditional_possible_quantity"
    ] == "0"
