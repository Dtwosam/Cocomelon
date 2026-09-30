from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.prospective_two_strike_stop_filter import (
    EMBARGO_MS,
    ProspectiveTwoStrikeStopFilterState,
)
from cocomelon.research.prospective_two_strike_stop_filter_ledger import (
    ProspectiveTwoStrikeStopFilterLedgerError,
    update_two_strike_ledger,
    validate_two_strike_ledger,
)


def _trade(
    suffix: str,
    *,
    opened_at_ms: int,
    pnl: str,
    market: str = "SOL",
    direction: Direction = Direction.LONG,
    exit_reason: str = "MARK_STOP_TRIGGERED",
) -> TradeJournalEntry:
    net = Decimal(pnl)
    entry = Decimal("100")
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
        entry_price=entry,
        exit_price=(
            entry + net
            if direction is Direction.LONG
            else entry - net
        ),
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
        exit_reason=exit_reason,
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _source_digest(char: str) -> str:
    return "sha256:" + char * 64


def test_two_strike_ledger_appends_immutable_trade_rows() -> None:
    frozen = 1_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=frozen
    )
    start = frozen + EMBARGO_MS
    first_trades = (
        _trade("loss-1", opened_at_ms=start, pnl="-5"),
        _trade(
            "loss-2",
            opened_at_ms=start + 120_000,
            pnl="-6",
        ),
        _trade(
            "blocked",
            opened_at_ms=start + 240_000,
            pnl="-7",
        ),
    )

    first = update_two_strike_ledger(
        first_trades,
        state,
        previous=None,
        source_paper_run_id=10,
        source_paper_run_attempt=1,
        source_artifact_name="learning-10-1",
        source_artifact_digest=_source_digest("a"),
    )

    assert first["row_count"] == 3
    assert first["new_row_count"] == 3
    rows = first["rows"]
    assert isinstance(rows, tuple)
    assert [row["prior_strikes"] for row in rows] == [0, 1, 2]
    assert [row["candidate_admitted"] for row in rows] == [
        True,
        True,
        False,
    ]
    summary = first["summary"]
    assert isinstance(summary, dict)
    assert summary["blocked_trades"] == 1
    assert summary["blocked_losses"] == 1
    assert summary["delta_net_pnl"] == "7"

    second_trades = first_trades + (
        _trade(
            "reset",
            opened_at_ms=start + 360_000,
            pnl="4",
            exit_reason="OPPOSITE_FRESH_THESIS",
        ),
    )
    second = update_two_strike_ledger(
        second_trades,
        state,
        previous=first,
        source_paper_run_id=11,
        source_paper_run_attempt=1,
        source_artifact_name="learning-11-1",
        source_artifact_digest=_source_digest("b"),
    )

    assert second["previous_row_count"] == 3
    assert second["new_row_count"] == 1
    assert second["row_count"] == 4
    assert second["prior_ledger_sha256"] == first["ledger_sha256"]
    second_rows = second["rows"]
    assert isinstance(second_rows, tuple)
    assert second_rows[:3] == rows
    assert second_rows[3]["prior_strikes"] == 0
    assert second_rows[3]["candidate_admitted"] is True
    validate_two_strike_ledger(second)


def test_two_strike_ledger_rejects_freeze_drift() -> None:
    frozen = 2_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=frozen
    )
    start = frozen + EMBARGO_MS
    trades = (
        _trade("loss", opened_at_ms=start, pnl="-5"),
    )
    first = update_two_strike_ledger(
        trades,
        state,
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_artifact_name="learning-20-1",
        source_artifact_digest=_source_digest("c"),
    )

    shifted = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=frozen + 1
    )
    with pytest.raises(
        ProspectiveTwoStrikeStopFilterLedgerError,
        match="metadata drift: frozen_at_ms",
    ):
        update_two_strike_ledger(
            trades,
            shifted,
            previous=first,
            source_paper_run_id=21,
            source_paper_run_attempt=1,
            source_artifact_name="learning-21-1",
            source_artifact_digest=_source_digest("d"),
        )


def test_two_strike_ledger_rejects_changed_historical_row() -> None:
    frozen = 3_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=frozen
    )
    start = frozen + EMBARGO_MS
    original = (
        _trade("loss-1", opened_at_ms=start, pnl="-5"),
        _trade(
            "loss-2",
            opened_at_ms=start + 120_000,
            pnl="-6",
        ),
    )
    first = update_two_strike_ledger(
        original,
        state,
        previous=None,
        source_paper_run_id=30,
        source_paper_run_attempt=1,
        source_artifact_name="learning-30-1",
        source_artifact_digest=_source_digest("e"),
    )
    changed = (
        _trade("loss-1", opened_at_ms=start, pnl="-4"),
        original[1],
    )

    with pytest.raises(
        ProspectiveTwoStrikeStopFilterLedgerError,
        match="previous two-strike trade row changed",
    ):
        update_two_strike_ledger(
            changed,
            state,
            previous=first,
            source_paper_run_id=31,
            source_paper_run_attempt=1,
            source_artifact_name="learning-31-1",
            source_artifact_digest=_source_digest("f"),
        )


def test_two_strike_ledger_is_idempotent_for_same_source() -> None:
    frozen = 4_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=frozen
    )
    start = frozen + EMBARGO_MS
    trades = (
        _trade("loss", opened_at_ms=start, pnl="-5"),
    )
    first = update_two_strike_ledger(
        trades,
        state,
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_source_digest("1"),
    )
    repeated = update_two_strike_ledger(
        trades,
        state,
        previous=first,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_source_digest("1"),
    )

    assert repeated == validate_two_strike_ledger(first)


def test_two_strike_ledger_rejects_duplicate_source_identity_drift() -> None:
    frozen = 5_000_000
    state = ProspectiveTwoStrikeStopFilterState(
        frozen_at_ms=frozen
    )
    start = frozen + EMBARGO_MS
    trades = (
        _trade("loss", opened_at_ms=start, pnl="-5"),
    )
    first = update_two_strike_ledger(
        trades,
        state,
        previous=None,
        source_paper_run_id=50,
        source_paper_run_attempt=1,
        source_artifact_name="learning-50-1",
        source_artifact_digest=_source_digest("2"),
    )

    with pytest.raises(
        ProspectiveTwoStrikeStopFilterLedgerError,
        match="duplicate source run artifact identity drift",
    ):
        update_two_strike_ledger(
            trades,
            state,
            previous=first,
            source_paper_run_id=50,
            source_paper_run_attempt=1,
            source_artifact_name="learning-50-1",
            source_artifact_digest=_source_digest("3"),
        )
