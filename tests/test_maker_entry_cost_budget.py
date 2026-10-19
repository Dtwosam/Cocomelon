"""Fee-only maker budget must never manufacture capital-matched trade profit."""

from __future__ import annotations

from copy import deepcopy
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
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.research.maker_entry_cost_budget import (
    MakerEntryCostBudgetError,
    maker_entry_closed_trade_cost_budget,
)
from cocomelon.research.maker_entry_feasibility import (
    quote_research_only_maker_entry,
    review_original_trade_through,
)

TAKER = Decimal("0.00045")
MAKER = Decimal("0.00015")
ENTRY_FEE = Decimal("0.09")
EXIT_FEE = Decimal("0.09")


def _plan(i: int, direction: Direction) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id=f"risk-{i}",
        strategy_decision_id=f"strategy-{i}",
        market=MarketId("", "BTC"),
        side=OrderSide.BUY if direction is Direction.LONG else OrderSide.SELL,
        requested_quantity=Decimal("2"),
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("95") if direction is Direction.LONG else Decimal("105"),
        approved_notional_ceiling=Decimal("220"),
        created_at_ms=1000,
        earliest_execution_ms=1250,
        execution_config_version="phase7-v1",
        instrument_metadata_received_at_ms=900,
        approved_risk_amount_ceiling=Decimal("15"),
        stop_distance_fraction=Decimal("0.05"),
        effective_loss_fraction=Decimal("0.055"),
    )


def _trade(i: int, net: str, direction: Direction = Direction.LONG) -> tuple[
    TradeJournalEntry, PaperOrderPlan
]:
    plan = _plan(i, direction)
    amount = Decimal(net)
    gross = amount + ENTRY_FEE + EXIT_FEE
    return (
        TradeJournalEntry(
            market=plan.market,
            direction=direction,
            opened_at_ms=1500,
            closed_at_ms=4000,
            feature_snapshot_id=f"feature-{i}",
            strategy_decision_id=f"strategy-{i}",
            risk_decision_id=f"risk-{i}",
            opening_plan_id=plan.plan_id,
            opening_attempt_id=f"open-attempt-{i}",
            exit_plan_ids=(f"exit-plan-{i}",),
            exit_attempt_ids=(f"exit-attempt-{i}",),
            fill_ids=(f"open-fill-{i}", f"exit-fill-{i}"),
            position_action_ids=(),
            funding_event_ids=(),
            initial_stop=plan.stop_price or Decimal("95"),
            initial_risk_amount=Decimal("10"),
            entry_price=Decimal("100"),
            exit_price=(
                Decimal("100") + gross / Decimal("2")
                if direction is Direction.LONG
                else Decimal("100") - gross / Decimal("2")
            ),
            filled_quantity=Decimal("2"),
            gross_realized_pnl=gross,
            entry_fees=ENTRY_FEE,
            exit_fees=EXIT_FEE,
            funding_cash_pnl=Decimal("0"),
            net_pnl=amount,
            entry_slippage_amount=Decimal("0"),
            exit_slippage_amount=Decimal("0"),
            entry_slippage_fraction=Decimal("0"),
            exit_slippage_fraction=Decimal("0"),
            holding_duration_ms=2500,
            mfe=None,
            mae=None,
            net_r=amount / Decimal("10"),
            equity_before=Decimal("10000"),
            equity_after=Decimal("10000") + amount,
            exit_reason="MARK_STOP_TRIGGERED",
            health_refs=("PAPER",),
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            replay_run_id="same-fills-unit-test",
        ),
        plan,
    )


def _book(ms: int = 1250) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MarketId("", "BTC"),
        exchange_time_ms=ms,
        receive_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"l2Book:BTC:{ms}",
        payload={
            "bids": [{"px": Decimal("100"), "sz": Decimal("5")}],
            "asks": [{"px": Decimal("101"), "sz": Decimal("5")}],
        },
    )


