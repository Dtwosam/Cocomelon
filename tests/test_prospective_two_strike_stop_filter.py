from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_two_strike_stop_filter import (
    CANDIDATE_ID,
    EMBARGO_MS,
    ProspectiveTwoStrikeStopFilterError,
    ProspectiveTwoStrikeStopFilterState,
    prospective_two_strike_stop_filter_summary,
)


def _trade(
    suffix: str,
    *,
    market: str = "SOL",
    direction: Direction = Direction.LONG,
    opened_at_ms: int,
    pnl: str,
    exit_reason: str = "MARK_STOP_TRIGGERED",
    hold_ms: int = 60_000,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    entry = Decimal("100")
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + hold_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-{suffix}", f"close-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=(
            entry + net
            if direction is Direction.LONG
            else entry - net
        ),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=hold_ms,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason=exit_reason,
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_two_strike_state_round_trip_locks_rule_and_embargo() -> None:
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=123
    )
    assert state.started_at_ms == 123 + EMBARGO_MS
    assert state.candidate_id == CANDIDATE_ID

    restored = ProspectiveTwoStrikeStopFilterState.from_payload(
        state.payload()
    )
    assert restored == state

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["strike_threshold"] = 3
    with pytest.raises(
        ProspectiveTwoStrikeStopFilterError,
        match="frozen candidate",
    ):
        ProspectiveTwoStrikeStopFilterState.from_payload(payload)


def test_two_strike_shadow_skips_once_then_resets() -> None:
    start = EMBARGO_MS + 1_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trades = (
        _trade(
            "loss-1",
            opened_at_ms=start,
            pnl="-5",
        ),
        _trade(
            "loss-2",
            opened_at_ms=start + 120_000,
            pnl="-6",
        ),
        _trade(
            "blocked-winner",
            opened_at_ms=start + 240_000,
            pnl="9",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "admitted-after-reset",
            opened_at_ms=start + 360_000,
            pnl="4",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
    )

    result = prospective_two_strike_stop_filter_summary(
        trades,
        state,
    )

    assert result["prospective_closed_trades"] == 4
    assert result["admitted_trades"] == 3
    assert result["blocked_trades"] == 1
    assert result["blocked_wins"] == 1
    assert result["blocked_losses"] == 0
    assert result["blocked_net_pnl"] == "9"
    assert result["actual_net_pnl"] == "2"
    assert result["candidate_net_pnl"] == "-7"
    assert result["delta_net_pnl"] == "-9"
    strikes = result["decision_prior_strikes"]
    assert isinstance(strikes, dict)
    blocked_trade = trades[2]
    reset_trade = trades[3]
    assert strikes[blocked_trade.trade_id] == 2
    assert strikes[reset_trade.trade_id] == 0


def test_two_strike_shadow_is_direction_and_market_separate() -> None:
    start = EMBARGO_MS + 2_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trades = (
        _trade("sol-long-1", opened_at_ms=start, pnl="-5"),
        _trade(
            "sol-short-1",
            direction=Direction.SHORT,
            opened_at_ms=start + 120_000,
            pnl="-5",
        ),
        _trade(
            "eth-long-1",
            market="ETH",
            opened_at_ms=start + 240_000,
            pnl="-5",
        ),
        _trade(
            "sol-long-2",
            opened_at_ms=start + 360_000,
            pnl="-5",
        ),
        _trade(
            "sol-short-2",
            direction=Direction.SHORT,
            opened_at_ms=start + 480_000,
            pnl="3",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "sol-long-blocked",
            opened_at_ms=start + 600_000,
            pnl="-8",
        ),
        _trade(
            "eth-long-2",
            market="ETH",
            opened_at_ms=start + 720_000,
            pnl="-5",
        ),
        _trade(
            "eth-long-blocked",
            market="ETH",
            opened_at_ms=start + 840_000,
            pnl="-7",
        ),
    )

    result = prospective_two_strike_stop_filter_summary(
        trades,
        state,
    )

    assert result["blocked_trades"] == 2
    assert result["blocked_losses"] == 2
    assert result["blocked_net_pnl"] == "-15"
    assert result["delta_net_pnl"] == "15"
    by_direction = result["by_direction"]
    assert isinstance(by_direction, dict)
    assert by_direction["long"]["blocked_trades"] == 2
    assert by_direction["short"]["blocked_trades"] == 0
    blocked_by_market = result["blocked_by_market"]
    assert isinstance(blocked_by_market, dict)
    assert blocked_by_market["SOL"]["net_pnl"] == "-8"
    assert blocked_by_market["ETH"]["net_pnl"] == "-7"
    robustness = result["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["leave_one_trade_out_min_delta"] == "7"
    assert (
        robustness["positive_after_any_single_trade_removed"]
        is True
    )
    assert robustness["leave_one_market_out_min_delta"] == "7"
    assert (
        robustness["positive_after_any_single_market_removed"]
        is True
    )


def test_two_strike_shadow_uses_only_closes_known_before_opening() -> None:
    start = EMBARGO_MS + 3_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trades = (
        _trade(
            "overlap-loss-1",
            opened_at_ms=start,
            pnl="-5",
            hold_ms=300_000,
        ),
        _trade(
            "overlap-loss-2",
            opened_at_ms=start + 120_000,
            pnl="-6",
            hold_ms=300_000,
        ),
        _trade(
            "overlap-third-open",
            opened_at_ms=start + 240_000,
            pnl="4",
            exit_reason="OPPOSITE_FRESH_THESIS",
            hold_ms=600_000,
        ),
        _trade(
            "after-two-known-closes",
            opened_at_ms=start + 480_000,
            pnl="-9",
        ),
    )

    result = prospective_two_strike_stop_filter_summary(
        trades,
        state,
    )

    strikes = result["decision_prior_strikes"]
    assert isinstance(strikes, dict)
    assert strikes[trades[0].trade_id] == 0
    assert strikes[trades[1].trade_id] == 0
    assert strikes[trades[2].trade_id] == 0
    assert strikes[trades[3].trade_id] == 2
    assert result["blocked_trades"] == 1
    assert result["blocked_losses"] == 1
    assert result["blocked_net_pnl"] == "-9"


def test_two_strike_shadow_ignores_pre_embargo_history() -> None:
    frozen = 3_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=frozen
    )
    start = frozen + EMBARGO_MS
    trades = (
        _trade(
            "touched-loss-1",
            opened_at_ms=frozen,
            pnl="-5",
        ),
        _trade(
            "touched-loss-2",
            opened_at_ms=frozen + 120_000,
            pnl="-5",
        ),
        _trade(
            "clean-first",
            opened_at_ms=start,
            pnl="-5",
        ),
        _trade(
            "clean-second",
            opened_at_ms=start + 120_000,
            pnl="-5",
        ),
        _trade(
            "clean-blocked",
            opened_at_ms=start + 240_000,
            pnl="-7",
        ),
    )

    result = prospective_two_strike_stop_filter_summary(
        trades,
        state,
    )

    assert result["prospective_closed_trades"] == 3
    assert result["blocked_trades"] == 1
    strikes = result["decision_prior_strikes"]
    assert isinstance(strikes, dict)
    assert strikes[trades[2].trade_id] == 0
    assert strikes[trades[4].trade_id] == 2


def test_two_strike_state_rejects_embargo_tamper() -> None:
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=100
    )
    payload = state.payload()
    payload["started_at_ms"] = state.started_at_ms + 1

    with pytest.raises(
        ProspectiveTwoStrikeStopFilterError,
        match="frozen embargo",
    ):
        ProspectiveTwoStrikeStopFilterState.from_payload(payload)
