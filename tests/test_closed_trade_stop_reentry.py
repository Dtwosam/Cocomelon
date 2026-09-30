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


def test_stop_reentry_tracks_prior_losing_stop_streak_depth() -> None:
    trades = (
        _trade(
            "sol-loss-1",
            opened_at_ms=0,
            closed_at_ms=60_000,
            pnl="-10",
        ),
        _trade(
            "sol-loss-2",
            opened_at_ms=600_000,
            closed_at_ms=660_000,
            pnl="-6",
        ),
        _trade(
            "sol-loss-3",
            opened_at_ms=1_200_000,
            closed_at_ms=1_260_000,
            pnl="-4",
        ),
        _trade(
            "sol-winner",
            opened_at_ms=1_800_000,
            closed_at_ms=1_860_000,
            pnl="3",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "eth-loss-1",
            market="ETH",
            opened_at_ms=2_400_000,
            closed_at_ms=2_460_000,
            pnl="-8",
        ),
        _trade(
            "eth-loss-2",
            market="ETH",
            opened_at_ms=3_000_000,
            closed_at_ms=3_060_000,
            pnl="-5",
        ),
        _trade(
            "eth-loss-3",
            market="ETH",
            opened_at_ms=3_600_000,
            closed_at_ms=3_660_000,
            pnl="-7",
        ),
    )

    result = closed_trade_stop_reentry_summary(trades)

    by_streak = result["by_prior_losing_stop_streak"]
    assert isinstance(by_streak, dict)
    assert by_streak["0"]["trades"] == 2
    assert by_streak["1"]["trades"] == 2
    assert by_streak["2"]["trades"] == 2
    assert by_streak["3+"]["trades"] == 1
    assert by_streak["2"]["wins"] == 0
    assert by_streak["2"]["losses"] == 2
    assert by_streak["2"]["net_pnl"] == "-11"
    assert by_streak["3+"]["net_pnl"] == "3"

    thresholds = result["skip_after_prior_losing_stops"]
    assert isinstance(thresholds, dict)
    after_2 = thresholds["after_2"]
    assert after_2["blocked_trades"] == 3
    assert after_2["blocked_winners"] == 1
    assert after_2["blocked_losses"] == 2
    assert after_2["blocked_net_pnl"] == "-8"
    assert after_2["delta_trade_contribution_pnl"] == "8"
    robustness = after_2["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["leave_one_trade_out_min_delta_pnl"] == "1"
    assert robustness["positive_after_removing_any_one_trade"] is True
    market_robustness = after_2["market_robustness"]
    assert isinstance(market_robustness, dict)
    assert market_robustness["market_count"] == 2
    assert market_robustness["leave_one_market_out_min_delta_pnl"] == "1"
    assert (
        market_robustness["positive_after_removing_any_one_market"]
        is True
    )

    after_3 = thresholds["after_3"]
    assert after_3["blocked_trades"] == 1
    assert after_3["blocked_winners"] == 1
    assert after_3["delta_trade_contribution_pnl"] == "-3"
