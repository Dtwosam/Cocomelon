from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.prospective_entry_filter import (
    ENTRY_FILTER_CANDIDATE_ID,
    ProspectiveEntryFilterError,
    ProspectiveEntryFilterState,
    evaluate_prospective_entry_filter,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    value = Decimal(pnl)
    entry = Decimal("100")
    quantity = Decimal("1")
    exit_price = (
        entry + value
        if direction is Direction.LONG
        else entry - value
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"open-plan-{suffix}",
        opening_attempt_id=f"open-attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-fill-{suffix}", f"exit-fill-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=exit_price,
        filled_quantity=quantity,
        gross_realized_pnl=value,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=value,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=value / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + value,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _fact(
    trade: TradeJournalEntry,
    *,
    lead_strategy: str,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=RUN_ID,
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=trade.opened_at_ms - 1_000,
        score=Decimal("75"),
        lead_strategy=lead_strategy,
        signal_ids=(f"signal-{trade.strategy_decision_id}",),
        reason_codes=("decision_threshold_met",),
        trend_regime=(
            TrendRegime.UP
            if trade.direction is Direction.LONG
            else TrendRegime.DOWN
        ),
        volatility_regime=VolatilityRegime.NORMAL,
    )


def test_filter_blocks_only_prospective_long_trend_contribution(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        old_long = _trade(
            suffix="old",
            direction=Direction.LONG,
            opened_at_ms=9_000,
            pnl="-20",
        )
        long_trend = _trade(
            suffix="blocked",
            direction=Direction.LONG,
            opened_at_ms=11_000,
            pnl="-8",
        )
        long_breakout = _trade(
            suffix="breakout",
            direction=Direction.LONG,
            opened_at_ms=12_000,
            pnl="4",
        )
        short_trend = _trade(
            suffix="short",
            direction=Direction.SHORT,
            opened_at_ms=13_000,
            pnl="6",
        )
        for trade in (
            old_long,
            long_trend,
            long_breakout,
            short_trend,
        ):
            journal.record_trade(trade)
        facts.record_decision_fact(_fact(old_long, lead_strategy="trend"))
        facts.record_decision_fact(
            _fact(long_trend, lead_strategy="trend")
        )
        facts.record_decision_fact(
            _fact(long_breakout, lead_strategy="breakout")
        )
        facts.record_decision_fact(
            _fact(short_trend, lead_strategy="trend")
        )

        result = evaluate_prospective_entry_filter(
            journal,
            facts,
            ProspectiveEntryFilterState(started_at_ms=10_000),
        )
    finally:
        facts.close()
        journal.close()

    assert result["prospective_closed_trades"] == 3
    assert result["attributed_trades"] == 3
    assert result["attribution_misses"] == 0
    assert result["blocked_trades"] == 1
    assert result["blocked_wins"] == 0
    assert result["blocked_losses"] == 1
    assert result["blocked_net_pnl"] == "-8"
    assert result["allowed_trades"] == 2
    assert result["allowed_net_pnl"] == "10"
    assert result["actual_net_pnl"] == "2"
    assert result["candidate_trade_contribution_pnl"] == "10"
    assert result["delta_trade_contribution_pnl"] == "8"
    robustness = result["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["total_delta_trade_contribution_pnl"] == "8"
    assert robustness["largest_abs_trade_contribution"] == "8"
    assert robustness["changes_readiness_gate"] is False
    residual = result["allowed_residual"]
    assert isinstance(residual, dict)
    residual_overall = residual["overall"]
    assert isinstance(residual_overall, dict)
    assert residual_overall["trades"] == 2
    assert residual_overall["net_pnl"] == "10"
    by_side = residual["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["net_pnl"] == "4"
    assert by_side["short"]["net_pnl"] == "6"
    by_strategy = residual["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["breakout"]["net_pnl"] == "4"
    assert by_strategy["trend"]["net_pnl"] == "6"
    assert residual["changes_readiness_gate"] is False
    portfolio = result["fixed_schedule_portfolio"]
    assert isinstance(portfolio, dict)
    assert portfolio["attributed_trades"] == 3
    assert portfolio["admitted_trades"] == 2
    assert portfolio["blocked_trades"] == 1
    actual_timeline = portfolio["actual"]
    candidate_timeline = portfolio["candidate"]
    assert isinstance(actual_timeline, dict)
    assert isinstance(candidate_timeline, dict)
    assert actual_timeline["final_realized_contribution"] == "2"
    assert candidate_timeline["final_realized_contribution"] == "10"
    assert portfolio["delta_final_realized_contribution"] == "8"
    assert portfolio["replacement_trades_modeled"] is False
    assert portfolio["candidate_equity_resizing_modeled"] is False
    assert portfolio["changes_readiness_gate"] is False
    assert result["portfolio_counterfactual"] is False
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_missing_fact_prevents_review_readiness(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        trade = _trade(
            suffix="missing",
            direction=Direction.LONG,
            opened_at_ms=11_000,
            pnl="-5",
        )
        journal.record_trade(trade)
        result = evaluate_prospective_entry_filter(
            journal,
            facts,
            ProspectiveEntryFilterState(started_at_ms=10_000),
        )
    finally:
        facts.close()
        journal.close()

    assert result["prospective_closed_trades"] == 1
    assert result["attributed_trades"] == 0
    assert result["attribution_misses"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_state_round_trip_preserves_frozen_candidate() -> None:
    state = ProspectiveEntryFilterState(started_at_ms=123)
    restored = ProspectiveEntryFilterState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.candidate_id == ENTRY_FILTER_CANDIDATE_ID

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["lead_strategy"] = "breakout"
    with pytest.raises(
        ProspectiveEntryFilterError,
        match="frozen candidate",
    ):
        ProspectiveEntryFilterState.from_payload(payload)
