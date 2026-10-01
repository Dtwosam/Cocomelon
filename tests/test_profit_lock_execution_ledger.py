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
    ProfitLockExecutionLedgerError,
    update_profit_lock_execution_ledger,
    validate_profit_lock_execution_ledger,
)
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)


def _trade(
    suffix: str,
    *,
    pnl: str,
    opened_at_ms: int,
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
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
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
    rule_id: str,
    candidate_pnl: str | None,
    activated: bool,
    triggered: bool,
    complete: bool,
) -> ProfitLockExecutionOutcome:
    candidate = (
        None
        if candidate_pnl is None
        else Decimal(candidate_pnl)
    )
    candidate_r = (
        None
        if candidate is None
        else candidate / trade.initial_risk_amount
    )
    source = (
        "triggered_incomplete"
        if candidate is None
        else ("visible_book_ioc" if triggered else "actual_close")
    )
    if source == "actual_close":
        candidate = trade.net_pnl
        candidate_r = trade.net_r
    return ProfitLockExecutionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        rule_id=rule_id,
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
        simulated_exit_fees=Decimal("0.1") if complete else Decimal("0"),
        attempt_count=1 if triggered else 0,
        planning_rejection_count=0,
        no_fill_count=0,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        candidate_net_pnl_estimate=candidate,
        candidate_net_r_estimate=candidate_r,
        delta_net_pnl_estimate=(
            None if candidate is None else candidate - trade.net_pnl
        ),
        delta_net_r_estimate=(
            None if candidate_r is None else candidate_r - trade.net_r
        ),
        candidate_source=source,
    )


