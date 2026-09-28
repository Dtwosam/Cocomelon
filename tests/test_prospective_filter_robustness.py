from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_filter_robustness import (
    prospective_filter_robustness,
)


def _trade(
    *,
    suffix: str,
    market: str,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    value = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 1_000,
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


def test_filter_robustness_survives_single_trade_and_market_removal() -> None:
    items = (
        (_trade(
            suffix="a",
            market="SOL",
            opened_at_ms=1_000,
            pnl="-8",
        ), True),
        (_trade(
            suffix="b",
            market="ETH",
            opened_at_ms=2_000,
            pnl="-6",
        ), True),
        (_trade(
            suffix="c",
            market="BTC",
            opened_at_ms=3_000,
            pnl="2",
        ), True),
        (_trade(
            suffix="d",
            market="BTC",
            opened_at_ms=4_000,
            pnl="5",
        ), False),
    )

    result = prospective_filter_robustness(items)

    assert result["total_delta_trade_contribution_pnl"] == "12"
    assert result["largest_abs_trade_contribution"] == "8"
    assert result["largest_abs_trade_market"] == "SOL"
    assert result["leave_one_trade_out_min_delta"] == "4"
    assert result["positive_after_any_single_trade_removed"] is True
    assert result["largest_abs_market"] == "SOL"
    assert result["largest_abs_market_contribution"] == "8"
    assert result["leave_one_market_out_min_delta"] == "4"
    assert result["positive_after_any_single_market_removed"] is True
    assert result["changes_readiness_gate"] is False


def test_filter_robustness_detects_single_market_dependency() -> None:
    items = (
        (_trade(
            suffix="a",
            market="SOL",
            opened_at_ms=1_000,
            pnl="-10",
        ), True),
        (_trade(
            suffix="b",
            market="SOL",
            opened_at_ms=2_000,
            pnl="-5",
        ), True),
        (_trade(
            suffix="c",
            market="ETH",
            opened_at_ms=3_000,
            pnl="2",
        ), True),
    )

    result = prospective_filter_robustness(items)

    assert result["total_delta_trade_contribution_pnl"] == "13"
    assert result["largest_abs_market"] == "SOL"
    assert result["largest_abs_market_contribution"] == "15"
    assert result["leave_one_market_out_min_delta"] == "-2"
    assert result["positive_after_any_single_market_removed"] is False


def test_filter_robustness_reports_four_full_chronological_blocks() -> None:
    items = tuple(
        (
            _trade(
                suffix=str(index),
                market=f"M{index % 3}",
                opened_at_ms=index * 10_000,
                pnl="-1",
            ),
            True,
        )
        for index in range(20)
    )

    result = prospective_filter_robustness(items)
    temporal = result["temporal"]
    assert isinstance(temporal, dict)
    assert temporal["full_blocks"] == 4
    assert temporal["positive_full_blocks"] == 4
    assert temporal["all_full_blocks_positive"] is True
    blocks = temporal["chronological_blocks"]
    assert isinstance(blocks, list)
    assert [block["trades"] for block in blocks] == [5, 5, 5, 5]
    assert [
        block["delta_trade_contribution_pnl"]
        for block in blocks
    ] == ["5", "5", "5", "5"]
