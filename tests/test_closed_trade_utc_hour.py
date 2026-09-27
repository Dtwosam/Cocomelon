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
from cocomelon.research.closed_trade_utc_hour import (
    HOUR_MS,
    closed_trade_utc_hour_summary,
)

RUN_ID = "continuous-paper-mainnet-v1"
MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    opened_at_ms: int,
    pnl: str,
    equity_before: str,
) -> TradeJournalEntry:
    value = Decimal(pnl)
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + HOUR_MS * 2,
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
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + value,
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
        holding_duration_ms=HOUR_MS * 2,
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
    decision_timestamp_ms: int,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=RUN_ID,
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=decision_timestamp_ms,
        score=Decimal("75"),
        lead_strategy="trend",
        signal_ids=(f"signal-{trade.strategy_decision_id}",),
        reason_codes=("decision_threshold_met",),
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
    )


def test_closed_trade_utc_hour_uses_decision_time_not_close_time(
    tmp_path: Path,
) -> None:
    trades = (
        _trade(
            suffix="00",
            opened_at_ms=HOUR_MS,
            pnl="10",
            equity_before="10000",
        ),
        _trade(
            suffix="08-loss",
            opened_at_ms=10 * HOUR_MS,
            pnl="-5",
            equity_before="10010",
        ),
        _trade(
            suffix="08-win",
            opened_at_ms=11 * HOUR_MS,
            pnl="2",
            equity_before="10005",
        ),
        _trade(
            suffix="23",
            opened_at_ms=23 * HOUR_MS + 30 * 60_000,
            pnl="-1",
            equity_before="10007",
        ),
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        facts.record_decision_fact(
            _fact(
                trades[0],
                decision_timestamp_ms=10 * 60_000,
            )
        )
        facts.record_decision_fact(
            _fact(
                trades[1],
                decision_timestamp_ms=8 * HOUR_MS + 15 * 60_000,
            )
        )
        facts.record_decision_fact(
            _fact(
                trades[2],
                decision_timestamp_ms=8 * HOUR_MS + 45 * 60_000,
            )
        )
        facts.record_decision_fact(
            _fact(
                trades[3],
                decision_timestamp_ms=23 * HOUR_MS + 15 * 60_000,
            )
        )

        result = closed_trade_utc_hour_summary(trades, facts)
    finally:
        facts.close()

    assert result["closed_trades"] == 4
    assert result["attributed_trades"] == 4
    assert result["attribution_misses"] == 0
    assert result["active_utc_hours"] == 3
    assert result["positive_net_pnl_hours"] == 1
    assert result["negative_net_pnl_hours"] == 2
    assert result["trade_count_hhi"] == "0.3750"

    rows = result["rows"]
    assert isinstance(rows, list)
    by_hour = {row["utc_hour"]: row for row in rows}
    assert set(by_hour) == {0, 8, 23}
    assert by_hour[0]["label"] == "00:00-00:59"
    assert by_hour[0]["net_pnl"] == "10"
    assert by_hour[0]["trade_count_share"] == "0.25"
    assert by_hour[8]["trades"] == 2
    assert by_hour[8]["wins"] == 1
    assert by_hour[8]["losses"] == 1
    assert by_hour[8]["net_pnl"] == "-3"
    assert by_hour[8]["mean_net_r"] == "-0.15"
    assert by_hour[8]["win_rate"] == "0.5"
    assert by_hour[8]["profit_factor"] == "0.4"
    assert by_hour[8]["trade_count_share"] == "0.5"
    assert by_hour[23]["net_pnl"] == "-1"


def test_closed_trade_utc_hour_reports_missing_decision_fact(
    tmp_path: Path,
) -> None:
    trade = _trade(
        suffix="missing",
        opened_at_ms=HOUR_MS,
        pnl="1",
        equity_before="10000",
    )
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    try:
        result = closed_trade_utc_hour_summary((trade,), facts)
    finally:
        facts.close()

    assert result["closed_trades"] == 1
    assert result["attributed_trades"] == 0
    assert result["attribution_misses"] == 1
    assert result["active_utc_hours"] == 0
    assert result["positive_net_pnl_hours"] == 0
    assert result["negative_net_pnl_hours"] == 0
    assert result["trade_count_hhi"] is None
    assert result["rows"] == []
