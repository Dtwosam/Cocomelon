from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.execution import (
    OrderSide,
    OrderType,
    PaperOrderPlan,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.risk import RiskLimits
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePath,
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_portfolio_capacity import (
    delayed_entry_portfolio_capacity_overlay,
)

MARKET = MarketId("", "SOL")
BACKGROUND = MarketId("", "BTC")


def _plan_for(
    *,
    suffix: str,
    market: MarketId,
    opened_at_ms: int,
    quantity: Decimal,
) -> PaperOrderPlan:
    return PaperOrderPlan(
        risk_decision_id=f"risk-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        market=market,
        side=OrderSide.BUY,
        requested_quantity=quantity,
        order_type=OrderType.MARKETABLE_IOC,
        reduce_only=False,
        execution_reference_price=Decimal("100"),
        max_slippage_bps=Decimal("25"),
        stop_price=Decimal("90"),
        approved_notional_ceiling=Decimal("1000"),
        created_at_ms=opened_at_ms - 1_000,
        earliest_execution_ms=opened_at_ms - 900,
        execution_config_version="paper-v1",
        instrument_metadata_received_at_ms=opened_at_ms - 2_000,
        approved_risk_amount_ceiling=Decimal("25"),
        stop_distance_fraction=Decimal("0.10"),
        effective_loss_fraction=Decimal("0.10"),
    )


def _trade(
    *,
    suffix: str,
    market: MarketId,
    opened_at_ms: int,
    closed_at_ms: int,
    quantity: str = "2.5",
    pnl: str = "0",
) -> TradeJournalEntry:
    qty = Decimal(quantity)
    net_pnl = Decimal(pnl)
    opening_plan = _plan_for(
        suffix=suffix,
        market=market,
        opened_at_ms=opened_at_ms,
        quantity=qty,
    )
    return TradeJournalEntry(
        market=market,
        direction=Direction.LONG,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=opening_plan.plan_id,
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-exit-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + net_pnl / qty,
        filled_quantity=qty,
        gross_realized_pnl=net_pnl,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net_pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=net_pnl / Decimal("25"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net_pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
) -> ContinuousPaperTradePath:
    return ContinuousPaperTradePath(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        opened_at_ms=trade.opened_at_ms,
        closed_at_ms=trade.closed_at_ms,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        initial_stop=trade.initial_stop,
        initial_risk_amount=trade.initial_risk_amount,
        filled_quantity=trade.filled_quantity,
        venue_max_leverage=Decimal("20"),
        excursion_complete=True,
        health_refs=trade.health_refs,
        marks=tuple(
            ContinuousPaperTradePathMark(
                available_at_ms=timestamp_ms,
                exchange_time_ms=timestamp_ms,
                event_key=f"{trade.trade_id}-{timestamp_ms}",
                mark_px=Decimal(mark_px),
            )
            for timestamp_ms, mark_px in marks
        ),
        known_gap_intervals=(),
    )


def _plan(trade: TradeJournalEntry) -> PaperOrderPlan:
    suffix = trade.risk_decision_id.removeprefix("risk-")
    return _plan_for(
        suffix=suffix,
        market=trade.market,
        opened_at_ms=trade.opened_at_ms,
        quantity=trade.filled_quantity,
    )


def _plan_loader(
    *trades: TradeJournalEntry,
):
    plans = {
        plan.plan_id: plan
        for plan in (_plan(trade) for trade in trades)
    }
    return plans.get


def _outcome(
    trade: TradeJournalEntry,
    *,
    price: str = "100",
) -> DelayedEntryOutcome:
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source="full_visible_book_ioc",
        delayed_filled_quantity=trade.filled_quantity,
        delayed_average_fill_price=Decimal(price),
        delayed_fee=Decimal("0"),
        observation_lag_ms=0,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=None,
        capacity_cause=None,
    )


def _stores(tmp_path: Path):
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    return journal, paths


def test_capacity_overlay_detects_candidate_bucket_violation(
    tmp_path: Path,
) -> None:
    journal, paths = _stores(tmp_path)
    try:
        background = _trade(
            suffix="background",
            market=BACKGROUND,
            opened_at_ms=90_000,
            closed_at_ms=300_000,
        )
        candidate = _trade(
            suffix="candidate",
            market=MARKET,
            opened_at_ms=100_000,
            closed_at_ms=300_000,
        )
        journal.record_trade(background)
        journal.record_trade(candidate)
        paths.record(
            _path(
                background,
                (
                    (150_000, "96"),
                    (250_000, "100"),
                ),
            )
        )
        paths.record(
            _path(
                candidate,
                ((200_000, "100"),),
            )
        )
        result = delayed_entry_portfolio_capacity_overlay(
            journal,
            (_outcome(candidate),),
            paths,
            _plan_loader(background, candidate),
            limits=RiskLimits(),
            paper_max_gross_leverage=Decimal("3"),
        )
    finally:
        journal.close()

    actual = result["actual"]
    delayed = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(delayed, dict)
    assert actual["capacity_violations"] == 0
    assert delayed["capacity_violations"] == 1
    assert delayed["correlation_bucket_risk_violations"] == 1
    assert delayed["aggregate_risk_violations"] == 0
    assert delayed["gross_leverage_violations"] == 0
    assert delayed["delayed_opening_violations"] == 1
    assert delayed["background_opening_violations"] == 0
    assert Decimal(
        str(delayed["min_correlation_bucket_risk_headroom"])
    ) < Decimal("0")
    actual_admission = result["actual_admission"]
    candidate_admission = result["candidate_admission"]
    assert isinstance(actual_admission, dict)
    assert isinstance(candidate_admission, dict)
    assert actual_admission["rejected_openings"] == 0
    assert candidate_admission["rejected_openings"] == 1
    assert candidate_admission["delayed_candidate_rejected"] == 1
    assert candidate_admission["observed_schedule_admitted"] == 1
    assert result["changed_admissions_modeled"] is True


def test_admission_shadow_can_reject_later_background_opening(
    tmp_path: Path,
) -> None:
    journal, paths = _stores(tmp_path)
    try:
        candidate = _trade(
            suffix="candidate",
            market=MARKET,
            opened_at_ms=100_000,
            closed_at_ms=300_000,
        )
        later_background = _trade(
            suffix="later-background",
            market=BACKGROUND,
            opened_at_ms=170_000,
            closed_at_ms=300_000,
            pnl="-10",
        )
        journal.record_trade(candidate)
        journal.record_trade(later_background)
        paths.record(
            _path(
                candidate,
                ((200_000, "100"),),
            )
        )
        paths.record(
            _path(
                later_background,
                ((220_000, "100"),),
            )
        )
        result = delayed_entry_portfolio_capacity_overlay(
            journal,
            (_outcome(candidate, price="101"),),
            paths,
            _plan_loader(candidate, later_background),
            limits=RiskLimits(),
            paper_max_gross_leverage=Decimal("3"),
        )
    finally:
        journal.close()

    actual_admission = result["actual_admission"]
    candidate_admission = result["candidate_admission"]
    assert isinstance(actual_admission, dict)
    assert isinstance(candidate_admission, dict)
    assert actual_admission["rejected_openings"] == 0
    assert candidate_admission["delayed_candidate_admitted"] == 1
    assert candidate_admission["observed_schedule_rejected"] == 1
    assert candidate_admission["rejected_openings"] == 1
    assert candidate_admission[
        "correlation_bucket_risk_rejections"
    ] == 1
    assert candidate_admission["max_concurrent_positions"] == 1
    assert Decimal(
        str(result["fixed_candidate_final_realized_contribution"])
    ) == Decimal("-12.5")
    assert Decimal(
        str(result["admitted_candidate_final_realized_contribution"])
    ) == Decimal("-2.5")
    assert Decimal(
        str(result["admission_delta_vs_fixed_schedule"])
    ) == Decimal("10")


def test_capacity_overlay_detects_candidate_gross_leverage_violation(
    tmp_path: Path,
) -> None:
    journal, paths = _stores(tmp_path)
    try:
        background = _trade(
            suffix="background",
            market=BACKGROUND,
            opened_at_ms=90_000,
            closed_at_ms=300_000,
        )
        candidate = _trade(
            suffix="candidate",
            market=MARKET,
            opened_at_ms=100_000,
            closed_at_ms=300_000,
        )
        journal.record_trade(background)
        journal.record_trade(candidate)
        paths.record(
            _path(
                background,
                (
                    (150_000, "96"),
                    (250_000, "100"),
                ),
            )
        )
        paths.record(
            _path(
                candidate,
                ((200_000, "105"),),
            )
        )
        limits = RiskLimits(
            max_open_risk=Decimal("1"),
            correlation_bucket_risk_limit=Decimal("1"),
            max_gross_leverage=Decimal("0.05"),
        )

        result = delayed_entry_portfolio_capacity_overlay(
            journal,
            (_outcome(candidate, price="105"),),
            paths,
            _plan_loader(background, candidate),
            limits=limits,
            paper_max_gross_leverage=Decimal("3"),
        )
    finally:
        journal.close()

    actual = result["actual"]
    delayed = result["candidate"]
    assert isinstance(actual, dict)
    assert isinstance(delayed, dict)
    assert actual["capacity_violations"] == 0
    assert delayed["capacity_violations"] == 1
    assert delayed["gross_leverage_violations"] == 1
    assert delayed["aggregate_risk_violations"] == 0
    assert delayed["correlation_bucket_risk_violations"] == 0
    assert Decimal(
        str(delayed["min_gross_notional_headroom"])
    ) < Decimal("0")


def test_capacity_overlay_no_fill_removes_candidate_position(
    tmp_path: Path,
) -> None:
    journal, paths = _stores(tmp_path)
    try:
        candidate = _trade(
            suffix="candidate",
            market=MARKET,
            opened_at_ms=100_000,
            closed_at_ms=300_000,
        )
        journal.record_trade(candidate)
        paths.record(
            _path(candidate, ((200_000, "100"),))
        )
        no_fill = DelayedEntryOutcome(
            trade_id=candidate.trade_id,
            opening_plan_id=candidate.opening_plan_id,
            market=candidate.market.canonical,
            direction=candidate.direction.value,
            source="no_fill",
            delayed_filled_quantity=Decimal("0"),
            delayed_average_fill_price=None,
            delayed_fee=Decimal("0"),
            observation_lag_ms=0,
            signed_price_improvement_bps=None,
            gross_r_improvement=None,
            attempt_reason=None,
            capacity_cause=None,
        )

        result = delayed_entry_portfolio_capacity_overlay(
            journal,
            (no_fill,),
            paths,
            _plan_loader(candidate),
            limits=RiskLimits(),
            paper_max_gross_leverage=Decimal("3"),
        )
    finally:
        journal.close()

    candidate_state = result["candidate"]
    assert isinstance(candidate_state, dict)
    assert result["candidate_no_fill_trades"] == 1
    assert result["candidate_filled_positions"] == 0
    assert candidate_state["opening_checks"] == 0
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_actual_admission_uses_filled_risk_not_approved_ceiling(
    tmp_path: Path,
) -> None:
    journal, paths = _stores(tmp_path)
    try:
        first = _trade(
            suffix="partial-one",
            market=MarketId("", "ONE"),
            opened_at_ms=100_000,
            closed_at_ms=400_000,
            quantity="1",
        )
        second = _trade(
            suffix="partial-two",
            market=MarketId("", "TWO"),
            opened_at_ms=110_000,
            closed_at_ms=400_000,
            quantity="1",
        )
        third = _trade(
            suffix="partial-three",
            market=MarketId("", "THREE"),
            opened_at_ms=120_000,
            closed_at_ms=400_000,
            quantity="1",
        )
        for trade in (first, second, third):
            journal.record_trade(trade)
            paths.record(
                _path(
                    trade,
                    ((200_000, "100"),),
                )
            )

        result = delayed_entry_portfolio_capacity_overlay(
            journal,
            (_outcome(first),),
            paths,
            _plan_loader(first, second, third),
            limits=RiskLimits(),
            paper_max_gross_leverage=Decimal("3"),
        )
    finally:
        journal.close()

    actual = result["actual"]
    actual_admission = result["actual_admission"]
    assert isinstance(actual, dict)
    assert isinstance(actual_admission, dict)
    assert actual["opening_checks"] == 3
    assert actual["capacity_violations"] == 0
    assert actual_admission["admitted_openings"] == 3
    assert actual_admission["rejected_openings"] == 0
    assert result["observed_planned_risk_basis"] == (
        "actual_fill_notional_stop_distance_plus_plan_cost_buffer"
    )



def test_capacity_overlay_detects_available_margin_violation(
    tmp_path: Path,
) -> None:
    journal, paths = _stores(tmp_path)
    try:
        candidate = _trade(
            suffix="margin-candidate",
            market=MARKET,
            opened_at_ms=100_000,
            closed_at_ms=300_000,
        )
        journal.record_trade(candidate)
        paths.record(
            _path(candidate, ((200_000, "100"),))
        )
        limits = RiskLimits(
            max_open_risk=Decimal("1"),
            correlation_bucket_risk_limit=Decimal("1"),
            max_gross_leverage=Decimal("3"),
            max_available_margin_fraction=Decimal("0.0085"),
        )

        result = delayed_entry_portfolio_capacity_overlay(
            journal,
            (_outcome(candidate, price="105"),),
            paths,
            _plan_loader(candidate),
            limits=limits,
            paper_max_gross_leverage=Decimal("3"),
        )
    finally:
        journal.close()

    actual = result["actual"]
    delayed = result["candidate"]
    admission = result["candidate_admission"]
    assert isinstance(actual, dict)
    assert isinstance(delayed, dict)
    assert isinstance(admission, dict)
    assert actual["capacity_violations"] == 0
    assert actual["margin_capacity_violations"] == 0
    assert delayed["capacity_violations"] == 1
    assert delayed["margin_capacity_violations"] == 1
    assert delayed["gross_leverage_violations"] == 0
    assert Decimal(
        str(delayed["min_margin_notional_headroom"])
    ) < Decimal("0")
    assert admission["rejected_openings"] == 1
    assert admission["margin_capacity_rejections"] == 1
    assert result["available_margin_capacity_modeled"] is True
