from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.closed_trade_lifecycle_economics import (
    ClosedTradeLifecycleEconomicsError,
    closed_trade_lifecycle_economics,
)


def trade(
    n: int,
    *,
    side: Direction = Direction.LONG,
    symbol: str = "SOL",
    gross: str = "2",
    fee: str = "0.5",
    funding: str = "0",
    mfe: str | None = "0.8",
    complete: bool = True,
    exit_reason: str = "MARK_STOP_TRIGGERED",
) -> SimpleNamespace:
    gross_pnl = Decimal(gross)
    fees = Decimal(fee)
    funding_pnl = Decimal(funding)
    net = gross_pnl - fees + funding_pnl
    excursion = (
        None if mfe is None
        else SimpleNamespace(
            complete=complete, r_multiple=Decimal(mfe)
        )
    )
    mae = (
        None if mfe is None
        else SimpleNamespace(
            complete=complete, r_multiple=Decimal("-0.4")
        )
    )
    return SimpleNamespace(
        trade_id=f"trade-{n}",
        market=MarketId("", symbol),
        direction=side,
        opened_at_ms=n * 1000,
        closed_at_ms=n * 1000 + 500,
        replay_run_id="continuous-paper-mainnet-v1",
        strategy_decision_id=f"decision-{n}",
        feature_snapshot_id=f"feature-{n}",
        gross_realized_pnl=gross_pnl,
        entry_fees=fees / 2,
        exit_fees=fees / 2,
        funding_cash_pnl=funding_pnl,
        entry_slippage_amount=Decimal("0.1"),
        exit_slippage_amount=Decimal("0.2"),
        net_pnl=net,
        net_r=net / Decimal("10"),
        mfe=excursion,
        mae=mae,
        exit_reason=exit_reason,
        holding_duration_ms=500_000,
    )


class Facts:
    def __init__(
        self,
        values: tuple[SimpleNamespace, ...],
        *,
        missing: tuple[str, ...] = (),
        bad_future: bool = False,
    ) -> None:
        self.rows = {
            value.strategy_decision_id: SimpleNamespace(
                market=value.market,
                direction=value.direction,
                feature_snapshot_id=value.feature_snapshot_id,
                timestamp_ms=(
                    value.opened_at_ms + 1 if bad_future
                    else value.opened_at_ms - 1
                ),
                lead_strategy="trend" if value.direction is Direction.LONG
                else "breakout",
                trend_regime=SimpleNamespace(value="down"),
                volatility_regime=SimpleNamespace(value="normal"),
            )
            for value in values
            if value.strategy_decision_id not in missing
        }

    def load_decision_by_strategy_id(
        self, decision_id: str, run_id: str
    ) -> SimpleNamespace | None:
        assert run_id == "continuous-paper-mainnet-v1"
        return self.rows.get(decision_id)


def test_realized_losses_separate_entry_exit_and_friction() -> None:
    t1 = trade(1, gross="5", fee="1", mfe="1.4")
    t2 = trade(2, gross="-3", fee="1", mfe="1.2")
    t3 = trade(
        3, side=Direction.SHORT, gross="-2", fee="0.8", mfe="0.1"
    )
    t4 = trade(
        4, side=Direction.SHORT, gross="0.4", fee="0.6", mfe="0.3"
    )
    t5 = trade(
        5, side=Direction.SHORT, gross="3", fee="0.5",
        funding="-0.1", mfe=None,
    )
    values = (t1, t2, t3, t4, t5)
    result = closed_trade_lifecycle_economics(
        values, Facts(values, missing=(t5.strategy_decision_id,))
    )
    assert result["research_only"] is True
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False
    assert result["decision_fact_attribution_misses"] == 1
    overall = result["overall"]
    assert overall["trades"] == 5
    assert overall["wins"] == 2
    assert overall["losses"] == 3
    assert Decimal(overall["net_pnl"]) == Decimal("-0.6")
    assert Decimal(overall["net_reconciliation_residual"]) == 0
    assert overall["complete_excursion_trades"] == 4
    assert overall["loss_without_0_25r_favorable_mark"] == 1
    assert overall["loss_after_0_5r_favorable_mark"] == 1
    assert overall["loss_after_1r_favorable_mark"] == 1
    assert overall["gross_winners_flipped_by_fees_and_funding"] == 1
    assert Decimal(overall["entry_signed_slippage"]) == Decimal("0.5")
    assert Decimal(overall["exit_signed_slippage"]) == Decimal("1.0")
    assert result["by_side_and_holding_duration"]["short | 5_to_15m"]["trades"] == 3
    assert result["by_side_and_lead_strategy"]["long | trend"]["trades"] == 2
    assert result["by_side_and_lead_strategy"]["short | breakout"]["trades"] == 2
    assert result["by_side_and_lead_strategy"]["short | unknown"]["trades"] == 1
    assert result["by_side_and_regime"]["short | down | normal"]["trades"] == 2
    assert result["by_side"]["short"]["wins"] == 1
    assert result["by_side"]["short"]["losses"] == 2
    assert overall["worth_independent_forward_test"] is False


def test_duplicate_trades_and_future_decision_lineage_fail_closed() -> None:
    row = trade(1)
    with pytest.raises(
        ClosedTradeLifecycleEconomicsError, match="duplicate"
    ):
        closed_trade_lifecycle_economics((row, row), Facts((row,)))
    with pytest.raises(
        ClosedTradeLifecycleEconomicsError, match="future decision"
    ):
        closed_trade_lifecycle_economics(
            (row,), Facts((row,), bad_future=True)
        )


def test_missing_excursion_never_claims_unobserved_price_path() -> None:
    row = trade(7, gross="-2", mfe="1.3", complete=False)
    result = closed_trade_lifecycle_economics((row,), Facts((row,)))
    overall = result["overall"]
    assert overall["complete_excursion_trades"] == 0
    assert overall["incomplete_excursion_trades"] == 1
    assert overall["loss_after_0_5r_favorable_mark"] == 0
    assert overall["loss_without_0_25r_favorable_mark"] == 0
    assert overall["peak_to_close_mean_r"] is None


def test_positive_both_halves_and_robustness_identify_only_research_targets() -> None:
    values = tuple(
        trade(
            i + 1,
            side=Direction.SHORT,
            symbol=("SOL" if i % 2 else "BTC"),
            gross="3",
            fee="0.5",
        )
        for i in range(20)
    )
    result = closed_trade_lifecycle_economics(values, Facts(values))
    breakout = result["by_side_and_lead_strategy"]["short | breakout"]
    assert breakout["sufficient_for_retrospective_profile"] is True
    assert breakout["worth_independent_forward_test"] is True
    assert Decimal(breakout["chronological_first_half_net_pnl"]) > 0
    assert Decimal(breakout["chronological_second_half_net_pnl"]) > 0
    assert Decimal(breakout["net_pnl_without_largest_winner"]) > 0
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_positive_aggregate_with_bad_first_half_is_not_forward_test_target() -> None:
    values = tuple(
        trade(
            i + 1,
            symbol=("SOL" if i % 2 else "BTC"),
            gross="-1" if i < 10 else "5",
            fee="0.5",
        )
        for i in range(20)
    )
    row = closed_trade_lifecycle_economics(values, Facts(values))[
        "by_side_and_lead_strategy"
    ]["long | trend"]
    assert Decimal(row["net_pnl"]) > 0
    assert Decimal(row["chronological_first_half_net_pnl"]) < 0
    assert row["worth_independent_forward_test"] is False
