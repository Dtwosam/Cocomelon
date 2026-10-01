from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_global_loss_gate import (
    CANDIDATE_ID,
    EMBARGO_MS,
    ProspectiveGlobalLossGateError,
    ProspectiveGlobalLossGateState,
    prospective_global_loss_gate_summary,
)


def _trade(
    suffix: str,
    *,
    opened_at_ms: int,
    pnl: str,
    market: str = "SOL",
    direction: Direction = Direction.LONG,
    hold_ms: int = 50,
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
        exit_reason=(
            "MARK_STOP_TRIGGERED"
            if net < 0
            else "OPPOSITE_FRESH_THESIS"
        ),
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_global_loss_gate_state_round_trip_locks_rule() -> None:
    state = ProspectiveGlobalLossGateState(frozen_at_ms=123)
    assert state.candidate_id == CANDIDATE_ID
    assert state.started_at_ms == 123 + EMBARGO_MS

    restored = ProspectiveGlobalLossGateState.from_payload(
        state.payload()
    )
    assert restored == state

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["loss_threshold"] = 3
    with pytest.raises(
        ProspectiveGlobalLossGateError,
        match="frozen candidate",
    ):
        ProspectiveGlobalLossGateState.from_payload(payload)


def test_global_loss_gate_counts_losses_across_market_and_side() -> None:
    start = EMBARGO_MS + 1_000
    state = ProspectiveGlobalLossGateState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trades = (
        _trade(
            "loss-sol-long",
            opened_at_ms=start,
            pnl="-2",
            market="SOL",
            direction=Direction.LONG,
        ),
        _trade(
            "loss-eth-short",
            opened_at_ms=start + 100,
            pnl="-3",
            market="ETH",
            direction=Direction.SHORT,
        ),
        _trade(
            "blocked-winner",
            opened_at_ms=start + 200,
            pnl="8",
            market="BTC",
            direction=Direction.LONG,
        ),
        _trade(
            "after-reset",
            opened_at_ms=start + 300,
            pnl="4",
            market="XRP",
            direction=Direction.SHORT,
        ),
    )

    result = prospective_global_loss_gate_summary(trades, state)

    assert result["prospective_closed_trades"] == 4
    assert result["admitted_trades"] == 3
    assert result["blocked_trades"] == 1
    assert result["blocked_wins"] == 1
    assert result["blocked_losses"] == 0
    assert result["delta_net_pnl"] == "-8"
    prior = result["decision_prior_losses"]
    assert isinstance(prior, dict)
    assert prior[trades[2].trade_id] == 2
    assert prior[trades[3].trade_id] == 0


def test_global_loss_gate_blocked_outcome_does_not_update_state() -> None:
    start = EMBARGO_MS + 2_000
    state = ProspectiveGlobalLossGateState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trades = (
        _trade("loss-1", opened_at_ms=start, pnl="-2"),
        _trade("loss-2", opened_at_ms=start + 100, pnl="-3"),
        _trade(
            "blocked-loss",
            opened_at_ms=start + 200,
            pnl="-20",
        ),
        _trade(
            "next-admitted",
            opened_at_ms=start + 300,
            pnl="5",
        ),
    )

    result = prospective_global_loss_gate_summary(trades, state)

    prior = result["decision_prior_losses"]
    assert isinstance(prior, dict)
    assert prior[trades[2].trade_id] == 2
    assert prior[trades[3].trade_id] == 0
    assert result["blocked_losses"] == 1
    assert result["delta_net_pnl"] == "20"


def test_global_loss_gate_uses_only_closes_known_before_opening() -> None:
    start = EMBARGO_MS + 3_000
    state = ProspectiveGlobalLossGateState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trades = (
        _trade(
            "slow-loss-1",
            opened_at_ms=start,
            pnl="-2",
            hold_ms=500,
        ),
        _trade(
            "slow-loss-2",
            opened_at_ms=start + 100,
            pnl="-3",
            hold_ms=500,
        ),
        _trade(
            "opens-before-losses-close",
            opened_at_ms=start + 200,
            pnl="4",
            hold_ms=50,
        ),
        _trade(
            "after-losses-close",
            opened_at_ms=start + 700,
            pnl="-5",
            hold_ms=50,
        ),
    )

    result = prospective_global_loss_gate_summary(trades, state)

    prior = result["decision_prior_losses"]
    assert isinstance(prior, dict)
    assert prior[trades[2].trade_id] == 0
    assert result["blocked_trades"] == 0


def test_global_loss_gate_ignores_pre_embargo_history() -> None:
    frozen = 10_000
    state = ProspectiveGlobalLossGateState(frozen_at_ms=frozen)
    start = state.started_at_ms
    trades = (
        _trade(
            "touched-loss-1",
            opened_at_ms=frozen,
            pnl="-5",
        ),
        _trade(
            "touched-loss-2",
            opened_at_ms=frozen + 100,
            pnl="-5",
        ),
        _trade(
            "clean-first",
            opened_at_ms=start,
            pnl="3",
        ),
    )

    result = prospective_global_loss_gate_summary(trades, state)

    assert result["prospective_closed_trades"] == 1
    assert result["blocked_trades"] == 0
    prior = result["decision_prior_losses"]
    assert isinstance(prior, dict)
    assert prior[trades[2].trade_id] == 0


def test_global_loss_gate_review_requires_profitable_robust_candidate() -> None:
    start = EMBARGO_MS + 20_000
    state = ProspectiveGlobalLossGateState(
        frozen_at_ms=start - EMBARGO_MS
    )
    trades: list[TradeJournalEntry] = []
    opened = start
    markets = ("SOL", "ETH", "BTC", "XRP", "ENA")
    index = 0

    for cycle, market in enumerate(markets):
        for pnl in ("-1", "-1", "-5", "4"):
            direction = (
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            )
            trades.append(
                _trade(
                    f"cycle-{cycle}-{index}",
                    opened_at_ms=opened,
                    pnl=pnl,
                    market=market,
                    direction=direction,
                )
            )
            opened += 100
            index += 1

    for extra in range(10):
        direction = (
            Direction.LONG
            if index % 2 == 0
            else Direction.SHORT
        )
        trades.append(
            _trade(
                f"extra-{extra}",
                opened_at_ms=opened,
                pnl="4",
                market=markets[extra % len(markets)],
                direction=direction,
            )
        )
        opened += 100
        index += 1

    result = prospective_global_loss_gate_summary(
        tuple(trades),
        state,
    )

    assert result["prospective_closed_trades"] == 30
    assert result["blocked_trades"] == 5
    assert result["blocked_wins"] == 0
    assert result["blocked_losses"] == 5
    assert result["delta_net_pnl"] == "25"
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["sample_complete"] is True
    assert readiness["candidate_profitable"] is True
    assert readiness["improvement_positive"] is True
    assert readiness["candidate_single_trade_robust"] is True
    assert readiness["candidate_single_market_robust"] is True
    assert readiness["delta_single_trade_robust"] is True
    assert readiness["delta_single_market_robust"] is True
    assert readiness["ready_for_review"] is True
    assert result["changes_risk_limits"] is False
