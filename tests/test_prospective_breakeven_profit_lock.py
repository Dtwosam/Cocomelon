from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.profit_lock_counterfactual import (
    DEFAULT_PROFIT_LOCK_RULES,
)
from cocomelon.research.profit_lock_execution_ledger import (
    update_profit_lock_execution_ledger,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import (
    EMBARGO_MS,
    ProspectiveBreakevenProfitLockError,
    ProspectiveBreakevenProfitLockState,
    prospective_breakeven_from_execution_ledger,
    prospective_breakeven_profit_lock_summary,
)


def _trade(
    suffix: str,
    *,
    opened_at_ms: int,
    pnl: str,
    market: str = "SOL",
    direction: Direction = Direction.LONG,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
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
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + net,
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
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=net / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    candidate_pnl: str,
    activated: bool = True,
    triggered: bool = True,
    complete: bool = True,
) -> ProfitLockExecutionOutcome:
    candidate = Decimal(candidate_pnl)
    return ProfitLockExecutionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id="breakeven_after_0_5r",
        activated=activated,
        triggered=triggered,
        simulated_close_complete=complete,
        activation_timestamp_ms=(
            trade.opened_at_ms + 10_000 if activated else None
        ),
        trigger_timestamp_ms=(
            trade.opened_at_ms + 20_000 if triggered else None
        ),
        completion_timestamp_ms=(
            trade.opened_at_ms + 21_000 if complete else None
        ),
        simulated_filled_quantity=(
            trade.filled_quantity if complete else Decimal("0")
        ),
        simulated_average_exit_price=(
            Decimal("100") if complete else None
        ),
        simulated_exit_fees=Decimal("0"),
        attempt_count=1 if triggered else 0,
        planning_rejection_count=0,
        no_fill_count=0,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=(
            candidate if complete or not triggered else None
        ),
        candidate_net_r_estimate=(
            candidate / Decimal("10")
            if complete or not triggered
            else None
        ),
        delta_net_pnl_estimate=(
            candidate - trade.net_pnl
            if complete or not triggered
            else None
        ),
        delta_net_r_estimate=(
            candidate / Decimal("10") - trade.net_r
            if complete or not triggered
            else None
        ),
        candidate_source=(
            "visible_book_ioc"
            if complete and triggered
            else (
                "triggered_incomplete"
                if triggered
                else "actual_close"
            )
        ),
    )


def _state(outcomes: tuple[ProfitLockExecutionOutcome, ...]) -> dict[str, object]:
    return {
        "schema_version": EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
        "started_at_ms": 1,
        "execution_config": {"config_version": "paper-v1"},
        "rules": [
            {
                "rule_id": rule.rule_id,
                "activate_at_r": str(rule.activate_at_r),
                "lock_at_r": str(rule.lock_at_r),
            }
            for rule in DEFAULT_PROFIT_LOCK_RULES
        ],
        "positions": [],
        "outcomes": [outcome.payload() for outcome in outcomes],
        "excluded_closed_trades": 0,
        "lineage_mismatch_closed_trades": 0,
        "orphaned_restored_positions": 0,
    }


def test_prospective_breakeven_state_round_trip() -> None:
    state = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=123
    )
    assert state.started_at_ms == 123 + EMBARGO_MS
    restored = ProspectiveBreakevenProfitLockState.from_payload(
        state.payload()
    )
    assert restored == state

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["activate_at_r"] = "0.6"
    with pytest.raises(
        ProspectiveBreakevenProfitLockError,
        match="rule drift",
    ):
        ProspectiveBreakevenProfitLockState.from_payload(payload)


def test_prospective_breakeven_ignores_touched_pre_embargo_trades() -> None:
    frozen = 1_000_000
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=frozen
    )
    start = candidate.started_at_ms
    touched = _trade(
        "touched",
        opened_at_ms=start - 1,
        pnl="-5",
    )
    clean = _trade(
        "clean",
        opened_at_ms=start,
        pnl="-5",
    )
    result = prospective_breakeven_profit_lock_summary(
        (touched, clean),
        _state(
            (
                _outcome(touched, candidate_pnl="1"),
                _outcome(clean, candidate_pnl="1"),
            )
        ),
        candidate,
    )

    assert result["prospective_closed_trades"] == 1
    assert result["matched_outcomes"] == 1
    assert result["actual_net_pnl"] == "-5"
    assert result["candidate_net_pnl"] == "1"
    assert result["delta_net_pnl"] == "6"