def _review(plan: PaperOrderPlan, crossing_qty: str) -> dict[str, object]:
    quote = quote_research_only_maker_entry(
        original_plan=plan,
        original_book=_book(),
        execution=PaperExecutionConfig(),
        maker_fee_rate=MAKER,
        quote_at_ms=1250,
        wait_ms=1000,
    )
    qty = Decimal(crossing_qty)
    prints = () if qty == Decimal("0") else (
        StreamEvent(
            kind=StreamKind.TRADE,
            market=plan.market,
            exchange_time_ms=1500,
            receive_time=datetime.fromtimestamp(1.5, tz=UTC),
            schema_version=1,
            source="hyperliquid-mainnet-ws",
            event_key=f"trade:{plan.plan_id}",
            payload={
                "side": "A" if plan.side is OrderSide.BUY else "B",
                "price": Decimal("100") if plan.side is OrderSide.BUY
                else Decimal("101"),
                "size": qty,
            },
        ),
    )
    return review_original_trade_through(
        quote,
        original_events=prints,
        observation_end_ms=2250,
        source_integrity_passed=True,
    )


def _cohort(
    pnls: tuple[str, ...],
    quantities: tuple[str, ...] | None = None,
) -> tuple[tuple[TradeJournalEntry, ...], dict[str, dict[str, object]]]:
    if quantities is None:
        quantities = tuple("2" for _ in pnls)
    assert len(pnls) == len(quantities)
    rows: list[TradeJournalEntry] = []
    receipts: dict[str, dict[str, object]] = {}
    for i, (pnl, quantity) in enumerate(zip(pnls, quantities, strict=True)):
        trade, plan = _trade(
            i + 1, pnl,
            Direction.LONG if i % 2 == 0 else Direction.SHORT,
        )
        rows.append(trade)
        receipts[plan.plan_id] = _review(plan, quantity)
    return tuple(rows), receipts


def _run(
    trades: tuple[TradeJournalEntry, ...],
    reviews: dict[str, dict[str, object]],
) -> dict[str, object]:
    return maker_entry_closed_trade_cost_budget(
        trades, reviews, taker_fee_rate=TAKER, maker_fee_rate=MAKER
    )


def test_entry_maker_discount_still_loses_after_all_original_exits() -> None:
    trades, reviews = _cohort(("1.0", "-2.0", "0.2"), ("2", "0.5", "0"))
    report = _run(trades, reviews)
    assert report["closed_trades"] == 3
    assert report["original_booked_gross_usd"] == "-0.26"
    assert report["original_booked_entry_fees_usd"] == "0.27"
    assert report["original_booked_exit_fees_usd"] == "0.27"
    assert report["original_booked_net_usd"] == "-0.8"
    assert Decimal(report["exact_entry_fee_discount_fraction"]) == Decimal("2") / 3
    assert report["all_original_entries_same_fill_fee_only_saving_usd"] == "0.18"
    assert report["all_original_entries_same_fill_net_usd"] == "-0.62"
    assert report["all_entry_fee_discount_still_nonpositive"] is True
    assert report["additional_non_fee_gross_needed_to_reach_zero_usd"] == "0.62"
    assert report["hypothetical_net_if_largest_positive_trade_missed_usd"] == "-1.68"
    assert report["hypothetical_net_if_top_three_positive_trades_missed_usd"] == "-1.94"
    assert report["original_tape_could_support_full_size_count_not_certified"] == 1
    assert report["original_tape_rules_out_full_size_count"] == 2
    assert report["original_tape_zero_crossing_qty_count"] == 1
    assert report["guaranteed_maker_fills"] == 0
    assert report["realized_maker_fee_savings_usd"] is None
    assert report["maker_strategy_whole_account_net_usd"] is None
    assert report["independent_paired_account_positive_edge_proven"] is False
    assert report["execution_authority"] is False


def test_missing_one_winner_erases_positive_fee_only_surplus() -> None:
    trades, reviews = _cohort(("1.0", "-0.3"))
    report = _run(trades, reviews)
    assert report["original_booked_net_usd"] == "0.7"
    assert report["all_original_entries_same_fill_net_usd"] == "0.82"
    assert report["hypothetical_surplus_to_absorb_missed_winner_usd"] == "0.82"
    assert report["hypothetical_net_if_largest_positive_trade_missed_usd"] == "-0.24"
    assert report["hypothetical_net_if_top_three_positive_trades_missed_usd"] == "-0.24"
    assert report["maker_strategy_whole_account_net_usd"] is None


