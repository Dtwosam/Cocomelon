from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathMark,
)
from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_RULES,
    ProfitLockCounterfactualError,
    ProfitLockRule,
    evaluate_profit_lock_rule,
    evaluate_profit_lock_study,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    direction: Direction = Direction.LONG,
    trade_id_suffix: str = "1",
    net_pnl: Decimal = Decimal("-10"),
) -> TradeJournalEntry:
    entry = Decimal("100")
    exit_price = Decimal("90") if direction is Direction.LONG else Decimal("110")
    gross = Decimal("-10")
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=1_000,
        closed_at_ms=11_000,
        feature_snapshot_id=f"feature-{trade_id_suffix}",
        strategy_decision_id=f"strategy-{trade_id_suffix}",
        risk_decision_id=f"risk-{trade_id_suffix}",
        opening_plan_id=f"plan-open-{trade_id_suffix}",
        opening_attempt_id=f"attempt-open-{trade_id_suffix}",
        exit_plan_ids=(f"plan-close-{trade_id_suffix}",),
        exit_attempt_ids=(f"attempt-close-{trade_id_suffix}",),
        fill_ids=(f"fill-open-{trade_id_suffix}", f"fill-close-{trade_id_suffix}"),
        position_action_ids=(f"action-close-{trade_id_suffix}",),
        funding_event_ids=(),
        initial_stop=Decimal("90") if direction is Direction.LONG else Decimal("110"),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=exit_price,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=gross,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net_pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=10_000,
        mfe=None,
        mae=None,
        net_r=net_pnl / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net_pnl,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _mark(ms: int, px: str, key: str) -> ContinuousPaperTradePathMark:
    return ContinuousPaperTradePathMark(
        available_at_ms=ms,
        exchange_time_ms=ms - 1,
        event_key=key,
        mark_px=Decimal(px),
    )


def _path_payload(
    trade: TradeJournalEntry,
    marks: tuple[ContinuousPaperTradePathMark, ...],
    *,
    path_complete: bool = True,
) -> dict[str, object]:
    return {
        "trade_id": trade.trade_id,
        "market": trade.market.canonical,
        "direction": trade.direction.value,
        "opened_at_ms": trade.opened_at_ms,
        "closed_at_ms": trade.closed_at_ms,
        "entry_price": str(trade.entry_price),
        "exit_price": str(trade.exit_price),
        "initial_stop": str(trade.initial_stop),
        "initial_risk_amount": str(trade.initial_risk_amount),
        "filled_quantity": str(trade.filled_quantity),
        "excursion_complete": path_complete,
        "path_complete": path_complete,
        "health_refs": list(trade.health_refs),
        "marks": [mark.to_dict() for mark in marks],
        "known_gap_intervals": [],
        "schema_version": 1,
        "path_id": "fixture-path-id",
    }


def test_breakeven_after_half_r_uses_first_crossing_mark() -> None:
    trade = _trade()
    rule = DEFAULT_PROFIT_LOCK_RULES[0]
    outcome = evaluate_profit_lock_rule(
        trade,
        (
            _mark(2_000, "105", "activate"),
            _mark(3_000, "104", "still-above"),
            _mark(4_000, "99", "gap-through"),
        ),
        rule,
    )

    assert outcome.activated is True
    assert outcome.activation_timestamp_ms == 2_000
    assert outcome.triggered is True
    assert outcome.trigger_timestamp_ms == 4_000
    assert outcome.trigger_mark_px == Decimal("99")
    assert outcome.candidate_net_pnl_estimate < Decimal("-1")
    assert outcome.candidate_net_pnl_estimate > trade.net_pnl
    assert outcome.delta_net_pnl_estimate > Decimal("8")


def test_half_r_lock_after_one_r_can_preserve_positive_estimated_net() -> None:
    trade = _trade()
    rule = DEFAULT_PROFIT_LOCK_RULES[1]
    outcome = evaluate_profit_lock_rule(
        trade,
        (
            _mark(2_000, "110", "activate"),
            _mark(3_000, "108", "hold"),
            _mark(4_000, "104", "trigger"),
        ),
        rule,
    )

    assert outcome.activated is True
    assert outcome.triggered is True
    assert outcome.trigger_mark_px == Decimal("104")
    assert outcome.candidate_net_pnl_estimate > Decimal("3.8")
    assert outcome.candidate_net_r_estimate > Decimal("0.38")
    assert outcome.delta_net_r_estimate > Decimal("1.38")


def test_profit_lock_rule_is_direction_symmetric_for_short() -> None:
    trade = _trade(direction=Direction.SHORT, trade_id_suffix="short")
    rule = ProfitLockRule(
        rule_id="short-fixture",
        activate_at_r=Decimal("1"),
        lock_at_r=Decimal("0.5"),
    )
    outcome = evaluate_profit_lock_rule(
        trade,
        (
            _mark(2_000, "90", "activate"),
            _mark(3_000, "92", "hold"),
            _mark(4_000, "96", "trigger"),
        ),
        rule,
    )

    assert outcome.activated is True
    assert outcome.triggered is True
    assert outcome.trigger_mark_px == Decimal("96")
    assert outcome.candidate_net_pnl_estimate > Decimal("3.8")


def test_study_uses_actual_close_when_rule_never_triggers() -> None:
    trade = _trade(net_pnl=Decimal("2"))
    study = evaluate_profit_lock_study(
        (trade,),
        (
            _path_payload(
                trade,
                (
                    _mark(2_000, "101", "one"),
                    _mark(3_000, "102", "two"),
                ),
            ),
        ),
    )

    assert study.evaluated_trade_count == 1
    assert study.skipped_incomplete_paths == 0
    assert len(study.rules) == 2
    for summary in study.rules:
        assert summary.triggered_trades == 0
        assert summary.actual_net_pnl == Decimal("2")
        assert summary.candidate_net_pnl_estimate == Decimal("2")
        assert summary.delta_net_pnl_estimate == Decimal("0")


def test_study_skips_incomplete_paths_without_guessing() -> None:
    trade = _trade()
    study = evaluate_profit_lock_study(
        (trade,),
        (
            _path_payload(
                trade,
                (_mark(2_000, "105", "partial"),),
                path_complete=False,
            ),
        ),
    )

    assert study.path_record_count == 1
    assert study.evaluated_trade_count == 0
    assert study.skipped_incomplete_paths == 1
    assert all(summary.evaluated_trades == 0 for summary in study.rules)


def test_study_fails_closed_on_path_journal_lineage_mismatch() -> None:
    trade = _trade()
    payload = _path_payload(
        trade,
        (_mark(2_000, "105", "mark"),),
    )
    payload["entry_price"] = "101"

    with pytest.raises(
        ProfitLockCounterfactualError,
        match="entry_price does not match journal",
    ):
        evaluate_profit_lock_study((trade,), (payload,))
