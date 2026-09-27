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
from cocomelon.research.fill_aware_delay_selector import (
    FILL_AWARE_DELAY_SELECTOR_ID,
    FillAwareDelaySelectorError,
    FillAwareDelaySelectorState,
    fill_aware_delay_selector_summary,
)

RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    exit_price: str,
    market: MarketId,
) -> TradeJournalEntry:
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


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    price: str | None,
    quantity: str,
) -> DelayedEntryOutcome:
    fill_qty = Decimal(quantity)
    fill_px = None if price is None else Decimal(price)
    improvement_bps: Decimal | None = None
    gross_r: Decimal | None = None
    if fill_px is not None:
        signed = (
            trade.entry_price - fill_px
            if trade.direction is Direction.LONG
            else fill_px - trade.entry_price
        )
        improvement_bps = (
            signed / trade.entry_price * Decimal("10000")
        )
        gross_r = (
            signed
            * fill_qty
            / trade.initial_risk_amount
        )
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=fill_qty,
        delayed_average_fill_price=fill_px,
        delayed_fee=Decimal("0"),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=improvement_bps,
        gross_r_improvement=gross_r,
    )


def test_fill_aware_selector_uses_60s_only_for_full_fill(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        full = _trade(
            suffix="full",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            exit_price="102",
            market=MarketId("", "SOL"),
        )
        partial = _trade(
            suffix="partial",
            direction=Direction.SHORT,
            opened_at_ms=2_000_000,
            exit_price="98",
            market=MarketId("", "BTC"),
        )
        no_fill = _trade(
            suffix="no-fill",
            direction=Direction.LONG,
            opened_at_ms=3_000_000,
            exit_price="99",
            market=MarketId("", "ETH"),
        )
        for trade in (full, partial, no_fill):
            journal.record_trade(trade)

        result = fill_aware_delay_selector_summary(
            journal,
            (
                _outcome(
                    full,
                    source="full_visible_book_ioc",
                    price="99",
                    quantity="1",
                ),
                _outcome(
                    partial,
                    source="partial_visible_book_ioc",
                    price="101",
                    quantity="0.5",
                ),
                _outcome(
                    no_fill,
                    source="no_fill",
                    price=None,
                    quantity="0",
                ),
            ),
            (
                _outcome(
                    full,
                    source="full_visible_book_ioc",
                    price="98.5",
                    quantity="1",
                ),
                _outcome(
                    partial,
                    source="full_visible_book_ioc",
                    price="102",
                    quantity="1",
                ),
                _outcome(
                    no_fill,
                    source="full_visible_book_ioc",
                    price="98",
                    quantity="1",
                ),
            ),
            started_at_ms=900_000,
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 3
    assert result["causal_evaluable_trades"] == 3
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["selected_60s"] == 1
    assert overall["selected_120s"] == 2
    assert overall["mean_selected_fill_fraction"] == "1"

    by_source = result["by_60s_source"]
    assert isinstance(by_source, dict)
    assert by_source["full_visible_book_ioc"]["selected_60s"] == 1
    assert by_source["partial_visible_book_ioc"]["selected_120s"] == 1
    assert by_source["no_fill"]["selected_120s"] == 1

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_fill_aware_selector_excludes_prestart_and_non_evaluable(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        old = _trade(
            suffix="old",
            direction=Direction.LONG,
            opened_at_ms=500_000,
            exit_price="101",
            market=MarketId("", "SOL"),
        )
        current = _trade(
            suffix="current",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            exit_price="101",
            market=MarketId("", "ETH"),
        )
        journal.record_trade(old)
        journal.record_trade(current)

        result = fill_aware_delay_selector_summary(
            journal,
            (
                _outcome(
                    old,
                    source="full_visible_book_ioc",
                    price="99",
                    quantity="1",
                ),
                _outcome(
                    current,
                    source="missing_delayed_book",
                    price=None,
                    quantity="0",
                ),
            ),
            (
                _outcome(
                    old,
                    source="full_visible_book_ioc",
                    price="98",
                    quantity="1",
                ),
                _outcome(
                    current,
                    source="full_visible_book_ioc",
                    price="98",
                    quantity="1",
                ),
            ),
            started_at_ms=900_000,
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 1
    assert result["causal_evaluable_trades"] == 0
    assert result["non_evaluable_base"] == 1
    assert result["missing_base_outcome"] == 0
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_fill_aware_delay_state_round_trip_freezes_rule() -> None:
    state = FillAwareDelaySelectorState(started_at_ms=123)
    restored = FillAwareDelaySelectorState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.candidate_id == FILL_AWARE_DELAY_SELECTOR_ID

    payload = state.payload()
    payload["rule"] = "always_120s"
    with pytest.raises(
        FillAwareDelaySelectorError,
        match="frozen candidate",
    ):
        FillAwareDelaySelectorState.from_payload(payload)
