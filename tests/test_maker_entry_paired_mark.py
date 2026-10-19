"""Capital-matched entry-period PAPER cash must include fees and missed winners."""

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
from cocomelon.research.maker_entry_paired_exit_cost import (
    paired_maker_vs_ioc_exit_cost_probe,
)
from cocomelon.research.maker_entry_paired_mark import (
    paired_maker_vs_ioc_entry_mark,
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
        execution_reference_price=Decimal(
            "101" if side is OrderSide.BUY else "100"
        ),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95" if side is OrderSide.BUY else "105"),
        approved_notional_ceiling=Decimal("210"),
        created_at_ms=1000,
        earliest_execution_ms=1250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("15"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.055"),
    )


def _spec() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MarketId("", "BTC"),
        sz_decimals=1,
        venue_max_leverage=Decimal("10"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="mainnet-original",
    )


def _event(
    kind: StreamKind,
    ms: int,
    payload: dict[str, object],
    *,
    market: str = "BTC",
    source: str = "hyperliquid-mainnet-ws",
    key: str | None = None,
    exchange_ms: int | None = None,
) -> StreamEvent:
    return StreamEvent(
        kind=kind,
        market=MarketId("", market),
        exchange_time_ms=ms if exchange_ms is None else exchange_ms,
        receive_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
        schema_version=1,
        source=source,
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
    ms: int,
    side: str,
    price: str,
    volume: str,
    *,
    market: str = "BTC",
    source: str = "hyperliquid-mainnet-ws",
) -> StreamEvent:
    return _event(
        StreamKind.TRADE, ms,
        {"side": side, "price": Decimal(price), "size": Decimal(volume)},
        market=market, source=source,
    )


def _mark(price: str = "103", ms: int = 2500) -> StreamEvent:
    return _event(
        StreamKind.ACTIVE_ASSET_CTX,
        ms,
        {"mark_px": Decimal(price)},
    )


def _pair(
    prints: tuple[StreamEvent, ...],
    *,
    plan: PaperOrderPlan | None = None,
    mark: StreamEvent | None = None,
    book: StreamEvent | None = None,
    clean: bool = True,
    at_ms: int = 2500,
    initial_cash: Decimal = Decimal("10000"),
) -> dict[str, object]:
    original = plan or _plan()
    original_book = book or _book()
    witness = quote_research_only_maker_entry(
        original_plan=original,
        original_book=original_book,
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"),
        quote_at_ms=1250,
        wait_ms=1000,
    )
    return paired_maker_vs_ioc_entry_mark(
        original_plan=original,
        original_book=original_book,
        original_trades=prints,
        original_mark=mark or _mark(),
        maker_witness=witness,
        instrument=_spec(),
        execution_config=PaperExecutionConfig(),
        start_cash=initial_cash,
        mark_at_ms=at_ms,
        source_integrity_passed=clean,
    )


def test_all_filled_maker_only_conditional_both_accounts_costed() -> None:
    report = _pair((_trade(1400, "A", "99", "8"),))
    baseline = report["baseline_entry_account"]
    maker = report["conditional_maker_entry_account"]
    assert isinstance(baseline, dict) and isinstance(maker, dict)
    assert Decimal(baseline["marked_equity_usd"]) == Decimal("10003.9091")
    assert Decimal(baseline["cumulative_fees_usd"]) == Decimal("0.0909")
    assert Decimal(baseline["unrealized_pnl_usd"]) == Decimal("4")
    assert Decimal(maker["marked_equity_usd"]) == Decimal("10005.97")
    assert Decimal(maker["cumulative_fees_usd"]) == Decimal("0.03")
    assert Decimal(maker["unrealized_pnl_usd"]) == Decimal("6")
    assert Decimal(report["conditional_entry_period_marked_delta_usd"]) == (
        Decimal("2.0609")
    )
    assert baseline["starting_cash_usd"] == maker["starting_cash_usd"]
    assert baseline["position_count"] == maker["position_count"] == 1
    assert report["maker_original_venue_fills_confirmed"] is False
    assert report["both_lanes_open_positions_exit_complete"] is False
    assert report["candidate_trade_funding_and_exit_costs_modeled"] is False
    assert report["whole_account_positive_edge_verified"] is False
    assert report["execution_authority"] is False


def test_missed_winner_is_a_real_cost_in_isolated_cash_parity() -> None:
    report = _pair((_trade(1400, "B", "101", "9"),))
    assert report["maker_shadow_modelled_entry_status"] == "no_fill"
    maker = report["conditional_maker_entry_account"]
    assert isinstance(maker, dict)
    assert maker["position_count"] == 0
    assert maker["marked_equity_usd"] == "10000"
    assert maker["cumulative_fees_usd"] == "0"
    assert Decimal(report["conditional_entry_period_marked_delta_usd"]) == (
        Decimal("-3.9091")
    )


def test_partial_maker_entry_costs_exact_quantity_and_mark() -> None:
    report = _pair((
        _trade(1300, "A", "100", "4"),
        _trade(1400, "A", "99", "0.7"),
        _trade(1500, "A", "99", "0.8"),
    ))
    maker = report["conditional_maker_entry_account"]
    assert isinstance(maker, dict)
    assert Decimal(maker["position_quantity"]) == Decimal("0.5")
    assert Decimal(maker["cumulative_fees_usd"]) == Decimal("0.0075")
    assert Decimal(maker["marked_equity_usd"]) == Decimal("10001.4925")
    assert Decimal(report["conditional_entry_period_marked_delta_usd"]) == (
        Decimal("-2.4166")
    )


def test_missing_losing_ioc_trade_can_look_good_but_never_promotes() -> None:
    report = _pair((), mark=_mark("97"))
    assert Decimal(report["conditional_entry_period_marked_delta_usd"]) > 0
    assert report["whole_account_positive_edge_verified"] is False
    assert report["independent_source_continuity_authenticated"] is False
    assert report["promotion_authority"] is False


def test_short_baseline_and_conditional_maker_mark_are_independent() -> None:
    report = _pair(
        (_trade(1400, "B", "102", "9"),),
        plan=_plan(OrderSide.SELL),
        mark=_mark("98"),
    )
    baseline = report["baseline_entry_account"]
    maker = report["conditional_maker_entry_account"]
    assert isinstance(baseline, dict) and isinstance(maker, dict)
    assert Decimal(baseline["marked_equity_usd"]) == Decimal("10003.91")
    assert Decimal(maker["marked_equity_usd"]) == Decimal("10005.9697")
    assert Decimal(report["conditional_entry_period_marked_delta_usd"]) == (
        Decimal("2.0597")
    )


@pytest.mark.parametrize(
    ("mark", "at", "error"),
    [
        (_event(StreamKind.ACTIVE_ASSET_CTX, 2500, {
            "mark_px": Decimal("103"),
        }, market="ETH"), 2500, "market"),
        (_event(StreamKind.ACTIVE_ASSET_CTX, 2500, {
            "mark_px": Decimal("103"),
        }, source="unrelated-tape"), 2500, "market"),
        (_event(StreamKind.ACTIVE_ASSET_CTX, 2500, {
            "mark_px": Decimal("NaN"),
        }), 2500, "mark invalid"),
        (_event(StreamKind.ACTIVE_ASSET_CTX, 2500, {
            "mark_px": Decimal("0"),
        }), 2500, "mark invalid"),
        (_mark("103", 1900), 2500, "stale or future"),
        (_mark("103", 2500), 8000, "stale or future"),
        (_mark("103", 2500), 2000, "market or chronology"),
        (_event(StreamKind.ACTIVE_ASSET_CTX, 2500, {
            "mark_px": Decimal("103"),
        }, exchange_ms=2600), 2500, "stale or future"),
        (_event(StreamKind.ACTIVE_ASSET_CTX, 2500, {
            "mark_px": Decimal("103"),
        }, key="l2_book:BTC:1250"), 2500, "stale or future"),
    ],
)
def test_invalid_or_future_original_mark_never_creates_profit(
    mark: StreamEvent, at: int, error: str,
) -> None:
    with pytest.raises(MakerEntryWitnessError, match=error):
        _pair((), mark=mark, at_ms=at)


def test_maker_entry_account_rejects_failed_capture() -> None:
    with pytest.raises(MakerEntryWitnessError, match="not continuous"):
        _pair((), clean=False)


def test_unmatched_trade_source_is_not_a_maker_book_source() -> None:
    with pytest.raises(MakerEntryWitnessError, match="trade source"):
        _pair((_trade(1400, "A", "99", "8", source="different"),))


@pytest.mark.parametrize("bad_cash", [
    Decimal("0"),
    Decimal("-10"),
    Decimal("NaN"),
    Decimal("Infinity"),
])
def test_cash_seeding_must_be_strictly_positive_finite(bad_cash: Decimal) -> None:
    with pytest.raises(MakerEntryWitnessError, match="start cash"):
        _pair((), initial_cash=bad_cash)


def test_original_duplicate_trade_events_cannot_make_two_paper_positions() -> None:
    event = _trade(1400, "A", "99", "8")
    with pytest.raises(MakerEntryWitnessError, match="duplicate"):
        _pair((event, event))



def _exit_plan(side: OrderSide = OrderSide.BUY) -> PaperOrderPlan:
    source = _plan(side)
    return replace(
        source,
        side=OrderSide.SELL if side is OrderSide.BUY else OrderSide.BUY,
        reduce_only=True,
        stop_price=None,
        approved_risk_amount_ceiling=None,
        stop_distance_fraction=None,
        effective_loss_fraction=None,
        execution_reference_price=Decimal(
            "104" if side is OrderSide.BUY else "98"
        ),
        risk_decision_id="predeclared-exit-risk-1",
        strategy_decision_id="predeclared-exit-signal-1",
        created_at_ms=2900,
        earliest_execution_ms=3200,
    )


def _exit_book(side: OrderSide = OrderSide.BUY) -> StreamEvent:
    return _event(
        StreamKind.L2_BOOK, 3200,
        {
            "bids": [{"px": Decimal(
                "104" if side is OrderSide.BUY else "97"
            ), "sz": Decimal("10")}],
            "asks": [{"px": Decimal(
                "105" if side is OrderSide.BUY else "98"
            ), "sz": Decimal("10")}],
        },
    )


def _closed_pair(
    prints: tuple[StreamEvent, ...],
    *,
    side: OrderSide = OrderSide.BUY,
    exit_book: StreamEvent | None = None,
    exit_plan: PaperOrderPlan | None = None,
    end_mark: StreamEvent | None = None,
    clean: bool = True,
) -> dict[str, object]:
    original = _plan(side)
    book = _book()
    witness = quote_research_only_maker_entry(
        original_plan=original,
        original_book=book,
        execution=PaperExecutionConfig(),
        maker_fee_rate=Decimal("0.00015"),
        quote_at_ms=1250,
        wait_ms=1000,
    )
    return paired_maker_vs_ioc_exit_cost_probe(
        original_opening_plan=original,
        original_exit_plan=exit_plan or _exit_plan(side),
        original_open_book=book,
        original_trades_to_maker_expiry=prints,
        original_exit_book=exit_book or _exit_book(side),
        original_after_exit_mark=end_mark or _mark(
            "104" if side is OrderSide.BUY else "98", ms=3300,
        ),
        maker_witness=witness,
        instrument=_spec(),
        execution_config=PaperExecutionConfig(),
        start_cash=Decimal("10000"),
        exit_at_ms=3200,
        mark_at_ms=3300,
        source_integrity_passed=clean,
    )


def test_closed_long_both_lanes_pay_actual_simulated_entry_and_exit_fees() -> None:
    result = _closed_pair((_trade(1400, "A", "99", "8"),))
    baseline = result["baseline_account"]
    maker = result["conditional_maker_account"]
    assert isinstance(baseline, dict) and isinstance(maker, dict)
    assert Decimal(baseline["marked_equity_usd"]) == Decimal("10005.8155")
    assert Decimal(maker["marked_equity_usd"]) == Decimal("10007.8764")
    assert Decimal(baseline["cumulative_fees_usd"]) == Decimal("0.1845")
    assert Decimal(maker["cumulative_fees_usd"]) == Decimal("0.1236")
    assert Decimal(baseline["realized_gross_pnl_usd"]) == Decimal("6")
    assert Decimal(maker["realized_gross_pnl_usd"]) == Decimal("8")
    assert Decimal(result["single_path_after_exit_marked_delta_usd"]) == (
        Decimal("2.0609")
    )
    assert result["both_lanes_flat_after_original_exit"] is True
    assert result["whole_account_profitable_edge_proven"] is False
    assert result["funding_boundaries_and_multi_trade_capacity_modeled"] is False
    assert result["real_maker_fills_confirmed"] is False
    assert result["promotion_authority"] is False


def test_closed_maker_missed_winner_exposes_full_gross_and_fee_opportunity() -> None:
    result = _closed_pair((_trade(1400, "B", "101", "9"),))
    maker = result["conditional_maker_account"]
    assert isinstance(maker, dict)
    assert Decimal(maker["marked_equity_usd"]) == Decimal("10000")
    assert maker["position_count"] == 0
    assert maker["cumulative_fees_usd"] == "0"
    assert Decimal(result["single_path_after_exit_marked_delta_usd"]) == (
        Decimal("-5.8155")
    )
    assert result["conditional_maker_exit_result"] == "no_entry"


def test_partial_maker_exit_charges_only_actual_conditional_quantity() -> None:
    result = _closed_pair((
        _trade(1300, "A", "100", "4"),
        _trade(1400, "A", "99", "0.7"),
        _trade(1500, "A", "99", "0.8"),
    ))
    maker = result["conditional_maker_account"]
    assert isinstance(maker, dict)
    assert Decimal(result["conditional_maker_exit_quantity"]) == Decimal("0.5")
    assert Decimal(maker["realized_gross_pnl_usd"]) == Decimal("2")
    assert Decimal(maker["cumulative_fees_usd"]) == Decimal("0.0309")
    assert Decimal(maker["marked_equity_usd"]) == Decimal("10001.9691")
    assert result["both_lanes_flat_after_original_exit"] is True


def test_short_funding_free_single_exit_costs_are_side_correct() -> None:
    result = _closed_pair(
        (_trade(1400, "B", "102", "9"),), side=OrderSide.SELL,
    )
    baseline = result["baseline_account"]
    maker = result["conditional_maker_account"]
    assert isinstance(baseline, dict) and isinstance(maker, dict)
    assert Decimal(baseline["marked_equity_usd"]) == Decimal("10003.8218")
    assert Decimal(maker["marked_equity_usd"]) == Decimal("10005.8815")
    assert Decimal(result["single_path_after_exit_marked_delta_usd"]) == (
        Decimal("2.0597")
    )
    assert result["both_lanes_flat_after_original_exit"] is True


def test_closed_no_maker_fill_on_losing_original_is_not_promotion_evidence() -> None:
    loss_exit = _event(
        StreamKind.L2_BOOK, 3200,
        {"bids": [{"px": Decimal("97"), "sz": Decimal("10")}],
         "asks": [{"px": Decimal("98"), "sz": Decimal("10")}]},
    )
    loss_plan = replace(
        _exit_plan(), execution_reference_price=Decimal("97")
    )
    result = _closed_pair((), exit_book=loss_exit, exit_plan=loss_plan)
    assert Decimal(result["single_path_after_exit_marked_delta_usd"]) > 0
    assert result["whole_account_profitable_edge_proven"] is False


def test_closed_exit_probe_refuses_failed_original_or_hindsight_exit() -> None:
    with pytest.raises(MakerEntryWitnessError, match="source failed"):
        _closed_pair((), clean=False)
    with pytest.raises(MakerEntryWitnessError, match="lineage"):
        _closed_pair((), exit_plan=replace(
            _exit_plan(), created_at_ms=2000,
        ))
    with pytest.raises(MakerEntryWitnessError, match="book or mark"):
        _closed_pair((), exit_book=_event(
            StreamKind.L2_BOOK, 3200,
            {"bids": (), "asks": ()}, market="ETH",
        ))
    with pytest.raises(MakerEntryWitnessError, match="mark untrusted"):
        _closed_pair((), end_mark=_mark("104", ms=2500))


def test_rejected_exit_never_becomes_cost_free_close() -> None:
    # Original exit price is not guaranteed: only actual book depth
    # within predeclared slippage can release a PAPER position.
    thin_exit = _event(
        StreamKind.L2_BOOK, 3200,
        {"bids": [{"px": Decimal("80"), "sz": Decimal("10")}],
         "asks": [{"px": Decimal("81"), "sz": Decimal("10")}]},
    )
    report = _closed_pair((), exit_book=thin_exit)
    baseline = report["baseline_account"]
    assert isinstance(baseline, dict)
    assert Decimal(report["baseline_ioc_exit_quantity"]) == Decimal("0")
    assert report["both_lanes_flat_after_original_exit"] is False
    assert baseline["position_count"] == 1
    assert report["whole_account_profitable_edge_proven"] is False
