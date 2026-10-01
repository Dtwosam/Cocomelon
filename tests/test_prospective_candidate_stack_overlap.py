from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_candidate_stack_overlap import (
    prospective_candidate_stack_overlap_summary,
)


def _trade(
    suffix: str,
    *,
    opened_at_ms: int,
    pnl: str,
    direction: Direction = Direction.LONG,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId("", "SOL"),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 1_000,
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
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_candidate_stack_overlap_separates_incremental_blocks() -> None:
    trades = (
        _trade("both", opened_at_ms=1_000, pnl="-10"),
        _trade("combined-only", opened_at_ms=2_000, pnl="4"),
        _trade(
            "two-only",
            opened_at_ms=3_000,
            pnl="-6",
            direction=Direction.SHORT,
        ),
        _trade("neither", opened_at_ms=4_000, pnl="8"),
    )
    combined = {
        "started_at_ms": 500,
        "decision_block_reason_by_trade_id": {
            trades[0].trade_id: "long_trend",
            trades[1].trade_id: "rank_above_10",
            trades[2].trade_id: None,
            trades[3].trade_id: None,
        },
    }
    two_strike = {
        "started_at_ms": 900,
        "decision_prior_strikes": {
            trades[0].trade_id: 2,
            trades[1].trade_id: 0,
            trades[2].trade_id: 2,
            trades[3].trade_id: 0,
        },
    }

    result = prospective_candidate_stack_overlap_summary(
        trades,
        combined,
        two_strike,
    )

    assert result["matched_trades"] == 4
    assert result["integrity_clean"] is True
    buckets = result["buckets"]
    assert isinstance(buckets, dict)
    assert buckets["both_block"]["net_pnl"] == "-10"
    assert buckets["combined_only"]["net_pnl"] == "4"
    assert buckets["two_strike_only"]["net_pnl"] == "-6"
    assert buckets["neither_block"]["net_pnl"] == "8"
    assert result["combined_candidate_net_pnl"] == "2"
    assert result["two_strike_candidate_net_pnl"] == "12"
    assert result["stack_candidate_net_pnl"] == "8"
    assert result["stack_minus_combined_net_pnl"] == "6"
    assert result["stack_minus_two_strike_net_pnl"] == "-4"
    directions = result["two_strike_incremental_by_direction"]
    assert isinstance(directions, dict)
    assert directions["short"]["trades"] == 1
    assert directions["short"]["net_pnl"] == "-6"


def test_candidate_stack_overlap_reports_missing_decisions() -> None:
    first = _trade("first", opened_at_ms=2_000, pnl="-5")
    second = _trade("second", opened_at_ms=3_000, pnl="-3")
    third = _trade("third", opened_at_ms=4_000, pnl="-2")
    result = prospective_candidate_stack_overlap_summary(
        (first, second, third),
        {
            "started_at_ms": 1_000,
            "decision_block_reason_by_trade_id": {
                first.trade_id: None,
            },
        },
        {
            "started_at_ms": 1_500,
            "decision_prior_strikes": {
                first.trade_id: 0,
                second.trade_id: 2,
            },
        },
    )

    assert result["closed_trades_since_overlap_start"] == 3
    assert result["matched_trades"] == 1
    assert result["missing_combined_decisions"] == 2
    assert result["missing_two_strike_decisions"] == 1
    assert result["integrity_clean"] is False


def test_candidate_stack_overlap_uses_later_clean_start() -> None:
    old = _trade("old", opened_at_ms=1_000, pnl="-5")
    clean = _trade("clean", opened_at_ms=5_000, pnl="-4")
    result = prospective_candidate_stack_overlap_summary(
        (old, clean),
        {
            "started_at_ms": 500,
            "decision_block_reason_by_trade_id": {
                old.trade_id: None,
                clean.trade_id: None,
            },
        },
        {
            "started_at_ms": 4_000,
            "decision_prior_strikes": {
                clean.trade_id: 2,
            },
        },
    )

    assert result["overlap_started_at_ms"] == 4_000
    assert result["closed_trades_since_overlap_start"] == 1
    assert result["matched_trades"] == 1
    buckets = result["buckets"]
    assert isinstance(buckets, dict)
    assert buckets["two_strike_only"]["trades"] == 1
    assert buckets["two_strike_only"]["net_pnl"] == "-4"
