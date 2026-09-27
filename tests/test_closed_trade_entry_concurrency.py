from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.closed_trade_entry_concurrency import (
    closed_trade_entry_concurrency,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
    net_pnl: str,
) -> TradeJournalEntry:
    pnl = Decimal(net_pnl)
    entry = Decimal("100")
    exit_price = (
        entry + pnl
        if direction is Direction.LONG
        else entry - pnl
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"open-plan-{suffix}",
        opening_attempt_id=f"open-attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(
            f"open-fill-{suffix}",
            f"exit-fill-{suffix}",
        ),
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
        gross_realized_pnl=pnl,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=pnl / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _open_position(
    *,
    suffix: str,
    side: PositionSide,
    opened_at_ms: int,
) -> PaperPosition:
    return PaperPosition(
        market=MarketId("", f"OPEN{suffix}"),
        side=side,
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("90"),
        opening_plan_id=f"open-position-{suffix}",
        opened_at_ms=opened_at_ms,
        updated_at_ms=opened_at_ms + 1,
        planned_risk=Decimal("10"),
    )


def test_concurrency_groups_solo_and_preexisting_overlap() -> None:
    first = _trade(
        suffix="first",
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=10_000,
        net_pnl="5",
    )
    second = _trade(
        suffix="second",
        direction=Direction.LONG,
        opened_at_ms=2_000,
        closed_at_ms=5_000,
        net_pnl="-3",
    )
    third = _trade(
        suffix="third",
        direction=Direction.SHORT,
        opened_at_ms=3_000,
        closed_at_ms=4_000,
        net_pnl="-2",
    )

    result = closed_trade_entry_concurrency(
        (first, second, third)
    )

    buckets = result["by_concurrency_bucket"]
    assert isinstance(buckets, dict)
    assert buckets["0"]["trades"] == 1
    assert buckets["0"]["net_pnl"] == "5"
    assert buckets["1"]["trades"] == 1
    assert buckets["1"]["net_pnl"] == "-3"
    assert buckets["2"]["trades"] == 1
    assert buckets["2"]["net_pnl"] == "-2"

    solo = result["solo"]
    overlap = result["overlapping"]
    assert isinstance(solo, dict)
    assert isinstance(overlap, dict)
    assert solo["trades"] == 1
    assert overlap["trades"] == 2
    assert overlap["net_pnl"] == "-5"

    same_side = result["by_same_side_overlap"]
    assert isinstance(same_side, dict)
    assert same_side["1+"]["trades"] == 1
    assert same_side["1+"]["net_pnl"] == "-3"


def test_same_timestamp_opening_is_not_prior_exposure() -> None:
    first = _trade(
        suffix="a",
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=5_000,
        net_pnl="1",
    )
    second = _trade(
        suffix="b",
        direction=Direction.SHORT,
        opened_at_ms=1_000,
        closed_at_ms=4_000,
        net_pnl="2",
    )

    result = closed_trade_entry_concurrency((first, second))
    buckets = result["by_concurrency_bucket"]
    assert isinstance(buckets, dict)
    assert buckets["0"]["trades"] == 2
    assert buckets["1"]["trades"] == 0


def test_current_open_position_can_supply_historical_prior_overlap() -> None:
    trade = _trade(
        suffix="closed",
        direction=Direction.SHORT,
        opened_at_ms=5_000,
        closed_at_ms=8_000,
        net_pnl="-4",
    )
    open_position = _open_position(
        suffix="prior",
        side=PositionSide.SHORT,
        opened_at_ms=4_000,
    )

    result = closed_trade_entry_concurrency(
        (trade,),
        (open_position,),
    )

    buckets = result["by_concurrency_bucket"]
    assert isinstance(buckets, dict)
    assert buckets["1"]["trades"] == 1
    same_side = result["by_same_side_overlap"]
    assert isinstance(same_side, dict)
    assert same_side["1+"]["trades"] == 1
    observations = result["observations"]
    assert isinstance(observations, list)
    assert observations[0]["already_open_positions"] == 1
    assert observations[0]["same_side_already_open_positions"] == 1


def test_readiness_requires_both_solo_and_overlap_samples() -> None:
    trades = tuple(
        _trade(
            suffix=str(index),
            direction=Direction.LONG,
            opened_at_ms=index * 10_000,
            closed_at_ms=index * 10_000 + 1_000,
            net_pnl="1",
        )
        for index in range(30)
    )

    result = closed_trade_entry_concurrency(trades)
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["missing_closed_trades"] == 0
    assert readiness["missing_solo_trades"] == 0
    assert readiness["missing_overlap_trades"] == 10
    assert readiness["ready_for_review"] is False
