from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_allowed_residual import (
    AllowedResidualItem,
    ProspectiveAllowedResidualError,
    prospective_allowed_residual_attribution,
)


def _trade(
    *,
    suffix: str,
    market: str,
    direction: Direction,
    pnl: str,
) -> TradeJournalEntry:
    value = Decimal(pnl)
    entry = Decimal("100")
    exit_price = (
        entry + value
        if direction is Direction.LONG
        else entry - value
    )
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
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
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=exit_price,
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
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=value / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + value,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def test_allowed_residual_attribution_explains_remaining_losses() -> None:
    items = (
        AllowedResidualItem(
            _trade(
                suffix="a",
                market="SOL",
                direction=Direction.LONG,
                pnl="-8",
            ),
            lead_strategy="breakout",
            ordinal=3,
        ),
        AllowedResidualItem(
            _trade(
                suffix="b",
                market="ETH",
                direction=Direction.SHORT,
                pnl="5",
            ),
            lead_strategy="trend",
            ordinal=8,
        ),
        AllowedResidualItem(
            _trade(
                suffix="c",
                market="SOL",
                direction=Direction.SHORT,
                pnl="-2",
            ),
            lead_strategy="breakout",
            ordinal=12,
        ),
    )

    result = prospective_allowed_residual_attribution(items)

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 3
    assert overall["net_pnl"] == "-5"
    assert overall["winner_pnl"] == "5"
    assert overall["loser_pnl"] == "-10"

    by_side = result["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["net_pnl"] == "-8"
    assert by_side["short"]["net_pnl"] == "3"

    by_strategy = result["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["breakout"]["net_pnl"] == "-10"
    assert by_strategy["trend"]["net_pnl"] == "5"

    by_rank = result["by_rank_band"]
    assert isinstance(by_rank, dict)
    assert by_rank["1-5"]["net_pnl"] == "-8"
    assert by_rank["6-10"]["net_pnl"] == "5"
    assert by_rank["11-20"]["net_pnl"] == "-2"

    worst = result["worst_side_lead_strategy"]
    assert isinstance(worst, dict)
    assert worst["label"] == "long:breakout"
    assert worst["net_pnl"] == "-8"

    worst_market = result["worst_market"]
    assert isinstance(worst_market, dict)
    assert worst_market["label"] == "SOL"
    assert worst_market["net_pnl"] == "-10"
    assert result["changes_readiness_gate"] is False


def test_allowed_residual_attribution_omits_unavailable_dimensions() -> None:
    item = AllowedResidualItem(
        _trade(
            suffix="a",
            market="SOL",
            direction=Direction.SHORT,
            pnl="1",
        )
    )
    result = prospective_allowed_residual_attribution((item,))

    assert result["by_lead_strategy"] == {}
    assert result["by_rank_band"] == {}
    assert result["worst_lead_strategy"] is None
    assert result["worst_rank_band"] is None


def test_allowed_residual_rejects_duplicate_trade_ids() -> None:
    trade = _trade(
        suffix="dup",
        market="SOL",
        direction=Direction.LONG,
        pnl="-1",
    )
    with pytest.raises(
        ProspectiveAllowedResidualError,
        match="duplicate trade ids",
    ):
        prospective_allowed_residual_attribution(
            (
                AllowedResidualItem(trade),
                AllowedResidualItem(trade),
            )
        )
