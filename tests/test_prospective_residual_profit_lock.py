from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import ExcursionMetric, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.profit_lock_counterfactual import (
    ProfitLockTradeOutcome,
)
from cocomelon.research.prospective_allowed_residual import (
    AllowedResidualItem,
)
from cocomelon.research.prospective_residual_profit_lock import (
    ProspectiveResidualProfitLockError,
    prospective_residual_profit_lock_summary,
)


def _trade(
    suffix: str,
    *,
    pnl: str,
    mfe_r: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId("", "SOL"),
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=10_000,
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
        exit_price=Decimal("90"),
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
        holding_duration_ms=9_000,
        mfe=ExcursionMetric(
            kind="mfe",
            price=Decimal("105"),
            per_unit=Decimal("5"),
            fraction=Decimal("0.05"),
            currency=Decimal(mfe_r) * Decimal("10"),
            r_multiple=Decimal(mfe_r),
            timestamp_ms=2_000,
            source_event_key=f"mfe-{suffix}",
            complete=True,
        ),
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    rule_id: str,
    candidate_pnl: str,
    activated: bool,
    triggered: bool,
) -> ProfitLockTradeOutcome:
    candidate = Decimal(candidate_pnl)
    return ProfitLockTradeOutcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id=rule_id,
        activated=activated,
        activation_timestamp_ms=2_000 if activated else None,
        triggered=triggered,
        trigger_timestamp_ms=3_000 if triggered else None,
        trigger_mark_px=Decimal("100") if triggered else None,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=candidate,
        candidate_net_r_estimate=(
            candidate / trade.initial_risk_amount
        ),
        delta_net_pnl_estimate=candidate - trade.net_pnl,
        delta_net_r_estimate=(
            candidate / trade.initial_risk_amount - trade.net_r
        ),
        used_actual_close=not triggered,
    )


def test_residual_profit_lock_isolates_exact_path_saves() -> None:
    never_worked = _trade("never", pnl="-8", mfe_r="0.1")
    giveback = _trade("giveback", pnl="-6", mfe_r="0.8")
    deep = _trade("deep", pnl="-4", mfe_r="1.2")
    winner = _trade("winner", pnl="5", mfe_r="1.1")

    items = tuple(
        AllowedResidualItem(trade)
        for trade in (never_worked, giveback, deep, winner)
    )
    outcomes = (
        _outcome(
            never_worked,
            rule_id="breakeven_after_0_5r",
            candidate_pnl="-8",
            activated=False,
            triggered=False,
        ),
        _outcome(
            giveback,
            rule_id="breakeven_after_0_5r",
            candidate_pnl="-1",
            activated=True,
            triggered=True,
        ),
        _outcome(
            deep,
            rule_id="breakeven_after_0_5r",
            candidate_pnl="0.5",
            activated=True,
            triggered=True,
        ),
        _outcome(
            never_worked,
            rule_id="lock_0_5r_after_1r",
            candidate_pnl="-8",
            activated=False,
            triggered=False,
        ),
        _outcome(
            giveback,
            rule_id="lock_0_5r_after_1r",
            candidate_pnl="-6",
            activated=False,
            triggered=False,
        ),
        _outcome(
            deep,
            rule_id="lock_0_5r_after_1r",
            candidate_pnl="3",
            activated=True,
            triggered=True,
        ),
    )

    result = prospective_residual_profit_lock_summary(items, outcomes)

    assert result["allowed_trades"] == 4
    assert result["residual_loss_trades"] == 3
    assert result["giveback_residual_losses"] == 2
    assert result["deep_giveback_residual_losses"] == 1

    by_rule = result["by_rule"]
    assert isinstance(by_rule, dict)
    breakeven = by_rule["breakeven_after_0_5r"]
    assert breakeven["matched_exact_path_losses"] == 3
    assert breakeven["triggered_losses"] == 2
    assert breakeven["rescued_to_nonnegative"] == 1
    assert breakeven["actual_net_pnl"] == "-18"
    assert breakeven["candidate_net_pnl_estimate"] == "-8.5"
    assert breakeven["delta_net_pnl_estimate"] == "9.5"
    assert breakeven["giveback_triggered_losses"] == 2
    assert breakeven["giveback_delta_net_pnl_estimate"] == "9.5"
    assert breakeven["deep_giveback_delta_net_pnl_estimate"] == "4.5"
    pnl_robustness = breakeven["pnl_robustness"]
    assert isinstance(pnl_robustness, dict)
    assert pnl_robustness["leave_one_loss_out_min_delta"] == "4.5"
    assert pnl_robustness["positive_after_removing_any_one_loss"] is True

    lock = by_rule["lock_0_5r_after_1r"]
    assert lock["triggered_losses"] == 1
    assert lock["rescued_to_nonnegative"] == 1
    assert lock["delta_net_pnl_estimate"] == "7"
    lock_robustness = lock["pnl_robustness"]
    assert isinstance(lock_robustness, dict)
    assert lock_robustness["leave_one_loss_out_min_delta"] == "0"
    assert lock_robustness["positive_after_removing_any_one_loss"] is False
    assert result["changes_readiness_gate"] is False


def test_residual_profit_lock_reports_missing_exact_paths() -> None:
    first = _trade("first", pnl="-8", mfe_r="0.8")
    second = _trade("second", pnl="-4", mfe_r="1.2")
    result = prospective_residual_profit_lock_summary(
        (AllowedResidualItem(first), AllowedResidualItem(second)),
        (
            _outcome(
                first,
                rule_id="breakeven_after_0_5r",
                candidate_pnl="-1",
                activated=True,
                triggered=True,
            ),
        ),
    )

    by_rule = result["by_rule"]
    assert isinstance(by_rule, dict)
    breakeven = by_rule["breakeven_after_0_5r"]
    assert breakeven["matched_exact_path_losses"] == 1
    assert breakeven["missing_exact_path_losses"] == 1
    assert breakeven["exact_path_coverage_complete"] is False
    lock = by_rule["lock_0_5r_after_1r"]
    assert lock["matched_exact_path_losses"] == 0
    assert lock["missing_exact_path_losses"] == 2


def test_residual_profit_lock_rejects_mismatched_outcome() -> None:
    trade = _trade("mismatch", pnl="-8", mfe_r="0.8")
    bad = _outcome(
        trade,
        rule_id="breakeven_after_0_5r",
        candidate_pnl="-1",
        activated=True,
        triggered=True,
    )
    bad = ProfitLockTradeOutcome(
        trade_id=bad.trade_id,
        market="ETH",
        direction=bad.direction,
        rule_id=bad.rule_id,
        activated=bad.activated,
        activation_timestamp_ms=bad.activation_timestamp_ms,
        triggered=bad.triggered,
        trigger_timestamp_ms=bad.trigger_timestamp_ms,
        trigger_mark_px=bad.trigger_mark_px,
        actual_net_pnl=bad.actual_net_pnl,
        actual_net_r=bad.actual_net_r,
        candidate_net_pnl_estimate=bad.candidate_net_pnl_estimate,
        candidate_net_r_estimate=bad.candidate_net_r_estimate,
        delta_net_pnl_estimate=bad.delta_net_pnl_estimate,
        delta_net_r_estimate=bad.delta_net_r_estimate,
        used_actual_close=bad.used_actual_close,
    )

    with pytest.raises(
        ProspectiveResidualProfitLockError,
        match="does not match residual trade",
    ):
        prospective_residual_profit_lock_summary(
            (AllowedResidualItem(trade),),
            (bad,),
        )
