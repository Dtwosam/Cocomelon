from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_filter_fixed_schedule import (
    ProspectiveFilterFixedScheduleError,
    ProspectiveFilterPortfolioItem,
    prospective_filter_fixed_schedule_portfolio,
)


def _trade(
    *,
    suffix: str,
    opened_at_ms: int,
    closed_at_ms: int,
    pnl: str,
    quantity: str = "1",
) -> TradeJournalEntry:
    value = Decimal(pnl)
    qty = Decimal(quantity)
    entry = Decimal("100")
    return TradeJournalEntry(
        market=MarketId("", suffix.upper()),
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(
            f"open-fill-{suffix}",
            f"exit-fill-{suffix}",
        ),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10") * qty,
        entry_price=entry,
        exit_price=entry + (value / qty),
        filled_quantity=qty,
        gross_realized_pnl=value,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=value,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=value / (Decimal("10") * qty),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + value,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_fixed_schedule_filter_portfolio_tracks_drawdown_and_exposure() -> None:
    items = (
        ProspectiveFilterPortfolioItem(
            _trade(
                suffix="a",
                opened_at_ms=1_000,
                closed_at_ms=5_000,
                pnl="-10",
            ),
            admitted=False,
        ),
        ProspectiveFilterPortfolioItem(
            _trade(
                suffix="b",
                opened_at_ms=2_000,
                closed_at_ms=6_000,
                pnl="5",
            ),
            admitted=True,
        ),
        ProspectiveFilterPortfolioItem(
            _trade(
                suffix="c",
                opened_at_ms=3_000,
                closed_at_ms=4_000,
                pnl="-3",
            ),
            admitted=False,
        ),
    )

    result = prospective_filter_fixed_schedule_portfolio(items)

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert actual["final_realized_contribution"] == "-8"
    assert candidate["final_realized_contribution"] == "5"
    assert result["delta_final_realized_contribution"] == "13"
    assert actual["max_realized_drawdown"] == "13"
    assert candidate["max_realized_drawdown"] == "0"
    assert result["delta_max_realized_drawdown"] == "-13"
    assert actual["max_concurrent_positions"] == 3
    assert candidate["max_concurrent_positions"] == 1
    assert actual["max_gross_notional"] == "300"
    assert candidate["max_gross_notional"] == "100"
    assert actual["max_planned_risk"] == "30"
    assert candidate["max_planned_risk"] == "10"
    assert result["blocked_actual_net_pnl"] == "-13"
    assert result["replacement_trades_modeled"] is False
    assert result["candidate_equity_resizing_modeled"] is False
    assert result["changes_readiness_gate"] is False


def test_fixed_schedule_filter_portfolio_exposes_cost_of_skipped_winner() -> None:
    items = (
        ProspectiveFilterPortfolioItem(
            _trade(
                suffix="winner",
                opened_at_ms=1_000,
                closed_at_ms=3_000,
                pnl="10",
            ),
            admitted=False,
        ),
        ProspectiveFilterPortfolioItem(
            _trade(
                suffix="loss",
                opened_at_ms=2_000,
                closed_at_ms=4_000,
                pnl="-2",
            ),
            admitted=True,
        ),
    )

    result = prospective_filter_fixed_schedule_portfolio(items)

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert actual["final_realized_contribution"] == "8"
    assert candidate["final_realized_contribution"] == "-2"
    assert result["delta_final_realized_contribution"] == "-10"
    assert result["blocked_actual_net_pnl"] == "10"
    assert candidate["max_realized_drawdown"] == "2"


def test_fixed_schedule_filter_portfolio_rejects_duplicate_trades() -> None:
    trade = _trade(
        suffix="dup",
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        pnl="1",
    )
    with pytest.raises(
        ProspectiveFilterFixedScheduleError,
        match="duplicate trade ids",
    ):
        prospective_filter_fixed_schedule_portfolio(
            (
                ProspectiveFilterPortfolioItem(
                    trade,
                    admitted=True,
                ),
                ProspectiveFilterPortfolioItem(
                    trade,
                    admitted=False,
                ),
            )
        )



def test_fixed_schedule_exactly_flattens_high_precision_overlap() -> None:
    items = (
        ProspectiveFilterPortfolioItem(
            _trade(
                suffix="precision-a",
                opened_at_ms=1_000,
                closed_at_ms=3_000,
                pnl="0",
                quantity="77416898026317.92986302563684111",
            ),
            admitted=True,
        ),
        ProspectiveFilterPortfolioItem(
            _trade(
                suffix="precision-b",
                opened_at_ms=2_000,
                closed_at_ms=4_000,
                pnl="0",
                quantity="75676232014740.16417343828836660",
            ),
            admitted=True,
        ),
    )

    result = prospective_filter_fixed_schedule_portfolio(items)

    actual = result["actual"]
    candidate = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(candidate, dict)
    assert actual["final_realized_contribution"] == "0"
    assert candidate["final_realized_contribution"] == "0"
    assert actual["max_gross_notional"] == (
        "15309313004105809.403646392521"
    )
    assert actual["max_planned_risk"] == (
        "1530931300410580.9403646392521"
    )
    assert candidate["max_gross_notional"] == (
        actual["max_gross_notional"]
    )
    assert candidate["max_planned_risk"] == (
        actual["max_planned_risk"]
    )
