from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.research.profit_lock_counterfactual import ProfitLockRule
from cocomelon.research.profit_lock_execution_shadow import (
    ProfitLockExecutionShadow,
    ProfitLockExecutionShadowError,
)

MARKET = MarketId("", "SOL")
RULE = ProfitLockRule(
    rule_id="breakeven_after_0_5r",
    activate_at_r=Decimal("0.5"),
    lock_at_r=Decimal("0"),
)


def _config() -> PaperExecutionConfig:
    return PaperExecutionConfig()


def _position(
    *,
    quantity: str = "1",
    opened_at_ms: int = 1_000,
    planned_risk: str = "10",
    side: PositionSide = PositionSide.LONG,
) -> PaperPosition:
    return PaperPosition(
        market=MARKET,
        side=side,
        quantity=Decimal(quantity),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("90") if side is PositionSide.LONG else Decimal("110"),
        opening_plan_id="opening-plan-1",
        opened_at_ms=opened_at_ms,
        updated_at_ms=opened_at_ms,
        initial_risk_decision_id="risk-1",
        correlation_bucket="crypto_beta",
        planned_risk=Decimal(planned_risk),
        venue_max_leverage=Decimal("20"),
        latest_mark=Decimal("100"),
    )


def _instrument() -> InstrumentExecutionSpec:
    return InstrumentExecutionSpec(
        market=MARKET,
        sz_decimals=2,
        venue_max_leverage=Decimal("20"),
        minimum_order_notional=Decimal("10"),
        metadata_received_at_ms=900,
        metadata_source="hyperliquid-mainnet-meta",
    )


def _mark(px: str, receive_ms: int) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.ACTIVE_ASSET_CTX,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"ctx:{receive_ms}:{px}",
        payload={
            "mark_px": Decimal(px),
            "mid_px": Decimal(px),
            "oracle_px": Decimal(px),
            "funding": Decimal("0"),
            "open_interest": Decimal("1000"),
        },
    )


def _book(
    *,
    receive_ms: int,
    bid: str,
    ask: str,
    bid_size: str = "10",
    ask_size: str = "10",
) -> StreamEvent:
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MARKET,
        exchange_time_ms=receive_ms - 1,
        receive_time=datetime.fromtimestamp(receive_ms / 1000, tz=UTC),
        schema_version=1,
        source="hyperliquid-mainnet-ws",
        event_key=f"book:{receive_ms}:{bid}:{ask}:{bid_size}:{ask_size}",
        payload={
            "bids": (
                {
                    "px": Decimal(bid),
                    "sz": Decimal(bid_size),
                    "n": 1,
                },
            ),
            "asks": (
                {
                    "px": Decimal(ask),
                    "sz": Decimal(ask_size),
                    "n": 1,
                },
            ),
        },
    )


