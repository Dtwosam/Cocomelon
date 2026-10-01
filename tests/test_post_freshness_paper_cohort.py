from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.post_freshness_paper_cohort import (
    COHORT_STARTED_AT_MS,
    post_freshness_paper_cohort_summary,
)


def _trade(
    suffix: str,
    *,
    opened_at_ms: int,
    direction: Direction,
    pnl: str,
    exit_reason: str = "MARK_STOP_TRIGGERED",
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId("", "SOL" if direction is Direction.LONG else "ETH"),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
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
        holding_duration_ms=60_000,
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


def test_post_freshness_cohort_uses_open_time_boundary() -> None:
    trades = (
        _trade(
            "pre-loss",
            opened_at_ms=COHORT_STARTED_AT_MS - 1,
            direction=Direction.LONG,
            pnl="-10",
        ),
        _trade(
            "pre-win",
            opened_at_ms=COHORT_STARTED_AT_MS - 100_000,
            direction=Direction.SHORT,
            pnl="4",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "post-long-loss",
            opened_at_ms=COHORT_STARTED_AT_MS,
            direction=Direction.LONG,
            pnl="-5",
        ),
        _trade(
            "post-long-win",
            opened_at_ms=COHORT_STARTED_AT_MS + 1,
            direction=Direction.LONG,
            pnl="8",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
        _trade(
            "post-short-loss",
            opened_at_ms=COHORT_STARTED_AT_MS + 2,
            direction=Direction.SHORT,
            pnl="-3",
        ),
        _trade(
            "post-short-win",
            opened_at_ms=COHORT_STARTED_AT_MS + 3,
            direction=Direction.SHORT,
            pnl="6",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
    )

    result = post_freshness_paper_cohort_summary(trades)

    assert result["cohort_closed_trades"] == 4
    assert result["pre_cohort_closed_trades"] == 2
    assert result["cohort_wins"] == 2
    assert result["cohort_losses"] == 2
    assert result["cohort_net_pnl"] == "6"
    assert result["cohort_net_r"] == "0.6"
    assert result["cohort_mean_net_r"] == "0.15"
    assert result["pre_cohort_net_pnl"] == "-6"
    assert result["pre_cohort_mean_net_r"] == "-0.3"

    by_direction = result["by_direction"]
    assert isinstance(by_direction, dict)
    assert by_direction["long"]["trades"] == 2
    assert by_direction["long"]["net_pnl"] == "3"
    assert by_direction["short"]["trades"] == 2
    assert by_direction["short"]["net_pnl"] == "3"

    exits = result["by_exit_reason"]
    assert isinstance(exits, dict)
    assert exits["MARK_STOP_TRIGGERED"]["trades"] == 2
    assert exits["MARK_STOP_TRIGGERED"]["net_pnl"] == "-8"
    assert exits["OPPOSITE_FRESH_THESIS"]["trades"] == 2
    assert exits["OPPOSITE_FRESH_THESIS"]["net_pnl"] == "14"


def test_post_freshness_cohort_is_zero_safe() -> None:
    result = post_freshness_paper_cohort_summary(())

    assert result["cohort_closed_trades"] == 0
    assert result["pre_cohort_closed_trades"] == 0
    assert result["cohort_mean_net_r"] is None
    assert result["pre_cohort_mean_net_r"] is None
    assert result["descriptive_sample_complete"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
