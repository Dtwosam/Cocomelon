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
from cocomelon.research.entry_decision_age import (
    EntryDecisionAgeError,
    entry_decision_age_summary,
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
    net = Decimal(pnl)
    entry = Decimal("100")
    exit_price = (
        entry + net
        if direction is Direction.LONG
        else entry - net
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
        fill_ids=(
            f"open-fill-{suffix}",
            f"exit-fill-{suffix}",
        ),
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
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _fact(
    trade: TradeJournalEntry,
    *,
    age_ms: int,
    lead_strategy: str,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=RUN_ID,
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=trade.opened_at_ms - age_ms,
        score=Decimal("80"),
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


def test_entry_decision_age_groups_outcomes_by_fixed_latency_band(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        rows = (
            (
                _trade(
                    suffix="fast",
                    direction=Direction.LONG,
                    opened_at_ms=100_000,
                    pnl="5",
                ),
                500,
                "breakout",
            ),
            (
                _trade(
                    suffix="mid",
                    direction=Direction.SHORT,
                    opened_at_ms=200_000,
                    pnl="-2",
                ),
                7_000,
                "trend",
            ),
            (
                _trade(
                    suffix="slow",
                    direction=Direction.LONG,
                    opened_at_ms=300_000,
                    pnl="-4",
                ),
                35_000,
                "trend",
            ),
            (
                _trade(
                    suffix="very-slow",
                    direction=Direction.SHORT,
                    opened_at_ms=400_000,
                    pnl="3",
                ),
                65_000,
                "breakout",
            ),
        )
        for trade, age_ms, strategy in rows:
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(
                    trade,
                    age_ms=age_ms,
                    lead_strategy=strategy,
                )
            )

        result = entry_decision_age_summary(journal, facts)
    finally:
        facts.close()
        journal.close()

    assert result["attributed_closed_trades"] == 4
    assert result["attribution_misses"] == 0
    assert result["ready_for_review"] is False
    assert result["still_needed_for_review"] == 26
    assert result["older_than_5s"] == 3
    assert result["older_than_15s"] == 2
    assert result["older_than_30s"] == 2
    assert result["older_than_60s"] == 1

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 4
    assert overall["wins"] == 2
    assert overall["losses"] == 2
    assert overall["net_pnl"] == "2"
    assert overall["mean_net_r"] == "0.05"
    assert overall["mean_decision_age_ms"] == 26875
    assert overall["median_decision_age_ms"] == 35000
    assert overall["p90_decision_age_ms"] == 65000
    assert overall["max_decision_age_ms"] == 65000

    bands = result["by_age_band"]
    assert isinstance(bands, dict)
    assert bands["<1s"]["trades"] == 1
    assert bands["<1s"]["net_pnl"] == "5"
    assert bands["5-<15s"]["trades"] == 1
    assert bands["5-<15s"]["net_pnl"] == "-2"
    assert bands["30-<60s"]["trades"] == 1
    assert bands["30-<60s"]["net_pnl"] == "-4"
    assert bands["60s+"]["trades"] == 1
    assert bands["60s+"]["net_pnl"] == "3"

    by_side = result["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["net_pnl"] == "1"
    assert by_side["short"]["net_pnl"] == "1"

    by_strategy = result["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["breakout"]["net_pnl"] == "8"
    assert by_strategy["trend"]["net_pnl"] == "-6"


def test_entry_decision_age_counts_missing_fact_as_attribution_miss(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        journal.record_trade(
            _trade(
                suffix="missing",
                direction=Direction.LONG,
                opened_at_ms=100_000,
                pnl="-1",
            )
        )
        result = entry_decision_age_summary(journal, facts)
    finally:
        facts.close()
        journal.close()

    assert result["attributed_closed_trades"] == 0
    assert result["attribution_misses"] == 1
    assert result["ready_for_review"] is False


def test_entry_decision_age_rejects_fill_before_decision(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        trade = _trade(
            suffix="regression",
            direction=Direction.LONG,
            opened_at_ms=100_000,
            pnl="-1",
        )
        journal.record_trade(trade)
        facts.record_decision_fact(
            DecisionEvaluationFact(
                strategy_decision_id=trade.strategy_decision_id,
                feature_snapshot_id=trade.feature_snapshot_id,
                replay_run_id=RUN_ID,
                market=trade.market,
                direction=trade.direction,
                timestamp_ms=100_001,
                score=Decimal("80"),
                lead_strategy="trend",
                signal_ids=("signal-regression",),
                reason_codes=("decision_threshold_met",),
                trend_regime=TrendRegime.UP,
                volatility_regime=VolatilityRegime.NORMAL,
            )
        )

        with pytest.raises(
            EntryDecisionAgeError,
            match="precedes strategy decision",
        ):
            entry_decision_age_summary(journal, facts)
    finally:
        facts.close()
        journal.close()