def _trade(
    position: PaperPosition,
    *,
    closed_at_ms: int = 5_000,
    exit_price: str = "90",
) -> TradeJournalEntry:
    exit_px = Decimal(exit_price)
    quantity = position.quantity
    gross = (
        (exit_px - position.average_entry_price) * quantity
        if position.side is PositionSide.LONG
        else (position.average_entry_price - exit_px) * quantity
    )
    entry_fee = Decimal("0.045") * quantity
    exit_fee = Decimal("0.04") * quantity
    net = gross - entry_fee - exit_fee
    direction = (
        Direction.LONG
        if position.side is PositionSide.LONG
        else Direction.SHORT
    )
    return TradeJournalEntry(
        market=position.market,
        direction=direction,
        opened_at_ms=position.opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id=position.initial_risk_decision_id,
        opening_plan_id=position.opening_plan_id,
        opening_attempt_id="opening-attempt-1",
        exit_plan_ids=("exit-plan-actual",),
        exit_attempt_ids=("exit-attempt-actual",),
        fill_ids=("fill-open", "fill-close"),
        position_action_ids=("action-close",),
        funding_event_ids=(),
        initial_stop=position.stop_price,
        initial_risk_amount=position.planned_risk,
        entry_price=position.average_entry_price,
        exit_price=exit_px,
        filled_quantity=quantity,
        gross_realized_pnl=gross,
        entry_fees=entry_fee,
        exit_fees=exit_fee,
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - position.opened_at_ms,
        mfe=None,
        mae=None,
        net_r=net / position.planned_risk,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _shadow(*, started_at_ms: int = 500) -> ProfitLockExecutionShadow:
    return ProfitLockExecutionShadow(
        _config(),
        started_at_ms=started_at_ms,
        rules=(RULE,),
    )


def test_open_rule_state_payloads_are_lightweight_and_current() -> None:
    position = _position()
    shadow = _shadow()

    shadow.observe_mark(
        (position,),
        _mark("105", 1_500),
        now_ms=1_500,
    )

    rows = shadow.open_rule_state_payloads(RULE.rule_id)

    assert len(rows) == 1
    row = rows[0]
    assert row["opening_plan_id"] == position.opening_plan_id
    assert row["market"] == MARKET.canonical
    assert row["side"] == "long"
    assert row["entry_price"] == "100"
    assert row["opened_at_ms"] == 1_000
    assert row["eligible"] is True
    rule = row["rule"]
    assert isinstance(rule, dict)
    assert rule["rule_id"] == RULE.rule_id
    assert rule["activated_at_ms"] == 1_500
    assert rule["triggered_at_ms"] is None

    with pytest.raises(ValueError, match="unknown profit-lock rule"):
        shadow.open_rule_state_payloads("missing-rule")


def test_execution_shadow_waits_for_latency_then_uses_visible_book() -> None:
    position = _position()
    shadow = _shadow()

    shadow.observe_mark((position,), _mark("105", 1_500), now_ms=1_500)
    shadow.observe_mark((position,), _mark("99", 2_000), now_ms=2_000)

    shadow.observe_book(
        (position,),
        _instrument(),
        _book(receive_ms=2_100, bid="98.9", ask="99.1"),
        reference_price=Decimal("99"),
        now_ms=2_100,
    )
    before = shadow.summary_payload()["rules"][0]
    assert before["triggered_trades"] == 0

    shadow.observe_book(
        (position,),
        _instrument(),
        _book(receive_ms=2_300, bid="98.9", ask="99.1"),
        reference_price=Decimal("99"),
        now_ms=2_300,
    )
    shadow.record_closed_trade(_trade(position))

    summary = shadow.summary_payload()
    rule = summary["rules"][0]
    assert rule["closed_eligible_trades"] == 1
    assert rule["activated_trades"] == 1
    assert rule["triggered_trades"] == 1
    assert rule["simulated_full_closes"] == 1
    assert rule["triggered_incomplete"] == 0
    assert Decimal(str(rule["candidate_net_pnl_estimate"])) > Decimal("-2")
    assert Decimal(str(rule["delta_net_pnl_estimate"])) > Decimal("8")


def test_execution_shadow_partial_fill_survives_restart_and_completes() -> None:
    position = _position(quantity="2", planned_risk="20")
    shadow = _shadow()

    shadow.observe_mark((position,), _mark("105", 1_500), now_ms=1_500)
    shadow.observe_mark((position,), _mark("99", 2_000), now_ms=2_000)
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(
            receive_ms=2_300,
            bid="98.9",
            ask="99.1",
            bid_size="1",
        ),
        reference_price=Decimal("99"),
        now_ms=2_300,
    )

    state = shadow.state_payload()
    restored = _shadow(started_at_ms=99_999)
    restored.restore_state(state)
    assert restored.summary_payload()["state_restored"] is True

    restored.observe_book(
        (position,),
        _instrument(),
        _book(
            receive_ms=2_600,
            bid="98.8",
            ask="99.0",
            bid_size="1",
        ),
        reference_price=Decimal("98.9"),
        now_ms=2_600,
    )
    restored.record_closed_trade(_trade(position))

    rule = restored.summary_payload()["rules"][0]
    assert rule["simulated_full_closes"] == 1
    assert rule["triggered_incomplete"] == 0
    outcome = restored.state_payload()["outcomes"][0]
    assert Decimal(str(outcome["simulated_filled_quantity"])) == Decimal("2")
    assert Decimal(str(outcome["simulated_exit_fees"])) > Decimal("0")


