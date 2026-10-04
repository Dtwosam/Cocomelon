from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.profit_lock_activation_timeout import (
    profit_lock_activation_timeout_summary,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)


def _trade(
    suffix: str,
    *,
    market: str,
    direction: Direction,
    opened_at_ms: int,
    closed_after_ms: int,
    gross_pnl: str,
) -> TradeJournalEntry:
    gross = Decimal(gross_pnl)
    quantity = Decimal("1")
    entry = Decimal("100")
    exit_price = (
        entry + gross
        if direction is Direction.LONG
        else entry - gross
    )
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + closed_after_ms,
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
        entry_price=entry,
        exit_price=exit_price,
        filled_quantity=quantity,
        gross_realized_pnl=gross,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=gross,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_after_ms,
        mfe=None,
        mae=None,
        net_r=gross / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + gross,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    activation_after_ms: int | None,
) -> ProfitLockExecutionOutcome:
    activated = activation_after_ms is not None
    return ProfitLockExecutionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id="breakeven_after_0_5r",
        activated=activated,
        triggered=False,
        simulated_close_complete=False,
        activation_timestamp_ms=(
            None
            if activation_after_ms is None
            else trade.opened_at_ms + activation_after_ms
        ),
        trigger_timestamp_ms=None,
        completion_timestamp_ms=None,
        simulated_filled_quantity=Decimal("0"),
        simulated_average_exit_price=None,
        simulated_exit_fees=Decimal("0"),
        attempt_count=0,
        planning_rejection_count=0,
        no_fill_count=0,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=trade.net_pnl,
        candidate_net_r_estimate=trade.net_r,
        delta_net_pnl_estimate=Decimal("0"),
        delta_net_r_estimate=Decimal("0"),
        candidate_source="actual_close",
    )


def _state(
    outcomes: tuple[ProfitLockExecutionOutcome, ...],
) -> dict[str, object]:
    return {
        "schema_version": EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
        "outcomes": [outcome.payload() for outcome in outcomes],
    }


def _path(
    trade: TradeJournalEntry,
    *,
    marks: tuple[tuple[int, str], ...],
    gaps: tuple[tuple[int, int | None], ...] = (),
) -> dict[str, object]:
    return {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "entry_price": str(trade.entry_price),
        "filled_quantity": str(trade.filled_quantity),
        "marks": [
            {
                "available_at_ms": trade.opened_at_ms + offset_ms,
                "exchange_time_ms": trade.opened_at_ms + offset_ms,
                "event_key": f"{trade.trade_id}:{offset_ms}",
                "mark_px": mark_px,
            }
            for offset_ms, mark_px in marks
        ],
        "known_gap_intervals": [
            [started_ms, ended_ms]
            for started_ms, ended_ms in gaps
        ],
    }


