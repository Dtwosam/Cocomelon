from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.prospective_side_conditioned_delay import (
    CANDIDATE_ID,
    ProspectiveSideConditionedDelayError,
    ProspectiveSideConditionedDelayState,
    prospective_side_conditioned_delay_summary,
)

RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    suffix: str,
    direction: Direction,
    *,
    opened_at_ms: int,
    exit_price: str,
) -> TradeJournalEntry:
    market = MarketId("", "SOL" if direction is Direction.LONG else "BTC")
    entry = Decimal("100")
    exit_px = Decimal(exit_price)
    gross = (
        exit_px - entry
        if direction is Direction.LONG
        else entry - exit_px
    )
    return TradeJournalEntry(
        market=market,
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
        entry_price=entry,
        exit_price=exit_px,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=gross,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=gross,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=300_000,
        mfe=None,
        mae=None,
        net_r=gross / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + gross,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _delayed(
    trade: TradeJournalEntry,
    *,
    price: str,
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
        delayed_fee=Decimal("0"),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=(
            signed / trade.entry_price * Decimal("10000")
        ),
        gross_r_improvement=signed / trade.initial_risk_amount,
    )


def test_side_conditioned_delay_uses_120_long_and_60_short(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        long = _trade(
            "long",
            Direction.LONG,
            opened_at_ms=2_000_000,
            exit_price="105",
        )
        short = _trade(
            "short",
            Direction.SHORT,
            opened_at_ms=3_000_000,
            exit_price="95",
        )
        before = _trade(
            "before",
            Direction.LONG,
            opened_at_ms=500_000,
            exit_price="105",
        )
        for trade in (long, short, before):
            journal.record_trade(trade)

        result = prospective_side_conditioned_delay_summary(
            journal,
            (
                _delayed(long, price="99"),
                _delayed(short, price="101"),
                _delayed(before, price="99"),
            ),
            (
                _delayed(long, price="98"),
                _delayed(short, price="102"),
                _delayed(before, price="98"),
            ),
            ProspectiveSideConditionedDelayState(
                started_at_ms=1_000_000
            ),
        )
    finally:
        journal.close()

    assert result["candidate_id"] == CANDIDATE_ID
    assert result["prospective_closed_trades"] == 2
    assert result["paired_evaluable_trades"] == 2
    overall = result["overall"]
    assert overall["actual_net_pnl"] == "10"
    assert overall["always_60s_net_pnl"] == "12"
    assert overall["always_120s_net_pnl"] == "14"
    assert overall["selected_net_pnl"] == "13"
    by_side = result["by_side"]
    assert by_side["long"]["selected_net_pnl"] == "7"
    assert by_side["short"]["selected_net_pnl"] == "6"
    assert result["readiness"]["ready_for_review"] is False


def test_side_conditioned_delay_state_round_trip_freezes_rule() -> None:
    state = ProspectiveSideConditionedDelayState(started_at_ms=123)
    restored = ProspectiveSideConditionedDelayState.from_payload(
        state.payload()
    )
    assert restored == state

    payload = state.payload()
    payload["rule"] = {
        "long_delay_ms": 60_000,
        "short_delay_ms": 60_000,
        "direction_policy": "both_directions_remain_eligible",
    }
    with pytest.raises(
        ProspectiveSideConditionedDelayError,
        match="frozen candidate",
    ):
        ProspectiveSideConditionedDelayState.from_payload(payload)