def test_execution_shadow_is_direction_symmetric_for_short() -> None:
    position = _position(side=PositionSide.SHORT)
    shadow = _shadow()

    shadow.observe_mark((position,), _mark("95", 1_500), now_ms=1_500)
    shadow.observe_mark((position,), _mark("101", 2_000), now_ms=2_000)
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(receive_ms=2_300, bid="100.9", ask="101.1"),
        reference_price=Decimal("101"),
        now_ms=2_300,
    )
    shadow.record_closed_trade(
        _trade(position, exit_price="110")
    )

    rule = shadow.summary_payload()["rules"][0]
    assert rule["simulated_full_closes"] == 1
    assert Decimal(str(rule["delta_net_pnl_estimate"])) > Decimal("8")


def test_execution_shadow_keeps_actual_close_when_rule_never_triggers() -> None:
    position = _position()
    shadow = _shadow()

    shadow.observe_mark((position,), _mark("102", 1_500), now_ms=1_500)
    trade = _trade(position)
    shadow.record_closed_trade(trade)

    outcome = shadow.state_payload()["outcomes"][0]
    assert outcome["candidate_source"] == "actual_close"
    assert outcome["candidate_net_pnl_estimate"] == str(trade.net_pnl)
    assert outcome["delta_net_pnl_estimate"] == "0"


def test_execution_shadow_marks_triggered_unfilled_close_incomplete() -> None:
    position = _position()
    shadow = _shadow()

    shadow.observe_mark((position,), _mark("105", 1_500), now_ms=1_500)
    shadow.observe_mark((position,), _mark("99", 2_000), now_ms=2_000)
    shadow.record_closed_trade(_trade(position))

    outcome = shadow.state_payload()["outcomes"][0]
    assert outcome["candidate_source"] == "triggered_incomplete"
    assert outcome["candidate_net_pnl_estimate"] is None
    assert outcome["delta_net_pnl_estimate"] is None


def test_execution_shadow_excludes_positions_open_before_observer() -> None:
    position = _position(opened_at_ms=400)
    shadow = _shadow(started_at_ms=500)

    shadow.observe_mark((position,), _mark("105", 1_500), now_ms=1_500)
    shadow.record_closed_trade(_trade(position))

    summary = shadow.summary_payload()
    assert summary["closed_outcome_count"] == 0
    assert summary["excluded_closed_trades"] == 1


def test_execution_shadow_rejects_config_mismatch_on_restore() -> None:
    shadow = _shadow()
    state = shadow.state_payload()
    different = ProfitLockExecutionShadow(
        PaperExecutionConfig(latency_ms=500),
        started_at_ms=500,
        rules=(RULE,),
    )

    with pytest.raises(
        ProfitLockExecutionShadowError,
        match="config mismatch",
    ):
        different.restore_state(state)


def test_execution_shadow_contains_closed_trade_lineage_mismatch() -> None:
    tracked = _position()
    shadow = _shadow()
    shadow.observe_mark(
        (tracked,),
        _mark("102", 1_500),
        now_ms=1_500,
    )
    mismatched = _position(quantity="2", planned_risk="20")

    shadow.record_closed_trade(_trade(mismatched))

    summary = shadow.summary_payload()
    assert summary["closed_outcome_count"] == 0
    assert summary["lineage_mismatch_closed_trades"] == 1


