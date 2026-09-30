from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.execution import OrderSide, OrderType, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.delayed_entry_execution_shadow import DelayedEntryOutcome
from cocomelon.research.prospective_trade_quality import (
    CANDIDATE_ID,
    ProspectiveTradeQualityError,
    ProspectiveTradeQualityState,
    prospective_trade_quality_summary,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    entry = Decimal("100")
    exit_price = (
        entry + net if direction is Direction.LONG else entry - net
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 180_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"open-fill-{suffix}", f"exit-fill-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90") if direction is Direction.LONG else Decimal("110")
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
        holding_duration_ms=180_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _rank(
    trade: TradeJournalEntry,
    *,
    ordinal: int,
    age_ms: int = 1_000,
) -> ContinuousPaperOpeningRankEvidence:
    return ContinuousPaperOpeningRankEvidence(
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        opened_at_ms=trade.opened_at_ms,
        rank_observed_at_ms=trade.opened_at_ms - age_ms,
        rank_age_ms=age_ms,
        ordinal=ordinal,
        score=Decimal("0.7"),
        rank_pool_size=20,
        reason_codes=("fixture",),
    )


def _plan(trade: TradeJournalEntry) -> PaperOrderPlan:
    side = (
        OrderSide.BUY
        if trade.direction is Direction.LONG
        else OrderSide.SELL
    )
    return PaperOrderPlan(
        risk_decision_id=trade.risk_decision_id,
        strategy_decision_id=trade.strategy_decision_id,
        market=trade.market,
        side=side,
        requested_quantity=trade.filled_quantity,
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=trade.initial_stop,
        approved_notional_ceiling=Decimal("200"),
        created_at_ms=trade.opened_at_ms - 1_000,
        earliest_execution_ms=trade.opened_at_ms - 900,
        execution_config_version="paper-v1",
        instrument_metadata_received_at_ms=trade.opened_at_ms - 2_000,
        approved_risk_amount_ceiling=trade.initial_risk_amount,
        stop_distance_fraction=Decimal("0.1"),
        effective_loss_fraction=Decimal("0.101"),
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    price: str | None,
    quantity: str = "1",
) -> DelayedEntryOutcome:
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=Decimal(quantity),
        delayed_average_fill_price=(
            None if price is None else Decimal(price)
        ),
        delayed_fee=Decimal("0"),
        observation_lag_ms=500,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
    )


def test_trade_quality_is_side_symmetric_and_combines_rank_with_timing(
    tmp_path: Path,
) -> None:
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    long_admit = _trade(
        suffix="long-admit",
        direction=Direction.LONG,
        opened_at_ms=11_000,
        pnl="-5",
    )
    short_admit = _trade(
        suffix="short-admit",
        direction=Direction.SHORT,
        opened_at_ms=12_000,
        pnl="4",
    )
    rank_skip = _trade(
        suffix="rank-skip",
        direction=Direction.LONG,
        opened_at_ms=13_000,
        pnl="-3",
    )
    price_skip = _trade(
        suffix="price-skip",
        direction=Direction.SHORT,
        opened_at_ms=14_000,
        pnl="-2",
    )
    trades = (long_admit, short_admit, rank_skip, price_skip)
    for trade, ordinal in zip(trades, (5, 4, 12, 3), strict=True):
        ranks.record(_rank(trade, ordinal=ordinal))
    plans = {trade.opening_plan_id: _plan(trade) for trade in trades}
    outcomes = (
        _outcome(
            long_admit,
            source="full_visible_book_ioc",
            price="99",
        ),
        _outcome(
            short_admit,
            source="full_visible_book_ioc",
            price="101",
        ),
        _outcome(
            price_skip,
            source="full_visible_book_ioc",
            price="99",
        ),
    )

    result = prospective_trade_quality_summary(
        trades,
        ranks,
        outcomes,
        plans.get,
        ProspectiveTradeQualityState(started_at_ms=10_000),
    )

    assert result["prospective_closed_trades"] == 4
    assert result["evaluated_trades"] == 4
    assert result["admitted_trades"] == 2
    assert result["skipped_trades"] == 2
    assert result["rank_skips"] == 1
    assert result["worse_price_skips"] == 1
    assert result["actual_net_pnl"] == "-6"
    assert result["candidate_trade_contribution_pnl"] == "1"
    assert result["delta_trade_contribution_pnl"] == "7"

    by_direction = result["by_direction"]
    assert isinstance(by_direction, dict)
    assert by_direction["long"]["evaluated"] == 2
    assert by_direction["long"]["admitted"] == 1
    assert by_direction["short"]["evaluated"] == 2
    assert by_direction["short"]["admitted"] == 1


def test_rank_rejection_does_not_require_delayed_outcome(
    tmp_path: Path,
) -> None:
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trade = _trade(
        suffix="rank-only",
        direction=Direction.SHORT,
        opened_at_ms=11_000,
        pnl="-2",
    )
    ranks.record(_rank(trade, ordinal=11))

    result = prospective_trade_quality_summary(
        (trade,),
        ranks,
        (),
        lambda _plan_id: None,
        ProspectiveTradeQualityState(started_at_ms=10_000),
    )

    assert result["evaluated_trades"] == 1
    assert result["skipped_trades"] == 1
    assert result["rank_skips"] == 1
    assert result["missing_delayed_outcomes"] == 0
    assert result["missing_opening_plans"] == 0


def test_missing_rank_eligible_outcome_blocks_integrity(
    tmp_path: Path,
) -> None:
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "ranks")
    trade = _trade(
        suffix="missing-outcome",
        direction=Direction.LONG,
        opened_at_ms=11_000,
        pnl="-2",
    )
    ranks.record(_rank(trade, ordinal=5))

    result = prospective_trade_quality_summary(
        (trade,),
        ranks,
        (),
        lambda _plan_id: _plan(trade),
        ProspectiveTradeQualityState(started_at_ms=10_000),
    )

    assert result["evaluated_trades"] == 0
    assert result["missing_delayed_outcomes"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_trade_quality_state_round_trip_rejects_direction_rule_drift() -> None:
    state = ProspectiveTradeQualityState(started_at_ms=123)
    restored = ProspectiveTradeQualityState.from_payload(state.payload())

    assert restored == state
    assert restored.candidate_id == CANDIDATE_ID
    rule = restored.payload()["rule"]
    assert isinstance(rule, dict)
    assert rule["direction_policy"] == "same_rule_for_long_and_short"

    payload = state.payload()
    mutable_rule = payload["rule"]
    assert isinstance(mutable_rule, dict)
    mutable_rule["direction_policy"] = "short_only"

    with pytest.raises(
        ProspectiveTradeQualityError,
        match="frozen candidate",
    ):
        ProspectiveTradeQualityState.from_payload(payload)
