from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_full_stack_matched_trade_ledger import (
    ProspectiveFullStackMatchedTradeLedgerError,
    update_full_stack_matched_trade_ledger,
    validate_full_stack_matched_trade_ledger,
)

START = 30_000_000


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _trade(
    suffix: str,
    *,
    direction: Direction = Direction.LONG,
    market: str = "SOL",
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    net = Decimal(pnl)
    risk = Decimal("10")
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
        initial_risk_amount=risk,
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
        net_r=net / risk,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net,
        exit_reason="MARK_STOP_TRIGGERED",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _block_decision() -> dict[str, object]:
    return {
        "entry_decision": "BLOCK",
        "exit_evaluation": "NOT_APPLICABLE",
        "candidate_net_pnl": "0",
        "candidate_net_r": "0",
    }


def _admit_decision(
    *,
    candidate_pnl: str | None,
) -> dict[str, object]:
    if candidate_pnl is None:
        return {
            "entry_decision": "ADMIT",
            "exit_evaluation": "UNEVALUABLE",
            "candidate_net_pnl": None,
            "candidate_net_r": None,
        }
    pnl = Decimal(candidate_pnl)
    return {
        "entry_decision": "ADMIT",
        "exit_evaluation": "EVALUATED",
        "candidate_net_pnl": str(pnl),
        "candidate_net_r": str(pnl / Decimal("10")),
        "breakeven_activated": True,
        "breakeven_triggered": True,
        "breakeven_source": "visible_book_ioc",
    }


def _summary(
    trades: tuple[TradeJournalEntry, ...],
    decisions: dict[str, dict[str, object]],
    *,
    overlap_started_at_ms: int = START,
) -> dict[str, object]:
    terminal = sum(
        (
            decision.get("entry_decision") == "BLOCK"
            or decision.get("exit_evaluation") == "EVALUATED"
        )
        for decision in decisions.values()
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_readiness_gate": False,
        "claim_scope": "matched_trade_contribution_only",
        "portfolio_counterfactual": False,
        "replacement_trades_modeled": False,
        "overlap_started_at_ms": overlap_started_at_ms,
        "combined_started_at_ms": START - 4_000,
        "two_strike_started_at_ms": START - 3_000,
        "momentum_started_at_ms": START - 2_000,
        "breakeven_started_at_ms": overlap_started_at_ms,
        "closed_trades_since_overlap_start": len(
            tuple(
                trade
                for trade in trades
                if trade.opened_at_ms >= overlap_started_at_ms
            )
        ),
        "economically_evaluated_trades": terminal,
        "decision_by_trade_id": decisions,
    }


def test_full_stack_ledger_keeps_pending_exit_outside_immutable_rows() -> None:
    blocked = _trade(
        "blocked",
        opened_at_ms=START + 1_000,
        pnl="-8",
    )
    pending = _trade(
        "pending",
        direction=Direction.SHORT,
        market="ETH",
        opened_at_ms=START + 2_000,
        pnl="-6",
    )
    trades = (blocked, pending)
    decisions = {
        blocked.trade_id: _block_decision(),
        pending.trade_id: _admit_decision(candidate_pnl=None),
    }
    first = update_full_stack_matched_trade_ledger(
        trades,
        _summary(trades, decisions),
        previous=None,
        source_paper_run_id=10,
        source_paper_run_attempt=1,
        source_artifact_name="learning-10-1",
        source_artifact_digest=_digest("a"),
    )

    assert first["row_count"] == 1
    assert first["pending_trade_count"] == 1
    rows = first["rows"]
    assert isinstance(rows, tuple)
    assert rows[0]["trade_id"] == blocked.trade_id
    readiness = first["summary"]["review_readiness"]
    assert readiness["integrity_complete"] is False
    assert readiness["ready_for_evidence_review"] is False

    decisions[pending.trade_id] = _admit_decision(candidate_pnl="2")
    second = update_full_stack_matched_trade_ledger(
        trades,
        _summary(trades, decisions),
        previous=first,
        source_paper_run_id=11,
        source_paper_run_attempt=1,
        source_artifact_name="learning-11-1",
        source_artifact_digest=_digest("b"),
    )

    assert second["previous_row_count"] == 1
    assert second["new_row_count"] == 1
    assert second["row_count"] == 2
    assert second["pending_trade_count"] == 0
    second_rows = second["rows"]
    assert isinstance(second_rows, tuple)
    assert second_rows[0] == rows[0]
    assert second_rows[1]["trade_id"] == pending.trade_id
    validate_full_stack_matched_trade_ledger(second)


def test_full_stack_ledger_rejects_changed_terminal_row() -> None:
    trade = _trade(
        "changed",
        opened_at_ms=START + 1_000,
        pnl="-8",
    )
    decisions = {trade.trade_id: _block_decision()}
    first = update_full_stack_matched_trade_ledger(
        (trade,),
        _summary((trade,), decisions),
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_artifact_name="learning-20-1",
        source_artifact_digest=_digest("c"),
    )

    changed = deepcopy(decisions)
    changed[trade.trade_id]["candidate_net_pnl"] = "1"
    changed[trade.trade_id]["candidate_net_r"] = "0.1"
    with pytest.raises(
        ProspectiveFullStackMatchedTradeLedgerError,
        match="blocked entry candidate economics must be zero",
    ):
        update_full_stack_matched_trade_ledger(
            (trade,),
            _summary((trade,), changed),
            previous=first,
            source_paper_run_id=21,
            source_paper_run_attempt=1,
            source_artifact_name="learning-21-1",
            source_artifact_digest=_digest("d"),
        )


def test_full_stack_ledger_rejects_campaign_drift() -> None:
    trade = _trade(
        "campaign",
        opened_at_ms=START + 1_000,
        pnl="-8",
    )
    decisions = {trade.trade_id: _block_decision()}
    first = update_full_stack_matched_trade_ledger(
        (trade,),
        _summary((trade,), decisions),
        previous=None,
        source_paper_run_id=30,
        source_paper_run_attempt=1,
        source_artifact_name="learning-30-1",
        source_artifact_digest=_digest("e"),
    )

    with pytest.raises(
        ProspectiveFullStackMatchedTradeLedgerError,
        match="campaign identity drift",
    ):
        update_full_stack_matched_trade_ledger(
            (trade,),
            _summary(
                (trade,),
                decisions,
                overlap_started_at_ms=START + 1,
            ),
            previous=first,
            source_paper_run_id=31,
            source_paper_run_attempt=1,
            source_artifact_name="learning-31-1",
            source_artifact_digest=_digest("f"),
        )


def test_full_stack_ledger_is_idempotent_for_same_source() -> None:
    trade = _trade(
        "same",
        opened_at_ms=START + 1_000,
        pnl="-8",
    )
    decisions = {trade.trade_id: _block_decision()}
    source = _summary((trade,), decisions)
    first = update_full_stack_matched_trade_ledger(
        (trade,),
        source,
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_digest("1"),
    )
    repeated = update_full_stack_matched_trade_ledger(
        (trade,),
        source,
        previous=first,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_digest("1"),
    )

    assert repeated == validate_full_stack_matched_trade_ledger(first)


def test_full_stack_ledger_requires_profitable_robust_final_stack() -> None:
    markets = ("BTC", "ETH", "SOL", "ENA")
    trades: list[TradeJournalEntry] = []
    decisions: dict[str, dict[str, object]] = {}
    for index in range(30):
        trade = _trade(
            str(index),
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            market=markets[index % len(markets)],
            opened_at_ms=START + 1_000 + index * 100_000,
            pnl="-1",
        )
        trades.append(trade)
        decisions[trade.trade_id] = (
            _block_decision()
            if index < 10
            else _admit_decision(candidate_pnl="1")
        )

    ledger = update_full_stack_matched_trade_ledger(
        tuple(trades),
        _summary(tuple(trades), decisions),
        previous=None,
        source_paper_run_id=50,
        source_paper_run_attempt=1,
        source_artifact_name="learning-50-1",
        source_artifact_digest=_digest("2"),
    )

    overall = ledger["summary"]["overall"]
    assert overall["trades"] == 30
    assert overall["entry_blocked_trades"] == 10
    assert overall["entry_admitted_trades"] == 20
    assert overall["actual_net_pnl"] == "-30"
    assert overall["entry_stack_candidate_net_pnl"] == "-20"
    assert overall["full_stack_candidate_net_pnl"] == "20"
    assert overall["full_stack_candidate_net_r"] == "2.0"
    assert overall["full_stack_delta_net_pnl"] == "50"
    assert overall["full_stack_delta_net_r"] == "5.0"

    readiness = ledger["summary"]["review_readiness"]
    assert readiness["sample_complete"] is True
    assert readiness["integrity_complete"] is True
    assert readiness["candidate_profitable"] is True
    assert readiness["improvement_positive"] is True
    assert readiness["candidate_single_trade_robust"] is True
    assert readiness["candidate_single_market_robust"] is True
    assert readiness["delta_single_trade_robust"] is True
    assert readiness["delta_single_market_robust"] is True
    assert readiness["ready_for_evidence_review"] is True


def test_full_stack_ledger_does_not_call_less_bad_profitable() -> None:
    trades: list[TradeJournalEntry] = []
    decisions: dict[str, dict[str, object]] = {}
    markets = ("BTC", "ETH", "SOL", "ENA")
    for index in range(30):
        trade = _trade(
            f"less-bad-{index}",
            direction=(
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            ),
            market=markets[index % len(markets)],
            opened_at_ms=START + 1_000 + index * 100_000,
            pnl="-1",
        )
        trades.append(trade)
        decisions[trade.trade_id] = (
            _block_decision()
            if index < 10
            else _admit_decision(candidate_pnl="-0.25")
        )

    ledger = update_full_stack_matched_trade_ledger(
        tuple(trades),
        _summary(tuple(trades), decisions),
        previous=None,
        source_paper_run_id=60,
        source_paper_run_attempt=1,
        source_artifact_name="learning-60-1",
        source_artifact_digest=_digest("3"),
    )

    overall = ledger["summary"]["overall"]
    assert Decimal(overall["full_stack_delta_net_pnl"]) > 0
    assert Decimal(overall["full_stack_candidate_net_pnl"]) < 0
    readiness = ledger["summary"]["review_readiness"]
    assert readiness["improvement_positive"] is True
    assert readiness["candidate_profitable"] is False
    assert readiness["ready_for_evidence_review"] is False


def test_full_stack_ledger_rejects_semantically_corrupt_stored_row() -> None:
    trade = _trade(
        "corrupt",
        opened_at_ms=START + 1_000,
        pnl="-8",
    )
    decisions = {trade.trade_id: _block_decision()}
    ledger = update_full_stack_matched_trade_ledger(
        (trade,),
        _summary((trade,), decisions),
        previous=None,
        source_paper_run_id=70,
        source_paper_run_attempt=1,
        source_artifact_name="learning-70-1",
        source_artifact_digest=_digest("4"),
    )
    corrupt = deepcopy(ledger)
    rows = list(corrupt["rows"])
    row = dict(rows[0])
    row["full_stack_delta_net_pnl"] = "999"
    rows[0] = row
    corrupt["rows"] = rows

    with pytest.raises(
        ProspectiveFullStackMatchedTradeLedgerError,
        match="stored derived economics do not reconcile",
    ):
        validate_full_stack_matched_trade_ledger(corrupt)