def test_execution_shadow_reconcile_tracks_current_eligible_position() -> None:
    position = _position(opened_at_ms=1_000)
    shadow = _shadow(started_at_ms=500)

    shadow.reconcile_open_positions((position,))

    summary = shadow.summary_payload()
    assert summary["eligible_open_positions"] == 1
    assert summary["excluded_pre_observer_open_positions"] == 0


def test_execution_shadow_reconcile_tracks_pre_observer_position_as_excluded() -> None:
    position = _position(opened_at_ms=400)
    shadow = _shadow(started_at_ms=500)

    shadow.reconcile_open_positions((position,))

    summary = shadow.summary_payload()
    assert summary["eligible_open_positions"] == 0
    assert summary["excluded_pre_observer_open_positions"] == 1


def test_execution_shadow_reconciles_orphaned_restored_position() -> None:
    position = _position()
    shadow = _shadow()
    shadow.observe_mark(
        (position,),
        _mark("102", 1_500),
        now_ms=1_500,
    )

    restored = _shadow(started_at_ms=99_999)
    restored.restore_state(shadow.state_payload())
    restored.reconcile_open_positions(())

    summary = restored.summary_payload()
    assert summary["eligible_open_positions"] == 0
    assert summary["orphaned_restored_positions"] == 1
    round_trip = _shadow(started_at_ms=99_999)
    round_trip.restore_state(restored.state_payload())
    assert (
        round_trip.summary_payload()["orphaned_restored_positions"]
        == 1
    )


PROFIT_TARGET_RULE = ProfitLockRule(
    rule_id="profit_target_at_1r",
    activate_at_r=Decimal("1"),
    lock_at_r=Decimal("1"),
    exit_on_activation=True,
)


@pytest.mark.parametrize(
    ("side", "target_px", "bid", "ask", "reference", "actual_exit"),
    [
        (PositionSide.LONG, "110", "109.7", "109.9", "109.8", "90"),
        (PositionSide.SHORT, "90", "90.1", "90.3", "90.2", "110"),
    ],
)
def test_take_profit_at_1r_triggers_immediately_but_needs_real_book_fill(
    side: PositionSide,
    target_px: str,
    bid: str,
    ask: str,
    reference: str,
    actual_exit: str,
) -> None:
    position = _position(side=side)
    shadow = ProfitLockExecutionShadow(
        _config(),
        started_at_ms=500,
        rules=(PROFIT_TARGET_RULE,),
    )
    shadow.observe_mark(
        (position,), _mark(target_px, 1_500), now_ms=1_500
    )
    rule_state = shadow.open_rule_state_payloads(
        PROFIT_TARGET_RULE.rule_id
    )[0]["rule"]
    assert rule_state["activated_at_ms"] == 1_500
    assert rule_state["triggered_at_ms"] == 1_500
    assert rule_state["filled_quantity"] == "0"

    shadow.observe_book(
        (position,),
        _instrument(),
        _book(receive_ms=2_500, bid=bid, ask=ask),
        reference_price=Decimal(reference),
        now_ms=2_500,
    )
    shadow.record_closed_trade(
        _trade(position, exit_price=actual_exit)
    )
    outcome = shadow.state_payload()["outcomes"][0]
    assert outcome["candidate_source"] == "visible_book_ioc"
    assert outcome["simulated_close_complete"] is True
    assert Decimal(outcome["candidate_net_pnl_estimate"]) > Decimal("9")
    assert Decimal(outcome["delta_net_pnl_estimate"]) > Decimal("19")
    assert Decimal(outcome["simulated_exit_fees"]) > 0


def test_take_profit_rule_does_not_award_mark_only_wins() -> None:
    position = _position()
    shadow = ProfitLockExecutionShadow(
        _config(),
        started_at_ms=500,
        rules=(PROFIT_TARGET_RULE,),
    )
    shadow.observe_mark(
        (position,), _mark("110", 1_500), now_ms=1_500
    )
    shadow.record_closed_trade(_trade(position))
    outcome = shadow.state_payload()["outcomes"][0]
    assert outcome["triggered"] is True
    assert outcome["candidate_source"] == "triggered_incomplete"
    assert outcome["candidate_net_pnl_estimate"] is None
    assert outcome["delta_net_pnl_estimate"] is None


