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
from cocomelon.research.closed_trade_friction import (
    ClosedTradeFrictionError,
    closed_trade_friction_summary,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    gross: str,
    entry_slippage: str,
    exit_slippage: str,
    entry_fee: str,
    exit_fee: str,
    funding: str,
    net: str,
) -> TradeJournalEntry:
    net_value = Decimal(net)
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
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
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal(gross),
        entry_fees=Decimal(entry_fee),
        exit_fees=Decimal(exit_fee),
        funding_cash_pnl=Decimal(funding),
        net_pnl=net_value,
        entry_slippage_amount=Decimal(entry_slippage),
        exit_slippage_amount=Decimal(exit_slippage),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=net_value / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net_value,
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
        timestamp_ms=trade.opened_at_ms - 1,
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


def test_closed_trade_friction_reconciles_waterfall_and_flips(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        winner = _trade(
            suffix="winner",
            direction=Direction.LONG,
            gross="5",
            entry_slippage="1",
            exit_slippage="1",
            entry_fee="1.5",
            exit_fee="1.5",
            funding="0",
            net="2",
        )
        flipped = _trade(
            suffix="flipped",
            direction=Direction.LONG,
            gross="1",
            entry_slippage="0.5",
            exit_slippage="0.5",
            entry_fee="1",
            exit_fee="1",
            funding="0",
            net="-1",
        )
        rescued = _trade(
            suffix="rescued",
            direction=Direction.SHORT,
            gross="-1",
            entry_slippage="-1",
            exit_slippage="-1",
            entry_fee="0.25",
            exit_fee="0.25",
            funding="2",
            net="0.5",
        )
        for trade, strategy in (
            (winner, "trend"),
            (flipped, "trend"),
            (rescued, "breakout"),
        ):
            facts.record_decision_fact(
                _fact(trade, lead_strategy=strategy)
            )

        result = closed_trade_friction_summary(
            (winner, flipped, rescued),
            facts,
        )
    finally:
        facts.close()

    assert result["decision_fact_attribution_misses"] == 0
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 3
    assert Decimal(str(overall["reference_gross_pnl"])) == Decimal("6")
    assert Decimal(str(overall["signed_slippage_amount"])) == Decimal("1")
    assert Decimal(str(overall["adverse_slippage_amount"])) == Decimal("3")
    assert Decimal(str(overall["favorable_slippage_amount"])) == Decimal("2")
    assert Decimal(str(overall["actual_gross_realized_pnl"])) == Decimal("5")
    assert Decimal(str(overall["fees"])) == Decimal("5.5")
    assert Decimal(str(overall["funding_cash_pnl"])) == Decimal("2")
    assert Decimal(str(overall["net_pnl"])) == Decimal("1.5")
    assert Decimal(str(overall["net_cost_drag"])) == Decimal("4.5")
    assert overall["reference_gross_positive_trades"] == 2
    assert overall["actual_gross_positive_trades"] == 2
    assert overall["net_positive_trades"] == 2
    assert overall["friction_flipped_trades"] == 1
    assert overall["fee_funding_flipped_trades"] == 1
    assert overall["friction_rescued_trades"] == 1

    mean_reference = Decimal(str(overall["mean_reference_gross_r"]))
    mean_drag = Decimal(str(overall["mean_net_cost_drag_r"]))
    mean_net = Decimal(str(overall["mean_net_r"]))
    assert mean_reference - mean_drag == mean_net

    by_side = result["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["trades"] == 2
    assert Decimal(str(by_side["long"]["net_pnl"])) == Decimal("1")
    assert by_side["short"]["friction_rescued_trades"] == 1

    by_strategy = result["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["trend"]["trades"] == 2
    assert by_strategy["breakout"]["trades"] == 1


def test_missing_decision_fact_is_visible_not_guessed(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        trade = _trade(
            suffix="missing",
            direction=Direction.LONG,
            gross="1",
            entry_slippage="0",
            exit_slippage="0",
            entry_fee="0",
            exit_fee="0",
            funding="0",
            net="1",
        )
        result = closed_trade_friction_summary((trade,), facts)
    finally:
        facts.close()

    assert result["decision_fact_attribution_misses"] == 1
    by_strategy = result["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["unknown"]["trades"] == 1


def test_friction_fails_closed_on_decision_lineage_mismatch(
    tmp_path: Path,
) -> None:
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        trade = _trade(
            suffix="mismatch",
            direction=Direction.LONG,
            gross="1",
            entry_slippage="0",
            exit_slippage="0",
            entry_fee="0",
            exit_fee="0",
            funding="0",
            net="1",
        )
        bad_fact = DecisionEvaluationFact(
            strategy_decision_id=trade.strategy_decision_id,
            feature_snapshot_id="wrong-feature",
            replay_run_id=RUN_ID,
            market=trade.market,
            direction=trade.direction,
            timestamp_ms=trade.opened_at_ms - 1,
            score=Decimal("75"),
            lead_strategy="trend",
            signal_ids=("signal-bad",),
            reason_codes=("decision_threshold_met",),
            trend_regime=TrendRegime.UP,
            volatility_regime=VolatilityRegime.NORMAL,
        )
        facts.record_decision_fact(bad_fact)

        with pytest.raises(
            ClosedTradeFrictionError,
            match="feature lineage",
        ):
            closed_trade_friction_summary((trade,), facts)
    finally:
        facts.close()
