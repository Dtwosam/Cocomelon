from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    delayed_entry_fill_weighted_contribution,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    exit_price: str,
    entry_fee: str = "0.5",
    exit_fee: str = "0.5",
    funding: str = "0",
) -> TradeJournalEntry:
    entry = Decimal("100")
    exit_px = Decimal(exit_price)
    quantity = Decimal("2")
    gross = (
        (exit_px - entry) * quantity
        if direction is Direction.LONG
        else (entry - exit_px) * quantity
    )
    entry_fees = Decimal(entry_fee)
    exit_fees = Decimal(exit_fee)
    funding_pnl = Decimal(funding)
    net = gross - entry_fees - exit_fees + funding_pnl
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=1_000,
        closed_at_ms=61_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(
            f"open-fill-{suffix}",
            f"exit-fill-{suffix}",
        ),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=exit_px,
        filled_quantity=quantity,
        gross_realized_pnl=gross,
        entry_fees=entry_fees,
        exit_fees=exit_fees,
        funding_cash_pnl=funding_pnl,
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    quantity: str,
    price: str | None,
    fee: str,
) -> DelayedEntryOutcome:
    delayed_quantity = Decimal(quantity)
    delayed_price = None if price is None else Decimal(price)
    signed_bps: Decimal | None = None
    gross_r: Decimal | None = None
    if source == "full_visible_book_ioc":
        assert delayed_price is not None
        signed = (
            trade.entry_price - delayed_price
            if trade.direction is Direction.LONG
            else delayed_price - trade.entry_price
        )
        signed_bps = (
            signed / trade.entry_price * Decimal("10000")
        )
        gross_r = (
            signed * delayed_quantity
            / trade.initial_risk_amount
        )
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=delayed_quantity,
        delayed_average_fill_price=delayed_price,
        delayed_fee=Decimal(fee),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=signed_bps,
        gross_r_improvement=gross_r,
    )


def test_fill_weighted_contribution_prices_partial_and_no_fill(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        full = _trade(
            suffix="full",
            direction=Direction.LONG,
            exit_price="102",
        )
        partial = _trade(
            suffix="partial",
            direction=Direction.LONG,
            exit_price="102",
        )
        no_fill_loss = _trade(
            suffix="no-fill",
            direction=Direction.LONG,
            exit_price="98",
        )
        for trade in (full, partial, no_fill_loss):
            journal.record_trade(trade)

        result = delayed_entry_fill_weighted_contribution(
            journal,
            (
                _outcome(
                    full,
                    source="full_visible_book_ioc",
                    quantity="2",
                    price="99",
                    fee="0.4",
                ),
                _outcome(
                    partial,
                    source="partial_visible_book_ioc",
                    quantity="1",
                    price="99",
                    fee="0.2",
                ),
                _outcome(
                    no_fill_loss,
                    source="no_fill",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 3
    assert overall["actual_wins"] == 2
    assert overall["actual_losses"] == 1
    assert overall["candidate_positive_contributions"] == 2
    assert overall["candidate_zero_contributions"] == 1
    assert overall["candidate_better_than_actual"] == 2
    assert overall["candidate_worse_than_actual"] == 1
    assert overall["actual_loss_to_nonnegative_contribution"] == 1
    assert overall["actual_net_pnl"] == "1.0"
    assert overall["candidate_fill_weighted_net_pnl"] == "7.65"
    assert overall["delta_net_pnl_estimate"] == "6.65"
    assert overall["mean_fill_fraction"] == "0.5"

    by_source = result["by_source"]
    assert isinstance(by_source, dict)
    full_summary = by_source["full_visible_book_ioc"]
    partial_summary = by_source["partial_visible_book_ioc"]
    no_fill_summary = by_source["no_fill"]
    assert full_summary["candidate_fill_weighted_net_pnl"] == "5.1"
    assert partial_summary["candidate_fill_weighted_net_pnl"] == "2.55"
    assert no_fill_summary["candidate_fill_weighted_net_pnl"] == "0"


def test_no_fill_can_miss_an_actual_winner(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        winner = _trade(
            suffix="winner",
            direction=Direction.SHORT,
            exit_price="98",
        )
        journal.record_trade(winner)
        result = delayed_entry_fill_weighted_contribution(
            journal,
            (
                _outcome(
                    winner,
                    source="no_fill",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["actual_win_to_nonpositive_contribution"] == 1
    assert overall["actual_net_pnl"] == "3.0"
    assert overall["candidate_fill_weighted_net_pnl"] == "0"
    assert overall["delta_net_pnl_estimate"] == "-3.0"


def test_unresolved_sources_are_not_treated_as_zero_contribution(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="expired",
            direction=Direction.LONG,
            exit_price="98",
        )
        journal.record_trade(trade)
        result = delayed_entry_fill_weighted_contribution(
            journal,
            (
                _outcome(
                    trade,
                    source="expired",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
        )
    finally:
        journal.close()

    assert result["closed_shadow_outcomes"] == 1
    assert result["evaluated_delayed_attempts"] == 0
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 0
    source_counts = result["source_counts"]
    assert isinstance(source_counts, dict)
    assert source_counts["expired"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_lineage_mismatch_is_reported(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="mismatch",
            direction=Direction.LONG,
            exit_price="102",
        )
        journal.record_trade(trade)
        outcome = _outcome(
            trade,
            source="partial_visible_book_ioc",
            quantity="1",
            price="99",
            fee="0.2",
        )
        mismatched = DelayedEntryOutcome(
            trade_id=outcome.trade_id,
            opening_plan_id="wrong-plan",
            market=outcome.market,
            direction=outcome.direction,
            source=outcome.source,
            delayed_filled_quantity=outcome.delayed_filled_quantity,
            delayed_average_fill_price=outcome.delayed_average_fill_price,
            delayed_fee=outcome.delayed_fee,
            observation_lag_ms=outcome.observation_lag_ms,
            signed_price_improvement_bps=(
                outcome.signed_price_improvement_bps
            ),
            gross_r_improvement=outcome.gross_r_improvement,
        )
        result = delayed_entry_fill_weighted_contribution(
            journal,
            (mismatched,),
        )
    finally:
        journal.close()

    assert result["evaluated_delayed_attempts"] == 0
    assert result["lineage_mismatches"] == 1