def test_take_profit_shadow_is_new_frozen_cohort_and_restores_exact_rule() -> None:
    position = _position()
    old = _shadow()
    old.observe_mark(
        (position,), _mark("105", 1_500), now_ms=1_500
    )
    old_state = old.state_payload()
    assert old_state["rules"] == [{
        "rule_id": RULE.rule_id,
        "activate_at_r": "0.5",
        "lock_at_r": "0",
    }]

    target = ProfitLockExecutionShadow(
        _config(),
        started_at_ms=1_000,
        rules=(PROFIT_TARGET_RULE,),
    )
    target.observe_mark(
        (position,), _mark("109", 1_500), now_ms=1_500
    )
    assert target.open_rule_state_payloads(
        PROFIT_TARGET_RULE.rule_id
    )[0]["rule"]["triggered_at_ms"] is None
    state = target.state_payload()
    assert state["rules"] == [{
        "rule_id": "profit_target_at_1r",
        "activate_at_r": "1",
        "lock_at_r": "1",
        "exit_on_activation": "true",
    }]

    restored = ProfitLockExecutionShadow(
        _config(),
        started_at_ms=99_999,
        rules=(PROFIT_TARGET_RULE,),
    )
    restored.restore_state(state)
    restored.observe_mark(
        (position,), _mark("111", 2_000), now_ms=2_000
    )
    assert restored.open_rule_state_payloads(
        PROFIT_TARGET_RULE.rule_id
    )[0]["rule"]["triggered_at_ms"] == 2_000
    with pytest.raises(
        ProfitLockExecutionShadowError, match="rule mismatch"
    ):
        old.restore_state(restored.state_payload())


@pytest.mark.parametrize(
    ("side", "mark_px", "bid", "ask", "actual_exit"),
    [
        (PositionSide.LONG, "115", "114.9", "115.1", "90"),
        (PositionSide.SHORT, "85", "84.9", "85.1", "110"),
    ],
)
def test_one_half_r_profit_target_requires_fresh_book_execution(
    side: PositionSide,
    mark_px: str,
    bid: str,
    ask: str,
    actual_exit: str,
) -> None:
    rule = ProfitLockRule(
        rule_id="profit_target_at_1_5r",
        activate_at_r=Decimal("1.5"),
        lock_at_r=Decimal("1.5"),
        exit_on_activation=True,
    )
    position = _position(side=side)
    shadow = ProfitLockExecutionShadow(
        _config(),
        started_at_ms=500,
        rules=(rule,),
    )
    shadow.observe_mark(
        (position,),
        _mark(mark_px, 1500),
        now_ms=1500,
    )
    rule_before_fill = shadow.open_rule_state_payloads(
        rule.rule_id
    )[0]["rule"]
    assert rule_before_fill["activated_at_ms"] == 1500
    assert rule_before_fill["triggered_at_ms"] == 1500
    assert rule_before_fill["filled_quantity"] == "0"
    shadow.observe_book(
        (position,),
        _instrument(),
        _book(receive_ms=2_500, bid=bid, ask=ask),
        reference_price=Decimal(mark_px),
        now_ms=2500,
    )
    shadow.record_closed_trade(
        _trade(position, exit_price=actual_exit)
    )
    outcome = shadow.state_payload()["outcomes"][0]
    assert outcome["candidate_source"] == "visible_book_ioc"
    assert outcome["simulated_close_complete"] is True
    assert Decimal(outcome["simulated_exit_fees"]) > 0
    assert Decimal(outcome["candidate_net_pnl_estimate"]) > 14
    assert Decimal(outcome["delta_net_pnl_estimate"]) > 24