def test_zero_entry_fees_do_not_offer_free_maker_profit() -> None:
    trades, reviews = _cohort(("-1",))
    trade = trades[0]
    modified = replace(
        trade,
        entry_fees=Decimal("0"),
        gross_realized_pnl=trade.gross_realized_pnl - trade.entry_fees,
    )
    report = _run((modified,), reviews)
    assert report["all_original_entries_same_fill_fee_only_saving_usd"] == "0"
    assert report["all_entry_fee_discount_still_nonpositive"] is True
    assert report["entry_fee_refund_fraction_needed_for_zero"] is None


def test_duplicate_and_missing_witnesses_are_not_zero_cost() -> None:
    trades, reviews = _cohort(("-1", "2"))
    with pytest.raises(MakerEntryCostBudgetError, match="unpaired"):
        _run(trades, {trades[0].opening_plan_id: reviews[trades[0].opening_plan_id]})
    with pytest.raises(MakerEntryCostBudgetError, match="duplicate"):
        _run((trades[0], trades[0]), reviews)


@pytest.mark.parametrize(("path", "value"), [
    (("research_only",), False),
    (("maker_fill_certified",), True),
    (("execution_authority",), True),
    (("source_external_authentication_certified",), True),
    (("maker_fee_savings_realized_usd",), "10"),
    (("candidate_after_cost_pnl_usd",), "2"),
    (("quote", "resting_order_submitted"), True),
    (("quote", "opening_plan_id"), "different"),
    (("quote", "market"), "ETH"),
    (("quote", "baseline_taker_fee_rate"), "0.0"),
    (("quote", "hypothetical_maker_fee_rate"), "0.0"),
])
def test_cannot_promote_tampered_queue_proof_or_profit(
    path: tuple[str, ...], value: object,
) -> None:
    trades, reviews = _cohort(("1",))
    corrupted = deepcopy(reviews)
    row: dict[str, object] = corrupted[trades[0].opening_plan_id]
    if len(path) == 2:
        raw = row[path[0]]
        assert isinstance(raw, dict)
        raw[path[1]] = value
    else:
        row[path[0]] = value
    with pytest.raises(MakerEntryCostBudgetError, match="identity or authority"):
        _run(trades, corrupted)


@pytest.mark.parametrize(("path", "value", "message"), [
    (("quote", "requested_quantity"), "1", "quoted size"),
    (("quote", "quote_price"), "NaN", "finite nonnegative"),
    (("quote", "expire_at_ms"), 5000, "chronology"),
    (("quote", "quote_at_ms"), 1600, "chronology"),
    (("quote", "fee_savings_if_entire_entry_filled_same_notional"), "5", "mismatch"),
    (("possible_entry_fill_quantity_upper_bound",), "3", "mismatch"),
    (("possible_entry_fill_quantity_upper_bound",), "-0.1", "finite nonnegative"),
])
def test_cannot_use_contradictory_quote_size_or_future_receipt(
    path: tuple[str, ...], value: object, message: str,
) -> None:
    trades, reviews = _cohort(("1",))
    corrupted = deepcopy(reviews)
    row: dict[str, object] = corrupted[trades[0].opening_plan_id]
    if len(path) == 2:
        raw = row[path[0]]
        assert isinstance(raw, dict)
        raw[path[1]] = value
    else:
        row[path[0]] = value
    with pytest.raises(MakerEntryCostBudgetError, match=message):
        _run(trades, corrupted)


@pytest.mark.parametrize(("taker", "maker"), [
    (Decimal("0"), Decimal("0")),
    (Decimal("0.00045"), Decimal("0.00045")),
    (Decimal("0.00045"), Decimal("-1")),
    (Decimal("NaN"), Decimal("0.00015")),
])
def test_fee_schedule_must_be_finite_saving_taker_vs_maker(
    taker: Decimal, maker: Decimal,
) -> None:
    trades, reviews = _cohort(("1",))
    with pytest.raises(MakerEntryCostBudgetError, match="fee schedule"):
        maker_entry_closed_trade_cost_budget(
            trades, reviews, taker_fee_rate=taker, maker_fee_rate=maker
        )


def test_empty_closed_cohort_can_never_claim_strategy_profit() -> None:
    with pytest.raises(MakerEntryCostBudgetError, match="nonempty"):
        _run((), {})
