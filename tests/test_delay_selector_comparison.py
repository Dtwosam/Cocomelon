from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delay_selector_comparison import (
    DELAY_SELECTOR_COMPARISON_ID,
    DelaySelectorComparisonError,
    DelaySelectorComparisonState,
    delay_selector_comparison_summary,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.entry_mid_markout_shadow import (
    EntryMidMarkoutOutcome,
)

RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    opened_at_ms: int,
    market: str,
) -> TradeJournalEntry:
    market_id = MarketId("", market)
    return TradeJournalEntry(
        market=market_id,
        direction=Direction.LONG,
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
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("2"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("2"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=300_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.2"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10002"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _delayed(
    trade: TradeJournalEntry,
    *,
    source: str,
    price: str | None,
    quantity: str,
) -> DelayedEntryOutcome:
    qty = Decimal(quantity)
    px = None if price is None else Decimal(price)
    improvement: Decimal | None = None
    gross_r: Decimal | None = None
    if px is not None:
        improvement = (
            (trade.entry_price - px)
            / trade.entry_price
            * Decimal("10000")
        )
        gross_r = (
            (trade.entry_price - px)
            * qty
            / trade.initial_risk_amount
        )
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=qty,
        delayed_average_fill_price=px,
        delayed_fee=Decimal("0"),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=improvement,
        gross_r_improvement=gross_r,
    )


def _mid(
    trade: TradeJournalEntry,
    *,
    gross_r: str,
) -> EntryMidMarkoutOutcome:
    value = Decimal(gross_r)
    return EntryMidMarkoutOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=trade.replay_run_id,
        horizon_ms=60_000,
        status="fresh",
        target_timestamp_ms=trade.opened_at_ms + 60_000,
        observed_timestamp_ms=trade.opened_at_ms + 60_500,
        observation_lag_ms=500,
        mid_px=Decimal("99") if value < 0 else Decimal("101"),
        signed_return_bps=Decimal("-100") if value < 0 else Decimal("100"),
        gross_r=value,
    )


def test_delay_selector_comparison_isolates_disagreements(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        adaptive_120 = _trade(
            suffix="a120",
            opened_at_ms=1_000_000,
            market="SOL",
        )
        fill_120 = _trade(
            suffix="f120",
            opened_at_ms=2_000_000,
            market="BTC",
        )
        agree_60 = _trade(
            suffix="g60",
            opened_at_ms=3_000_000,
            market="ETH",
        )
        agree_120 = _trade(
            suffix="g120",
            opened_at_ms=4_000_000,
            market="ARB",
        )
        trades = (
            adaptive_120,
            fill_120,
            agree_60,
            agree_120,
        )
        for trade in trades:
            journal.record_trade(trade)

        mids = (
            _mid(adaptive_120, gross_r="-0.1"),
            _mid(fill_120, gross_r="0.1"),
            _mid(agree_60, gross_r="0.1"),
            _mid(agree_120, gross_r="-0.1"),
        )
        base = (
            _delayed(
                adaptive_120,
                source="full_visible_book_ioc",
                price="99",
                quantity="1",
            ),
            _delayed(
                fill_120,
                source="partial_visible_book_ioc",
                price="100",
                quantity="0.5",
            ),
            _delayed(
                agree_60,
                source="full_visible_book_ioc",
                price="99",
                quantity="1",
            ),
            _delayed(
                agree_120,
                source="partial_visible_book_ioc",
                price="100",
                quantity="0.5",
            ),
        )
        challenger = tuple(
            _delayed(
                trade,
                source="full_visible_book_ioc",
                price="98",
                quantity="1",
            )
            for trade in trades
        )

        result = delay_selector_comparison_summary(
            journal,
            mids,
            base,
            challenger,
            started_at_ms=900_000,
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 4
    assert result["causal_evaluable_trades"] == 4
    assert result["disagreement_trades"] == 2

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["agreements"] == 2
    assert overall["disagreements"] == 2
    assert overall["both_60s"] == 1
    assert overall["both_120s"] == 1
    assert overall["markout_60s_fill_120s"] == 1
    assert overall["markout_120s_fill_60s"] == 1

    disagreements = result["disagreements"]
    assert isinstance(disagreements, dict)
    assert disagreements["fill_aware_better"] == 1
    assert disagreements["markout_better"] == 1

    types = result["by_disagreement_type"]
    assert isinstance(types, dict)
    assert types["markout_60s_fill_120s"]["fill_aware_better"] == 1
    assert types["markout_120s_fill_60s"]["markout_better"] == 1

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert readiness["missing_disagreement_trades"] == 8


def test_delay_selector_comparison_excludes_prestart_trade(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        old = _trade(
            suffix="old",
            opened_at_ms=500_000,
            market="SOL",
        )
        current = _trade(
            suffix="new",
            opened_at_ms=1_000_000,
            market="BTC",
        )
        journal.record_trade(old)
        journal.record_trade(current)
        result = delay_selector_comparison_summary(
            journal,
            (
                _mid(old, gross_r="-0.1"),
                _mid(current, gross_r="-0.1"),
            ),
            (
                _delayed(
                    old,
                    source="full_visible_book_ioc",
                    price="99",
                    quantity="1",
                ),
                _delayed(
                    current,
                    source="full_visible_book_ioc",
                    price="99",
                    quantity="1",
                ),
            ),
            (
                _delayed(
                    old,
                    source="full_visible_book_ioc",
                    price="98",
                    quantity="1",
                ),
                _delayed(
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
    assert result["causal_evaluable_trades"] == 1


def test_delay_selector_comparison_state_round_trip() -> None:
    state = DelaySelectorComparisonState(started_at_ms=123)
    restored = DelaySelectorComparisonState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.candidate_id == DELAY_SELECTOR_COMPARISON_ID

    payload = state.payload()
    payload["comparison"] = "changed"
    with pytest.raises(
        DelaySelectorComparisonError,
        match="frozen study",
    ):
        DelaySelectorComparisonState.from_payload(payload)