def test_activation_timeout_intervenes_only_before_activation() -> None:
    opened = 1_000_000
    long_loser = _trade(
        "long-loser",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=opened,
        closed_after_ms=2 * 60 * 60 * 1_000,
        gross_pnl="-10",
    )
    short_loser = _trade(
        "short-loser",
        market="ETH",
        direction=Direction.SHORT,
        opened_at_ms=opened + 1_000,
        closed_after_ms=2 * 60 * 60 * 1_000,
        gross_pnl="-10",
    )
    activated = _trade(
        "activated",
        market="BTC",
        direction=Direction.LONG,
        opened_at_ms=opened + 2_000,
        closed_after_ms=2 * 60 * 60 * 1_000,
        gross_pnl="5",
    )

    offsets = (
        5 * 60 * 1_000,
        15 * 60 * 1_000,
        30 * 60 * 1_000,
        60 * 60 * 1_000,
    )
    result = profit_lock_activation_timeout_summary(
        (long_loser, short_loser, activated),
        _state(
            (
                _outcome(long_loser, activation_after_ms=None),
                _outcome(short_loser, activation_after_ms=None),
                _outcome(
                    activated,
                    activation_after_ms=4 * 60 * 1_000,
                ),
            )
        ),
        (
            _path(
                long_loser,
                marks=tuple(
                    (offset, str(Decimal("100") - Decimal(index)))
                    for index, offset in enumerate(offsets, start=1)
                ),
            ),
            _path(
                short_loser,
                marks=tuple(
                    (offset, str(Decimal("100") + Decimal(index)))
                    for index, offset in enumerate(offsets, start=1)
                ),
            ),
            _path(
                activated,
                marks=tuple((offset, "101") for offset in offsets),
            ),
        ),
    )

    fifteen = result["horizons"]["900000"]
    assert fifteen["evaluated_trades"] == 3
    assert fifteen["interventions"] == 2
    assert fifteen["interventions_by_direction"] == {
        "long": 1,
        "short": 1,
    }
    assert fifteen["actual_gross_pnl"] == "-15"
    assert fifteen["candidate_gross_pnl"] == "1"
    assert fifteen["delta_gross_pnl"] == "16"
    assert fifteen["delta_gross_r"] == "1.6"
    assert fifteen["delta_positive"] is True
    robustness = fifteen["robustness"]
    assert robustness["positive_after_removing_any_one_trade"] is True
    assert robustness["positive_after_removing_any_one_market"] is True

    rows = fifteen["rows"]
    activated_row = next(
        row for row in rows if row["trade_id"] == activated.trade_id
    )
    assert activated_row["status"] == "no_action"
    assert activated_row["reason"] == "activated_before_timeout"


def test_activation_timeout_fails_closed_on_gap_and_activation_race() -> None:
    opened = 2_000_000
    gapped = _trade(
        "gapped",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=opened,
        closed_after_ms=60 * 60 * 1_000,
        gross_pnl="-10",
    )
    raced = _trade(
        "raced",
        market="ETH",
        direction=Direction.LONG,
        opened_at_ms=opened + 1_000,
        closed_after_ms=60 * 60 * 1_000,
        gross_pnl="-10",
    )
    horizon = 5 * 60 * 1_000
    proxy_lag = 30_000

    result = profit_lock_activation_timeout_summary(
        (gapped, raced),
        _state(
            (
                _outcome(gapped, activation_after_ms=None),
                _outcome(
                    raced,
                    activation_after_ms=horizon + 10_000,
                ),
            )
        ),
        (
            _path(
                gapped,
                marks=((horizon + proxy_lag, "99"),),
                gaps=(
                    (
                        gapped.opened_at_ms + horizon,
                        gapped.opened_at_ms + horizon + 5_000,
                    ),
                ),
            ),
            _path(
                raced,
                marks=((horizon + proxy_lag, "99"),),
            ),
        ),
        horizons_ms=(horizon,),
    )

    summary = result["horizons"][str(horizon)]
    assert summary["evaluated_trades"] == 0
    assert summary["interventions"] == 0
    assert summary["exclusion_reason_counts"] == {
        "activation_during_proxy_lag": 1,
        "gap_overlaps_proxy_window": 1,
    }


def test_activation_timeout_keeps_early_closes_as_actual() -> None:
    trade = _trade(
        "early",
        market="SOL",
        direction=Direction.LONG,
        opened_at_ms=3_000_000,
        closed_after_ms=2 * 60 * 1_000,
        gross_pnl="-3",
    )
    result = profit_lock_activation_timeout_summary(
        (trade,),
        _state((_outcome(trade, activation_after_ms=None),)),
        (),
        horizons_ms=(5 * 60 * 1_000,),
    )

    summary = result["horizons"]["300000"]
    assert summary["evaluated_trades"] == 1
    assert summary["interventions"] == 0
    assert summary["candidate_gross_pnl"] == "-3"
    assert summary["delta_gross_pnl"] == "0"
    row = summary["rows"][0]
    assert row["reason"] == "actual_close_before_timeout"
