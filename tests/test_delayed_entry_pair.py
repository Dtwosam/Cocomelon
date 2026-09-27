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
from cocomelon.research.delayed_entry_pair import (
    delayed_entry_pair_summary,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    net_pnl: str,
) -> TradeJournalEntry:
    pnl = Decimal(net_pnl)
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 300_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-close-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=pnl + Decimal("0.05"),
        entry_fees=Decimal("0.05"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=300_000,
        mfe=None,
        mae=None,
        net_r=pnl / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    price: str,
    fee: str,
) -> DelayedEntryOutcome:
    px = Decimal(price)
    signed = (
        trade.entry_price - px
        if trade.direction is Direction.LONG
        else px - trade.entry_price
    )
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source="full_visible_book_ioc",
        delayed_filled_quantity=trade.filled_quantity,
        delayed_average_fill_price=px,
        delayed_fee=Decimal(fee),
        observation_lag_ms=500,
        signed_price_improvement_bps=(
            signed / trade.entry_price * Decimal("10000")
        ),
        gross_r_improvement=(
            signed * trade.filled_quantity
            / trade.initial_risk_amount
        ),
    )


def test_pair_compares_only_future_full_fills_and_is_direction_symmetric(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        old = _trade(
            suffix="old",
            direction=Direction.LONG,
            opened_at_ms=500,
            net_pnl="-1",
        )
        long_trade = _trade(
            suffix="long",
            direction=Direction.LONG,
            opened_at_ms=2_000,
            net_pnl="-2",
        )
        short_trade = _trade(
            suffix="short",
            direction=Direction.SHORT,
            opened_at_ms=3_000,
            net_pnl="1",
        )
        for trade in (old, long_trade, short_trade):
            journal.record_trade(trade)

        base = (
            _outcome(old, price="99", fee="0.04"),
            _outcome(long_trade, price="99", fee="0.04"),
            _outcome(short_trade, price="101", fee="0.04"),
        )
        challenger = (
            _outcome(old, price="98", fee="0.04"),
            _outcome(long_trade, price="98", fee="0.04"),
            _outcome(short_trade, price="100.5", fee="0.04"),
        )

        result = delayed_entry_pair_summary(
            journal,
            base,
            challenger,
            started_at_ms=1_000,
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 2
    assert result["paired_full_fills"] == 2
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["challenger_better"] == 1
    assert overall["base_better"] == 1
    assert overall["equal"] == 0
    by_side = result["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["challenger_minus_base_pnl"] == "1.00"
    assert by_side["short"]["challenger_minus_base_pnl"] == "-0.50"
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_pair_tracks_non_full_challenger_without_guessing(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="partial",
            direction=Direction.LONG,
            opened_at_ms=2_000,
            net_pnl="-2",
        )
        journal.record_trade(trade)
        base = (_outcome(trade, price="99", fee="0.04"),)
        challenger_full = _outcome(
            trade,
            price="98",
            fee="0.04",
        )
        challenger = (
            DelayedEntryOutcome(
                trade_id=challenger_full.trade_id,
                opening_plan_id=challenger_full.opening_plan_id,
                market=challenger_full.market,
                direction=challenger_full.direction,
                source="partial_visible_book_ioc",
                delayed_filled_quantity=Decimal("0.5"),
                delayed_average_fill_price=Decimal("98"),
                delayed_fee=Decimal("0.02"),
                observation_lag_ms=500,
                signed_price_improvement_bps=None,
                gross_r_improvement=None,
            ),
        )

        result = delayed_entry_pair_summary(
            journal,
            base,
            challenger,
            started_at_ms=1_000,
        )
    finally:
        journal.close()

    assert result["paired_full_fills"] == 0
    assert result["non_full_challenger"] == 1
    assert result["missing_base_outcome"] == 0
    assert result["missing_challenger_outcome"] == 0
