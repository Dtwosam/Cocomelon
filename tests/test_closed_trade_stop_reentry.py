from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.closed_trade_stop_reentry import (
    closed_trade_stop_reentry_summary,
)


def _trade(
    suffix: str,
    *,
    market: str = "SOL",
    direction: Direction = Direction.LONG,
    opened_at_ms: int,
    closed_at_ms: int,
    pnl: str,
    exit_reason: str = "MARK_STOP_TRIGGERED",
) -> TradeJournalEntry:
    net = Decimal(pnl)
    entry = Decimal("100")
    exit_price = (
        entry + net
        if direction is Direction.LONG
        else entry - net
    )
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
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
        holding_duration_ms=closed_at_ms - opened_at_ms,
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


def test_stop_reentry_attribution_buckets_and_skip_windows() -> None:
    trades = (
        _trade(
            "sol-first",
            opened_at_ms=0,
            closed_at_ms=60_000,
            pnl="-10",
        ),
        _trade(
            "sol-quick",
            opened_at_ms=120_000,
            closed_at_ms=180_000,
            pnl="-5",
        ),
        _trade(
            "sol-mid",
            opened_at_ms=600_000,
            closed_at_ms=660_000,
            pnl="8",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "sol-reset",
            opened_at_ms=900_000,
            closed_at_ms=960_000,
            pnl="4",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "eth-first",
            market="ETH",
            direction=Direction.SHORT,
            opened_at_ms=1_000_000,
            closed_at_ms=1_060_000,
            pnl="-6",
        ),
        _trade(
            "eth-late",
            market="ETH",
            direction=Direction.SHORT,
            opened_at_ms=9_000_000,
            closed_at_ms=9_060_000,
            pnl="-2",
        ),
    )

    result = closed_trade_stop_reentry_summary(trades)

    assert result["closed_trades"] == 6
    assert result["reentry_trades"] == 3
    assert result["fresh_or_reset_trades"] == 3
    assert result["reentry_wins"] == 1
    assert result["reentry_losses"] == 2
    assert result["reentry_net_pnl"] == "1"
    assert result["fresh_or_reset_net_pnl"] == "-12"

    buckets = result["by_gap_bucket"]
    assert isinstance(buckets, dict)
    assert buckets["0-5m"]["trades"] == 1
    assert buckets["0-5m"]["net_pnl"] == "-5"
    assert buckets["5-30m"]["trades"] == 1
    assert buckets["5-30m"]["net_pnl"] == "8"
    assert buckets["120m+"]["trades"] == 1
    assert buckets["120m+"]["net_pnl"] == "-2"

    windows = result["skip_windows"]
    assert isinstance(windows, dict)
    within_5m = windows["within_5m"]
    assert within_5m["blocked_trades"] == 1
    assert within_5m["blocked_winners"] == 0
    assert within_5m["blocked_losses"] == 1
    assert within_5m["blocked_net_pnl"] == "-5"
    assert within_5m["delta_trade_contribution_pnl"] == "5"

    within_30m = windows["within_30m"]
    assert within_30m["blocked_trades"] == 2
    assert within_30m["blocked_winners"] == 1
    assert within_30m["blocked_losses"] == 1
    assert within_30m["blocked_net_pnl"] == "3"
    assert within_30m["delta_trade_contribution_pnl"] == "-3"
    robustness = within_30m["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["positive_after_removing_any_one_trade"] is False

    within_120m = windows["within_120m"]
    assert within_120m["blocked_trades"] == 2
    assert within_120m["blocked_net_pnl"] == "3"


def test_stop_reentry_uses_most_recent_completed_same_side_trade() -> None:
    trades = (
        _trade(
            "old-loss",
            opened_at_ms=0,
            closed_at_ms=100_000,
            pnl="-10",
        ),
        _trade(
            "overlapping",
            opened_at_ms=50_000,
            closed_at_ms=150_000,
            pnl="-3",
        ),
        _trade(
            "after-both",
            opened_at_ms=160_000,
            closed_at_ms=220_000,
            pnl="2",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "after-reset",
            opened_at_ms=300_000,
            closed_at_ms=360_000,
            pnl="-1",
        ),
        _trade(
            "other-side",
            direction=Direction.SHORT,
            opened_at_ms=370_000,
            closed_at_ms=430_000,
            pnl="-4",
        ),
    )

    result = closed_trade_stop_reentry_summary(trades)

    assert result["reentry_trades"] == 1
    assert result["fresh_or_reset_trades"] == 4
    buckets = result["by_gap_bucket"]
    assert isinstance(buckets, dict)
    assert buckets["0-5m"]["trades"] == 1
    assert buckets["0-5m"]["net_pnl"] == "2"

    by_direction = result["reentry_by_direction"]
    assert isinstance(by_direction, dict)
    assert by_direction["long"]["trades"] == 1
    assert by_direction["short"]["trades"] == 0


def test_stop_reentry_empty_summary_is_zero_safe() -> None:
    result = closed_trade_stop_reentry_summary(())

    assert result["closed_trades"] == 0
    assert result["reentry_trades"] == 0
    assert result["fresh_or_reset_trades"] == 0
    windows = result["skip_windows"]
    assert isinstance(windows, dict)
    assert windows["within_5m"]["blocked_trades"] == 0
    assert windows["within_5m"]["delta_trade_contribution_pnl"] == "0"
