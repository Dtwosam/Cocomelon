from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.research.closed_trade_concentration import (
    closed_trade_concentration_summary,
)

DAY_MS = 86_400_000
RUN_ID = "continuous-paper-mainnet-v1"
SOL = MarketId("", "SOL")
ETH = MarketId("", "ETH")
BTC = MarketId("", "BTC")


def _trade(
    *,
    suffix: str,
    market: MarketId,
    day: int,
    pnl: str,
    equity_before: str,
) -> TradeJournalEntry:
    value = Decimal(pnl)
    entry = Decimal("100")
    opened_at_ms = day * DAY_MS + 1_000
    closed_at_ms = opened_at_ms + 60_000
    return TradeJournalEntry(
        market=market,
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
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
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=entry + value,
        filled_quantity=Decimal("1"),
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
        equity_before=Decimal(equity_before),
        equity_after=Decimal(equity_before) + value,
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
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def test_closed_trade_concentration_matches_phase9_positive_group_semantics(
    tmp_path: Path,
) -> None:
    trades = (
        _trade(
            suffix="sol-win",
            market=SOL,
            day=0,
            pnl="40",
            equity_before="10000",
        ),
        _trade(
            suffix="sol-loss",
            market=SOL,
            day=1,
            pnl="-10",
            equity_before="10040",
        ),
        _trade(
            suffix="eth-win",
            market=ETH,
            day=7,
            pnl="20",
            equity_before="10030",
        ),
        _trade(
            suffix="btc-loss",
            market=BTC,
            day=8,
            pnl="-5",
            equity_before="10050",
        ),
        _trade(
            suffix="btc-win",
            market=BTC,
            day=14,
            pnl="5",
            equity_before="10045",
        ),
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        for trade, strategy in zip(
            trades,
            ("trend", "trend", "breakout", "trend", "breakout"),
            strict=True,
        ):
            facts.record_decision_fact(
                _fact(trade, lead_strategy=strategy)
            )

        result = closed_trade_concentration_summary(trades, facts)
    finally:
        facts.close()

    assert result["trade_count"] == 5
    assert result["distinct_markets"] == 3
    assert result["distinct_lead_strategies"] == 2
    assert result["distinct_seven_day_buckets"] == 3
    assert result["decision_fact_misses"] == 0
    assert result["market_reference_max_share"] == "0.35"
    assert result["seven_day_reference_max_share"] == "0.50"
    assert result["market_reference_met"] is False
    assert result["seven_day_reference_met"] is False

    market = result["market"]
    assert isinstance(market, dict)
    assert market["largest_positive_contributor"] == "SOL"
    assert market["max_positive_net_pnl_share"] == "0.6"
    assert market["trade_count_hhi"] == "0.36"
    assert market["positive_net_pnl_hhi"] == "0.52"
    rows = market["rows"]
    assert isinstance(rows, list)
    by_market = {str(row["label"]): row for row in rows}
    assert by_market["SOL"]["net_pnl"] == "30"
    assert by_market["SOL"]["positive_net_pnl_share"] == "0.6"
    assert by_market["ETH"]["net_pnl"] == "20"
    assert by_market["ETH"]["positive_net_pnl_share"] == "0.4"
    assert by_market["BTC"]["net_pnl"] == "0"
    assert by_market["BTC"]["positive_net_pnl_share"] == "0"

    strategy = result["lead_strategy"]
    assert isinstance(strategy, dict)
    assert strategy["max_positive_net_pnl_share"] == "0.5"
    assert strategy["positive_net_pnl_hhi"] == "0.50"

    seven_day = result["seven_day"]
    assert isinstance(seven_day, dict)
    assert seven_day["largest_positive_contributor"] == "0"
    assert seven_day["max_positive_net_pnl_share"] == "0.6"
    assert seven_day["trade_count_hhi"] == "0.36"


def test_closed_trade_concentration_reports_missing_decision_facts(
    tmp_path: Path,
) -> None:
    trade = _trade(
        suffix="missing",
        market=SOL,
        day=0,
        pnl="5",
        equity_before="10000",
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        result = closed_trade_concentration_summary(
            (trade,),
            facts,
        )
    finally:
        facts.close()

    assert result["decision_fact_misses"] == 1
    strategy = result["lead_strategy"]
    assert isinstance(strategy, dict)
    assert strategy["largest_positive_contributor"] == "unknown"
    rows = strategy["rows"]
    assert isinstance(rows, list)
    assert rows[0]["label"] == "unknown"
    assert rows[0]["positive_net_pnl_share"] == "1"
