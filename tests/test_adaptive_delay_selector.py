from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.adaptive_delay_selector import (
    ADAPTIVE_DELAY_SELECTOR_ID,
    AdaptiveDelaySelectorError,
    AdaptiveDelaySelectorState,
    adaptive_delay_selector_summary,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.entry_mid_markout_shadow import (
    EntryMidMarkoutOutcome,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    exit_price: str,
    market: MarketId = MARKET,
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


def _delayed(
    trade: TradeJournalEntry,
    *,
    price: str,
    lag_ms: int = 1_000,
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
        observation_lag_ms=lag_ms,
        signed_price_improvement_bps=(
            signed / trade.entry_price * Decimal("10000")
        ),
        gross_r_improvement=(
            signed
            * trade.filled_quantity
            / trade.initial_risk_amount
        ),
    )


def _mid(
    trade: TradeJournalEntry,
    *,
    gross_r: str,
    observed_lag_ms: int = 500,
) -> EntryMidMarkoutOutcome:
    value = Decimal(gross_r)
    signed_move = (
        value
        * trade.initial_risk_amount
        / trade.filled_quantity
    )
    mid_px = (
        trade.entry_price + signed_move
        if trade.direction is Direction.LONG
        else trade.entry_price - signed_move
    )
    target = trade.opened_at_ms + 60_000
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
        target_timestamp_ms=target,
        observed_timestamp_ms=target + observed_lag_ms,
        observation_lag_ms=observed_lag_ms,
        mid_px=mid_px,
        signed_return_bps=(
            signed_move / trade.entry_price * Decimal("10000")
        ),
        gross_r=value,
    )


def test_adaptive_selector_uses_120s_for_adverse_and_60s_otherwise(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        adverse = _trade(
            suffix="adverse",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            exit_price="95",
        )
        favorable = _trade(
            suffix="favorable",
            direction=Direction.SHORT,
            opened_at_ms=2_000_000,
            exit_price="95",
            market=MarketId("", "BTC"),
        )
        for trade in (adverse, favorable):
            journal.record_trade(trade)

        result = adaptive_delay_selector_summary(
            journal,
            (
                _mid(adverse, gross_r="-0.1"),
                _mid(favorable, gross_r="0.1"),
            ),
            (
                _delayed(
                    adverse,
                    price="99",
                ),
                _delayed(
                    favorable,
                    price="101",
                ),
            ),
            (
                _delayed(
                    adverse,
                    price="98",
                ),
                _delayed(
                    favorable,
                    price="100.5",
                ),
            ),
            started_at_ms=900_000,
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 2
    assert result["causal_evaluable_trades"] == 2
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["selected_60s"] == 1
    assert overall["selected_120s"] == 1
    assert overall["actual_net_pnl"] == "0"
    assert overall["always_60s_net_pnl"] == "2"
    assert overall["always_120s_net_pnl"] == "2.5"
    assert overall["adaptive_net_pnl"] == "3"
    assert overall["adaptive_minus_60s_pnl"] == "1"
    assert overall["adaptive_minus_120s_pnl"] == "0.5"
    assert overall["adaptive_minus_actual_pnl"] == "3"

    by_signal = result["by_signal"]
    assert isinstance(by_signal, dict)
    adverse_group = by_signal["adverse_available_choose_120s"]
    non_adverse = by_signal["otherwise_choose_60s"]
    assert adverse_group["trades"] == 1
    assert adverse_group["selected_120s"] == 1
    assert non_adverse["trades"] == 1
    assert non_adverse["selected_60s"] == 1

    robustness = result["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["descriptive_only"] is True
    assert robustness["changes_readiness_gate"] is False

    vs_60 = robustness["adaptive_minus_60s"]
    assert isinstance(vs_60, dict)
    assert vs_60["trades"] == 2
    assert vs_60["markets"] == 2
    assert vs_60["total_delta_pnl"] == "1"
    assert vs_60["largest_abs_trade_contribution"] == "1"
    assert vs_60["largest_abs_trade_share"] == "1"
    assert vs_60["leave_one_trade_out_min_delta"] == "0"
    assert (
        vs_60["positive_after_any_single_trade_removed"]
        is False
    )
    assert vs_60["largest_abs_market"] == "SOL"
    assert vs_60["largest_abs_market_contribution"] == "1"
    assert vs_60["largest_abs_market_share"] == "1"
    assert vs_60["leave_one_market_out_min_delta"] == "0"
    assert (
        vs_60["positive_after_any_single_market_removed"]
        is False
    )

    vs_120 = robustness["adaptive_minus_120s"]
    assert isinstance(vs_120, dict)
    assert vs_120["total_delta_pnl"] == "0.5"
    assert vs_120["largest_abs_trade_contribution"] == "0.5"
    assert vs_120["leave_one_trade_out_min_delta"] == "0.0"

    by_market = result["by_market"]
    assert isinstance(by_market, dict)
    assert set(by_market) == {"BTC", "SOL"}
    assert by_market["SOL"]["adaptive_minus_60s_pnl"] == "1"
    assert by_market["BTC"]["adaptive_minus_120s_pnl"] == "0.5"

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_late_mid_signal_falls_back_to_60s_without_lookahead(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="late",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            exit_price="95",
        )
        journal.record_trade(trade)

        result = adaptive_delay_selector_summary(
            journal,
            (
                _mid(
                    trade,
                    gross_r="-0.1",
                    observed_lag_ms=2_000,
                ),
            ),
            (
                _delayed(
                    trade,
                    price="99",
                    lag_ms=1_000,
                ),
            ),
            (
                _delayed(
                    trade,
                    price="98",
                ),
            ),
            started_at_ms=900_000,
        )
    finally:
        journal.close()

    assert result["causal_evaluable_trades"] == 1
    assert result["late_mid_signal"] == 1
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 1
    assert overall["selected_60s"] == 1
    assert overall["selected_120s"] == 0
    assert overall["adaptive_net_pnl"] == "-4"
    assert overall["always_60s_net_pnl"] == "-4"


def test_adaptive_delay_state_round_trip_freezes_rule() -> None:
    state = AdaptiveDelaySelectorState(started_at_ms=123)
    restored = AdaptiveDelaySelectorState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.candidate_id == ADAPTIVE_DELAY_SELECTOR_ID

    payload = state.payload()
    payload["rule"] = "always_120s"
    with pytest.raises(
        AdaptiveDelaySelectorError,
        match="frozen candidate",
    ):
        AdaptiveDelaySelectorState.from_payload(payload)
