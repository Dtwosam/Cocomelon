from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import ExcursionMetric, TradeJournalEntry
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
    mfe_r: str | None = None,
    mfe_complete: bool = True,
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
        mfe=(
            None
            if mfe_r is None
            else ExcursionMetric(
                kind="mfe",
                price=Decimal("101"),
                per_unit=Decimal("1"),
                fraction=Decimal("0.01"),
                currency=Decimal(mfe_r) * Decimal("10"),
                r_multiple=Decimal(mfe_r),
                timestamp_ms=1_500,
                source_event_key=f"mfe-{suffix}",
                complete=mfe_complete,
            )
        ),
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



def test_allowed_residual_classifies_bad_entries_vs_profit_giveback() -> None:
    items = (
        AllowedResidualItem(
            _trade(
                suffix="never-worked",
                market="SOL",
                direction=Direction.LONG,
                pnl="-8",
                mfe_r="0.10",
            ),
            lead_strategy="breakout",
            ordinal=2,
        ),
        AllowedResidualItem(
            _trade(
                suffix="giveback-sol",
                market="SOL",
                direction=Direction.SHORT,
                pnl="-2",
                mfe_r="0.80",
            ),
            lead_strategy="breakout",
            ordinal=4,
        ),
        AllowedResidualItem(
            _trade(
                suffix="giveback-eth",
                market="ETH",
                direction=Direction.LONG,
                pnl="-4",
                mfe_r="1.20",
            ),
            lead_strategy="breakout",
            ordinal=5,
        ),
        AllowedResidualItem(
            _trade(
                suffix="missing",
                market="BTC",
                direction=Direction.SHORT,
                pnl="-1",
            ),
            lead_strategy="trend",
            ordinal=7,
        ),
        AllowedResidualItem(
            _trade(
                suffix="winner",
                market="ETH",
                direction=Direction.SHORT,
                pnl="5",
                mfe_r="0.70",
            ),
            lead_strategy="trend",
            ordinal=8,
        ),
    )

    result = prospective_allowed_residual_attribution(items)

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["losses"] == 4
    assert overall["complete_excursion_losses"] == 3
    assert overall["missing_or_incomplete_excursion_losses"] == 1
    assert overall["losses_with_mfe_lt_0_25r"] == 1
    assert overall["losses_after_mfe_ge_0_5r"] == 2
    assert overall["losses_after_mfe_ge_1r"] == 1
    assert overall["loss_pnl_with_mfe_lt_0_25r"] == "-8"
    assert overall["loss_pnl_after_mfe_ge_0_5r"] == "-6"
    assert overall["loss_pnl_after_mfe_ge_1r"] == "-4"

    by_market = result["by_market"]
    assert isinstance(by_market, dict)
    assert by_market["SOL"]["losses_with_mfe_lt_0_25r"] == 1
    assert by_market["ETH"]["losses_after_mfe_ge_1r"] == 1

    worst_never_worked = result["worst_market_never_worked"]
    assert isinstance(worst_never_worked, dict)
    assert worst_never_worked["label"] == "SOL"
    assert worst_never_worked["losses"] == 1
    assert worst_never_worked["loss_pnl"] == "-8"

    worst_giveback = result["worst_market_giveback"]
    assert isinstance(worst_giveback, dict)
    assert worst_giveback["label"] == "ETH"
    assert worst_giveback["losses"] == 1
    assert worst_giveback["loss_pnl"] == "-4"