def _state(
    trades: tuple[TradeJournalEntry, ...],
    *,
    started_at_ms: int = 1_000,
    excluded: int = 0,
    lineage: int = 0,
    orphaned: int = 0,
) -> dict[str, object]:
    outcomes: list[dict[str, object]] = []
    for trade in trades:
        outcomes.append(
            _outcome(
                trade,
                rule_id="breakeven_after_0_5r",
                candidate_pnl="0",
                activated=True,
                triggered=True,
                complete=True,
            ).payload()
        )
        outcomes.append(
            _outcome(
                trade,
                rule_id="lock_0_5r_after_1r",
                candidate_pnl=None,
                activated=True,
                triggered=True,
                complete=False,
            ).payload()
        )
    return {
        "schema_version": EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
        "started_at_ms": started_at_ms,
        "execution_config": {
            "config_version": "paper-v1",
            "max_ioc_slippage_bps": "10",
        },
        "rules": [
            {
                "rule_id": rule.rule_id,
                "activate_at_r": str(rule.activate_at_r),
                "lock_at_r": str(rule.lock_at_r),
            }
            for rule in DEFAULT_PROFIT_LOCK_RULES
        ],
        "positions": [],
        "outcomes": outcomes,
        "excluded_closed_trades": excluded,
        "lineage_mismatch_closed_trades": lineage,
        "orphaned_restored_positions": orphaned,
    }


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def test_profit_lock_execution_ledger_appends_and_reconciles() -> None:
    first_trade = _trade(
        "first",
        pnl="-5",
        opened_at_ms=2_000,
    )
    first_state = _state((first_trade,))
    first = update_profit_lock_execution_ledger(
        (first_trade,),
        first_state,
        previous=None,
        source_paper_run_id=10,
        source_paper_run_attempt=1,
        source_artifact_name="learning-10-1",
        source_artifact_digest=_digest("a"),
    )

    assert first["row_count"] == 2
    assert first["new_row_count"] == 2
    summary = first["summary"]
    assert isinstance(summary, dict)
    rules = summary["rules"]
    assert isinstance(rules, list)
    breakeven = rules[0]
    assert breakeven["economically_evaluated_trades"] == 1
    assert breakeven["triggered_trades"] == 1
    assert breakeven["simulated_full_closes"] == 1
    assert breakeven["delta_net_pnl_estimate"] == "5"
    lock = rules[1]
    assert lock["economically_evaluated_trades"] == 0
    assert lock["triggered_incomplete"] == 1

    readiness = first["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["all_rules_ready_for_review"] is False
    assert readiness["execution_authority"] is False
    assert readiness["promotion_authority"] is False

    economics = first["economic_robustness"]
    assert isinstance(economics, dict)
    be_economics = economics["breakeven_after_0_5r"]
    assert be_economics["delta_net_pnl"] == "5"
    assert be_economics["delta_net_r"] == "0.5"
    assert be_economics["economics_positive"] is True

    second_trade = _trade(
        "second",
        pnl="-4",
        opened_at_ms=4_000,
        market="ETH",
        direction=Direction.SHORT,
    )
    second = update_profit_lock_execution_ledger(
        (first_trade, second_trade),
        _state((first_trade, second_trade)),
        previous=first,
        source_paper_run_id=11,
        source_paper_run_attempt=1,
        source_artifact_name="learning-11-1",
        source_artifact_digest=_digest("b"),
    )

    assert second["previous_row_count"] == 2
    assert second["new_row_count"] == 2
    assert second["row_count"] == 4
    assert second["prior_ledger_sha256"] == first["ledger_sha256"]
    rows = second["rows"]
    assert isinstance(rows, tuple)
    assert rows[:2] == first["rows"]
    validate_profit_lock_execution_ledger(second)


def test_profit_lock_execution_ledger_rejects_changed_outcome() -> None:
    trade = _trade("changed", pnl="-5", opened_at_ms=2_000)
    state = _state((trade,))
    first = update_profit_lock_execution_ledger(
        (trade,),
        state,
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_artifact_name="learning-20-1",
        source_artifact_digest=_digest("c"),
    )
    changed = _state((trade,))
    outcomes = changed["outcomes"]
    assert isinstance(outcomes, list)
    first_row = outcomes[0]
    assert isinstance(first_row, dict)
    first_row["attempt_count"] = 2

    with pytest.raises(
        ProfitLockExecutionLedgerError,
        match="previous profit-lock outcome changed",
    ):
        update_profit_lock_execution_ledger(
            (trade,),
            changed,
            previous=first,
            source_paper_run_id=21,
            source_paper_run_attempt=1,
            source_artifact_name="learning-21-1",
            source_artifact_digest=_digest("d"),
        )


def test_profit_lock_execution_ledger_rejects_candidate_drift() -> None:
    trade = _trade("drift", pnl="-5", opened_at_ms=2_000)
    first = update_profit_lock_execution_ledger(
        (trade,),
        _state((trade,)),
        previous=None,
        source_paper_run_id=30,
        source_paper_run_attempt=1,
        source_artifact_name="learning-30-1",
        source_artifact_digest=_digest("e"),
    )
    shifted = _state((trade,), started_at_ms=1_001)

    with pytest.raises(
        ProfitLockExecutionLedgerError,
        match="candidate metadata drift",
    ):
        update_profit_lock_execution_ledger(
            (trade,),
            shifted,
            previous=first,
            source_paper_run_id=31,
            source_paper_run_attempt=1,
            source_artifact_name="learning-31-1",
            source_artifact_digest=_digest("f"),
        )


def test_profit_lock_execution_ledger_rejects_counter_regression() -> None:
    trade = _trade("counter", pnl="-5", opened_at_ms=2_000)
    first = update_profit_lock_execution_ledger(
        (trade,),
        _state((trade,), excluded=2),
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_digest("1"),
    )

    with pytest.raises(
        ProfitLockExecutionLedgerError,
        match="counter regressed: excluded_closed_trades",
    ):
        update_profit_lock_execution_ledger(
            (trade,),
            _state((trade,), excluded=1),
            previous=first,
            source_paper_run_id=41,
            source_paper_run_attempt=1,
            source_artifact_name="learning-41-1",
            source_artifact_digest=_digest("2"),
        )


def test_profit_lock_execution_ledger_rejects_journal_drift() -> None:
    trade = _trade("journal", pnl="-5", opened_at_ms=2_000)
    state = _state((trade,))
    different = _trade(
        "journal",
        pnl="-4",
        opened_at_ms=2_000,
    )

    with pytest.raises(
        ProfitLockExecutionLedgerError,
        match="journal drift: actual_net_pnl",
    ):
        update_profit_lock_execution_ledger(
            (different,),
            state,
            previous=None,
            source_paper_run_id=50,
            source_paper_run_attempt=1,
            source_artifact_name="learning-50-1",
            source_artifact_digest=_digest("3"),
        )


def test_profit_lock_execution_ledger_same_source_is_idempotent() -> None:
    trade = _trade("same", pnl="-5", opened_at_ms=2_000)
    state = _state((trade,))
    first = update_profit_lock_execution_ledger(
        (trade,),
        state,
        previous=None,
        source_paper_run_id=60,
        source_paper_run_attempt=1,
        source_artifact_name="learning-60-1",
        source_artifact_digest=_digest("4"),
    )
    repeated = update_profit_lock_execution_ledger(
        (trade,),
        state,
        previous=first,
        source_paper_run_id=60,
        source_paper_run_attempt=1,
        source_artifact_name="learning-60-1",
        source_artifact_digest=_digest("4"),
    )

    assert repeated == validate_profit_lock_execution_ledger(first)


def test_profit_lock_execution_ledger_rejects_duplicate_source_drift() -> None:
    trade = _trade("source", pnl="-5", opened_at_ms=2_000)
    state = _state((trade,))
    first = update_profit_lock_execution_ledger(
        (trade,),
        state,
        previous=None,
        source_paper_run_id=70,
        source_paper_run_attempt=1,
        source_artifact_name="learning-70-1",
        source_artifact_digest=_digest("5"),
    )

    with pytest.raises(
        ProfitLockExecutionLedgerError,
        match="duplicate source artifact identity drift",
    ):
        update_profit_lock_execution_ledger(
            (trade,),
            state,
            previous=first,
            source_paper_run_id=70,
            source_paper_run_attempt=1,
            source_artifact_name="learning-70-1",
            source_artifact_digest=_digest("6"),
        )