def test_prospective_breakeven_requires_complete_future_outcomes() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=2_000_000
    )
    trade = _trade(
        "missing",
        opened_at_ms=candidate.started_at_ms,
        pnl="-5",
    )
    result = prospective_breakeven_profit_lock_summary(
        (trade,),
        _state(()),
        candidate,
    )

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is False
    assert readiness["ready_for_review"] is False
    assert result["missing_outcome_trade_ids"] == [trade.trade_id]


def test_prospective_breakeven_ready_requires_profitable_robust_both_sides() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=3_000_000
    )
    trades: list[TradeJournalEntry] = []
    outcomes: list[ProfitLockExecutionOutcome] = []
    for index in range(30):
        direction = (
            Direction.LONG if index % 2 == 0 else Direction.SHORT
        )
        market = "SOL" if index % 3 else "ETH"
        trade = _trade(
            f"ready-{index}",
            opened_at_ms=candidate.started_at_ms + index * 120_000,
            pnl="-1" if index < 10 else "1",
            market=market,
            direction=direction,
        )
        trades.append(trade)
        outcomes.append(
            _outcome(
                trade,
                candidate_pnl="1",
                activated=index < 16,
                triggered=index < 10,
                complete=index < 10,
            )
            if index < 10
            else ProfitLockExecutionOutcome(
                trade_id=trade.trade_id,
                opening_plan_id=trade.opening_plan_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                rule_id="breakeven_after_0_5r",
                activated=index < 16,
                triggered=False,
                simulated_close_complete=False,
                activation_timestamp_ms=(
                    trade.opened_at_ms + 10_000
                    if index < 16
                    else None
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
        )

    result = prospective_breakeven_profit_lock_summary(
        tuple(trades),
        _state(tuple(outcomes)),
        candidate,
    )

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["sample_complete"] is True
    assert readiness["candidate_profitable"] is True
    assert readiness["delta_positive"] is True
    assert readiness["single_trade_robust"] is True
    assert readiness["single_market_robust"] is True
    assert readiness["ready_for_review"] is True
    assert result["long_evaluated_trades"] == 15
    assert result["short_evaluated_trades"] == 15


def test_prospective_breakeven_incomplete_trigger_blocks_integrity() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=4_000_000
    )
    trade = _trade(
        "incomplete",
        opened_at_ms=candidate.started_at_ms,
        pnl="-5",
    )
    result = prospective_breakeven_profit_lock_summary(
        (trade,),
        _state(
            (
                _outcome(
                    trade,
                    candidate_pnl="0",
                    triggered=True,
                    complete=False,
                ),
            )
        ),
        candidate,
    )

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert result["triggered_incomplete"] == 1
    assert readiness["integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_prospective_breakeven_reuses_immutable_execution_ledger() -> None:
    candidate = ProspectiveBreakevenProfitLockState(
        frozen_at_ms=5_000_000
    )
    trade = _trade(
        "ledger",
        opened_at_ms=candidate.started_at_ms,
        pnl="-5",
        market="ETH",
        direction=Direction.SHORT,
    )
    execution_ledger = update_profit_lock_execution_ledger(
        (trade,),
        _state((_outcome(trade, candidate_pnl="1"),)),
        previous=None,
        source_paper_run_id=77,
        source_paper_run_attempt=2,
        source_artifact_name="learning-77-2",
        source_artifact_digest="sha256:" + "a" * 64,
    )

    result = prospective_breakeven_from_execution_ledger(
        (trade,),
        execution_ledger,
        candidate,
    )

    assert result["prospective_closed_trades"] == 1
    assert result["matched_outcomes"] == 1
    assert result["delta_net_pnl"] == "6"
    assert (
        result["source_execution_ledger_sha256"]
        == execution_ledger["ledger_sha256"]
    )
    assert result["source_execution_ledger_row_count"] == 1
    assert result["source_paper_run_id"] == 77
    assert result["source_paper_run_attempt"] == 2
    assert result["source_artifact_name"] == "learning-77-2"
