from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_filter_economic_readiness import (
    ProspectiveFilterEconomicReadinessError,
    prospective_filter_economic_readiness,
)


def _trade(
    suffix: str,
    *,
    market: str,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
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
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + net,
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
        holding_duration_ms=1_000,
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


def test_filter_economics_requires_profitable_and_robust_candidate() -> None:
    result = prospective_filter_economic_readiness(
        (
            (_trade("sol-win", market="SOL", pnl="10"), False),
            (_trade("eth-win", market="ETH", pnl="8"), False),
            (_trade("sol-loss", market="SOL", pnl="-4"), True),
            (_trade("eth-loss", market="ETH", pnl="-3"), True),
        )
    )

    assert result["actual_net_pnl"] == "11"
    assert result["candidate_net_pnl"] == "18"
    assert result["delta_net_pnl"] == "7"
    assert result["actual_net_r"] == "1.1"
    assert result["candidate_net_r"] == "1.8"
    assert result["delta_net_r"] == "0.7"
    assert result["candidate_profitable"] is True
    assert result["improvement_positive"] is True
    assert result["candidate_single_trade_robust"] is True
    assert result["candidate_single_market_robust"] is True
    assert result["delta_single_trade_robust"] is True
    assert result["delta_single_market_robust"] is True
    assert result["economics_ready"] is True


def test_filter_economics_rejects_less_bad_but_losing_candidate() -> None:
    result = prospective_filter_economic_readiness(
        (
            (_trade("admitted-loss", market="SOL", pnl="-2"), False),
            (_trade("blocked-loss", market="ETH", pnl="-5"), True),
        )
    )

    assert result["candidate_net_pnl"] == "-2"
    assert result["delta_net_pnl"] == "5"
    assert result["candidate_profitable"] is False
    assert result["improvement_positive"] is True
    assert result["economics_ready"] is False


def test_filter_economics_rejects_single_market_concentration() -> None:
    result = prospective_filter_economic_readiness(
        (
            (_trade("win-a", market="SOL", pnl="10"), False),
            (_trade("win-b", market="SOL", pnl="8"), False),
            (_trade("loss-a", market="SOL", pnl="-4"), True),
            (_trade("loss-b", market="SOL", pnl="-3"), True),
        )
    )

    assert result["candidate_single_trade_robust"] is True
    assert result["delta_single_trade_robust"] is True
    assert result["candidate_single_market_robust"] is False
    assert result["delta_single_market_robust"] is False
    assert result["economics_ready"] is False


def test_filter_economics_rejects_duplicate_trade_ids() -> None:
    trade = _trade("duplicate", market="SOL", pnl="3")

    with pytest.raises(
        ProspectiveFilterEconomicReadinessError,
        match="duplicate trade ids",
    ):
        prospective_filter_economic_readiness(
            ((trade, False), (trade, True))
        )