def test_one_half_r_shadow_refuses_older_precommitted_one_r_rule_state() -> None:
    old_target = ProfitLockExecutionShadow(
        _config(),
        started_at_ms=500,
        rules=(PROFIT_TARGET_RULE,),
    )
    new_rule = ProfitLockRule(
        rule_id="profit_target_at_1_5r",
        activate_at_r=Decimal("1.5"),
        lock_at_r=Decimal("1.5"),
        exit_on_activation=True,
    )
    new_target = ProfitLockExecutionShadow(
        _config(),
        started_at_ms=500,
        rules=(new_rule,),
    )
    assert new_target.state_payload()["rules"] == [{
        "rule_id": "profit_target_at_1_5r",
        "activate_at_r": "1.5",
        "lock_at_r": "1.5",
        "exit_on_activation": "true",
    }]
    with pytest.raises(
        ProfitLockExecutionShadowError,
        match="rule mismatch",
    ):
        old_target.restore_state(new_target.state_payload())
    with pytest.raises(
        ProfitLockExecutionShadowError,
        match="rule mismatch",
    ):
        new_target.restore_state(old_target.state_payload())


TRAILING_PROFIT_RULE = ProfitLockRule(
    rule_id="trail_peak_after_1r_by_0_5r",
    activate_at_r=Decimal("1"),
    lock_at_r=Decimal("0.5"),
    trail_by_r=Decimal("0.5"),
)


@pytest.mark.parametrize(
    ("side", "first", "peak", "pullback", "trigger", "bid", "ask", "actual"),
    [
        (PositionSide.LONG, "110", "120", "117", "114", "113.9", "114.1", "90"),
        (PositionSide.SHORT, "90", "80", "83", "86", "85.9", "86.1", "110"),
    ],
)
def test_high_water_trailing_protects_profit_without_capping_initial_winner(
    side: PositionSide,
    first: str,
    peak: str,
    pullback: str,
    trigger: str,
    bid: str,
    ask: str,
    actual: str,
) -> None:
    position = _position(side=side)
    shadow = ProfitLockExecutionShadow(
        _config(), started_at_ms=500, rules=(TRAILING_PROFIT_RULE,)
    )
    shadow.observe_mark((position,), _mark(first, 1_500), now_ms=1_500)
    state = shadow.open_rule_state_payloads(
        TRAILING_PROFIT_RULE.rule_id
    )[0]["rule"]
    assert state["activated_at_ms"] == 1_500
    assert state["triggered_at_ms"] is None
    assert state["peak_gross_r"] == "1"

    shadow.observe_mark((position,), _mark(peak, 1_700), now_ms=1_700)
    shadow.observe_mark(
        (position,), _mark(pullback, 1_800), now_ms=1_800
    )
    state = shadow.open_rule_state_payloads(
        TRAILING_PROFIT_RULE.rule_id
    )[0]["rule"]
    assert state["peak_gross_r"] == "2"
    assert state["triggered_at_ms"] is None

    shadow.observe_mark(
        (position,), _mark(trigger, 1_900), now_ms=1_900
    )
    state = shadow.open_rule_state_payloads(
        TRAILING_PROFIT_RULE.rule_id
    )[0]["rule"]
    assert state["peak_gross_r"] == "2"
    assert state["triggered_at_ms"] == 1_900
    assert state["filled_quantity"] == "0"

    shadow.observe_book(
        (position,),
        _instrument(),
        _book(receive_ms=2_700, bid=bid, ask=ask),
        reference_price=Decimal(trigger),
        now_ms=2_700,
    )
    shadow.record_closed_trade(_trade(position, exit_price=actual))
    outcome = shadow.state_payload()["outcomes"][0]
    assert outcome["candidate_source"] == "visible_book_ioc"
    assert outcome["simulated_close_complete"] is True
    assert Decimal(outcome["candidate_net_pnl_estimate"]) > Decimal("13")
    assert Decimal(outcome["simulated_exit_fees"]) > 0


