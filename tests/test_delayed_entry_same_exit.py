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
from cocomelon.research.delayed_entry_same_exit import (
    delayed_entry_same_exit_contribution,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    net_pnl: str,
    entry_fee: str = "0.5",
) -> TradeJournalEntry:
    pnl = Decimal(net_pnl)
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
        fill_ids=(f"open-fill-{suffix}", f"exit-fill-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        filled_quantity=Decimal("2"),
        gross_realized_pnl=Decimal("0"),
        entry_fees=Decimal(entry_fee),
        exit_fees=Decimal("0"),
        funding_cash_pnl=pnl + Decimal(entry_fee),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=pnl / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    delayed_price: str,
    delayed_fee: str,
    source: str = "full_visible_book_ioc",
) -> DelayedEntryOutcome:
    price = Decimal(delayed_price)
    signed = (
        trade.entry_price - price
        if trade.direction is Direction.LONG
        else price - trade.entry_price
    )
    gross_r = (
        signed * trade.filled_quantity
        / trade.initial_risk_amount
    )
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=trade.filled_quantity,
        delayed_average_fill_price=price,
        delayed_fee=Decimal(delayed_fee),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=(
            signed / trade.entry_price * Decimal("10000")
            if source == "full_visible_book_ioc"
            else None
        ),
        gross_r_improvement=(
            gross_r
            if source == "full_visible_book_ioc"
            else None
        ),
    )


def test_same_exit_contribution_reprices_entry_and_entry_fee(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        long_trade = _trade(
            suffix="long",
            direction=Direction.LONG,
            net_pnl="-1",
        )
        short_trade = _trade(
            suffix="short",
            direction=Direction.SHORT,
            net_pnl="-1",
        )
        journal.record_trade(long_trade)
        journal.record_trade(short_trade)

        result = delayed_entry_same_exit_contribution(
            journal,
            (
                _outcome(
                    long_trade,
                    delayed_price="99",
                    delayed_fee="0.4",
                ),
                _outcome(
                    short_trade,
                    delayed_price="101",
                    delayed_fee="0.4",
                ),
            ),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 2
    assert overall["actual_losses"] == 2
    assert overall["candidate_wins_estimate"] == 2
    assert overall["loss_to_win_flips_estimate"] == 2
    assert overall["actual_net_pnl"] == "-2"
    assert overall["candidate_net_pnl_estimate"] == "2.2"
    assert overall["delta_net_pnl_estimate"] == "4.2"
    assert overall["mean_delta_net_r_estimate"] == "0.21"
    assert result["funding_assumption"] == (
        "actual_trade_funding_held_constant"
    )
    assert result["exit_assumption"] == (
        "actual_trade_exit_price_and_exit_fee_held_constant"
    )


def test_same_exit_contribution_ignores_non_full_shadow_outcomes(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="partial",
            direction=Direction.LONG,
            net_pnl="-2",
        )
        journal.record_trade(trade)
        partial = DelayedEntryOutcome(
            trade_id=trade.trade_id,
            opening_plan_id=trade.opening_plan_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source="partial_visible_book_ioc",
            delayed_filled_quantity=Decimal("1"),
            delayed_average_fill_price=Decimal("99"),
            delayed_fee=Decimal("0.2"),
            observation_lag_ms=1_000,
            signed_price_improvement_bps=None,
            gross_r_improvement=None,
        )
        result = delayed_entry_same_exit_contribution(
            journal,
            (partial,),
        )
    finally:
        journal.close()

    assert result["closed_shadow_outcomes"] == 1
    assert result["full_delayed_fill_outcomes"] == 0
    assert result["evaluated_full_delayed_fills"] == 0
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_same_exit_contribution_counts_lineage_mismatch(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="mismatch",
            direction=Direction.LONG,
            net_pnl="-2",
        )
        journal.record_trade(trade)
        outcome = _outcome(
            trade,
            delayed_price="99",
            delayed_fee="0.4",
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
        result = delayed_entry_same_exit_contribution(
            journal,
            (mismatched,),
        )
    finally:
        journal.close()

    assert result["full_delayed_fill_outcomes"] == 1
    assert result["evaluated_full_delayed_fills"] == 0
    assert result["lineage_mismatches"] == 1