def test_trailing_rule_has_no_lookahead_and_no_mark_only_profit() -> None:
    position = _position()
    shadow = ProfitLockExecutionShadow(
        _config(), started_at_ms=500, rules=(TRAILING_PROFIT_RULE,)
    )
    shadow.observe_mark(
        (position,), _mark("120", 1_500), now_ms=1_500
    )
    shadow.observe_mark(
        (position,), _mark("114", 2_000), now_ms=2_000
    )
    shadow.record_closed_trade(_trade(position))
    outcome = shadow.state_payload()["outcomes"][0]
    assert outcome["triggered"] is True
    assert outcome["candidate_source"] == "triggered_incomplete"
    assert outcome["candidate_net_pnl_estimate"] is None


def test_trailing_peak_survives_exact_restart_and_rejects_corruption() -> None:
    position = _position()
    trailing = ProfitLockExecutionShadow(
        _config(), started_at_ms=500, rules=(TRAILING_PROFIT_RULE,)
    )
    trailing.observe_mark(
        (position,), _mark("120", 1_500), now_ms=1_500
    )
    payload = trailing.state_payload()
    assert payload["rules"][0]["trail_by_r"] == "0.5"
    assert payload["positions"][0]["rules"][0]["peak_gross_r"] == "2"

    restored = ProfitLockExecutionShadow(
        _config(), started_at_ms=9_999, rules=(TRAILING_PROFIT_RULE,)
    )
    restored.restore_state(payload)
    restored.observe_mark(
        (position,), _mark("114", 2_000), now_ms=2_000
    )
    assert restored.open_rule_state_payloads(
        TRAILING_PROFIT_RULE.rule_id
    )[0]["rule"]["triggered_at_ms"] == 2_000

    old = _shadow()
    with pytest.raises(
        ProfitLockExecutionShadowError, match="rule mismatch"
    ):
        old.restore_state(payload)
    with pytest.raises(
        ProfitLockExecutionShadowError, match="rule mismatch"
    ):
        trailing.restore_state(old.state_payload())

    payload["positions"][0]["rules"][0]["peak_gross_r"] = "0.2"
    with pytest.raises(
        ProfitLockExecutionShadowError,
        match="activated trailing rule peak R",
    ):
        trailing.restore_state(payload)


def test_fixed_rules_keep_exact_metadata_without_peak() -> None:
    position = _position()
    original = _shadow()
    original.observe_mark(
        (position,), _mark("106", 1_500), now_ms=1_500
    )
    state = original.state_payload()
    assert "trail_by_r" not in state["rules"][0]
    assert "peak_gross_r" not in state["positions"][0]["rules"][0]
    original.restore_state(state)

    fixed = ProfitLockExecutionShadow(
        _config(), started_at_ms=500, rules=(PROFIT_TARGET_RULE,)
    )
    assert fixed.state_payload()["rules"][0] == {
        "rule_id": "profit_target_at_1r",
        "activate_at_r": "1",
        "lock_at_r": "1",
        "exit_on_activation": "true",
    }


@pytest.mark.parametrize("offset", ["0", "-0.1", "1.5"])
def test_trailing_rule_rejects_invalid_r_gap(offset: str) -> None:
    with pytest.raises(ValueError, match="trail_by_r"):
        ProfitLockRule(
            rule_id="bad-trailer",
            activate_at_r=Decimal("1"),
            lock_at_r=Decimal("0.5"),
            trail_by_r=Decimal(offset),
        )


def test_trailing_cannot_be_immediate_take_profit() -> None:
    with pytest.raises(ValueError, match="cannot exit immediately"):
        ProfitLockRule(
            rule_id="bad-activation",
            activate_at_r=Decimal("1"),
            lock_at_r=Decimal("0.5"),
            exit_on_activation=True,
            trail_by_r=Decimal("0.5"),
        )
