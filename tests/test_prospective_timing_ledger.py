from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.prospective_side_conditioned_delay import (
    ProspectiveSideConditionedDelayState,
)
from cocomelon.research.prospective_timing_ledger import (
    ProspectiveTimingLedgerError,
    extract_prospective_timing_rows,
    update_timing_ledger,
    validate_timing_ledger,
)

RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    suffix: str,
    direction: Direction,
    *,
    opened_at_ms: int,
    exit_price: str,
) -> TradeJournalEntry:
    market = MarketId(
        "",
        "SOL" if direction is Direction.LONG else "BTC",
    )
    entry = Decimal("100")
    exit_px = Decimal(exit_price)
    gross = (
        exit_px - entry
        if direction is Direction.LONG
        else entry - exit_px
    )
    return TradeJournalEntry(
        market=market,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 300_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-close-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=(
            Decimal("90")
            if direction is Direction.LONG
            else Decimal("110")
        ),
        initial_risk_amount=Decimal("10"),
        entry_price=entry,
        exit_price=exit_px,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=gross,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=gross,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=300_000,
        mfe=None,
        mae=None,
        net_r=gross / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + gross,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _delayed(
    trade: TradeJournalEntry,
    *,
    price: str,
) -> DelayedEntryOutcome:
    px = Decimal(price)
    signed = (
        trade.entry_price - px
        if trade.direction is Direction.LONG
        else px - trade.entry_price
    )
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source="full_visible_book_ioc",
        delayed_filled_quantity=trade.filled_quantity,
        delayed_average_fill_price=px,
        delayed_fee=Decimal("0"),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=(
            signed / trade.entry_price * Decimal("10000")
        ),
        gross_r_improvement=(
            signed / trade.initial_risk_amount
        ),
    )


def _extract(
    tmp_path: Path,
) -> tuple[
    tuple[dict[str, object], ...],
    dict[str, int],
    ProspectiveSideConditionedDelayState,
]:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    state = ProspectiveSideConditionedDelayState(
        started_at_ms=1_000_000
    )
    try:
        long = _trade(
            "long",
            Direction.LONG,
            opened_at_ms=2_000_000,
            exit_price="105",
        )
        short = _trade(
            "short",
            Direction.SHORT,
            opened_at_ms=3_000_000,
            exit_price="95",
        )
        before = _trade(
            "before",
            Direction.LONG,
            opened_at_ms=500_000,
            exit_price="105",
        )
        for trade in (long, short, before):
            journal.record_trade(trade)
        rows, diagnostics = extract_prospective_timing_rows(
            journal,
            (
                _delayed(long, price="99"),
                _delayed(short, price="101"),
                _delayed(before, price="99"),
            ),
            (
                _delayed(long, price="98"),
                _delayed(short, price="102"),
                _delayed(before, price="98"),
            ),
            state,
        )
    finally:
        journal.close()
    return rows, diagnostics, state


def _update(
    rows: tuple[dict[str, object], ...],
    diagnostics: dict[str, int],
    state: ProspectiveSideConditionedDelayState,
    previous: dict[str, object] | None = None,
    *,
    run_id: int = 100,
) -> dict[str, object]:
    return update_timing_ledger(
        rows,
        diagnostics,
        state,
        previous=previous,
        source_paper_run_id=run_id,
        source_paper_run_attempt=1,
        source_timing_artifact_name=f"timing-{run_id}",
    )


def test_extract_timing_rows_applies_frozen_side_rule(
    tmp_path: Path,
) -> None:
    rows, diagnostics, _ = _extract(tmp_path)

    assert diagnostics["prospective_closed_trades"] == 2
    assert diagnostics["paired_evaluable_trades"] == 2
    assert len(rows) == 2

    long = next(row for row in rows if row["direction"] == "long")
    short = next(
        row for row in rows if row["direction"] == "short"
    )

    assert long["selected_delay_ms"] == 120_000
    assert long["actual_net_pnl"] == "5"
    assert long["base_60s_net_pnl"] == "6"
    assert long["challenger_120s_net_pnl"] == "7"
    assert long["selected_net_pnl"] == "7"
    assert long["selected_minus_actual_pnl"] == "2"
    assert long["selected_minus_60s_pnl"] == "1"

    assert short["selected_delay_ms"] == 60_000
    assert short["actual_net_pnl"] == "5"
    assert short["base_60s_net_pnl"] == "6"
    assert short["challenger_120s_net_pnl"] == "7"
    assert short["selected_net_pnl"] == "6"
    assert short["selected_minus_actual_pnl"] == "1"
    assert short["selected_minus_60s_pnl"] == "0"


def test_initial_timing_ledger_is_canonical_and_valid(
    tmp_path: Path,
) -> None:
    rows, diagnostics, state = _extract(tmp_path)

    ledger = _update(rows, diagnostics, state)

    assert ledger["row_count"] == 2
    assert ledger["previous_row_count"] == 0
    assert ledger["new_row_count"] == 2
    assert validate_timing_ledger(ledger)["ledger_sha256"] == (
        ledger["ledger_sha256"]
    )


def test_timing_ledger_append_only_rejects_changed_prior_row(
    tmp_path: Path,
) -> None:
    rows, diagnostics, state = _extract(tmp_path)
    first = _update(rows, diagnostics, state)
    changed = [deepcopy(row) for row in rows]
    changed[0]["actual_net_pnl"] = "4"
    changed[0]["selected_minus_actual_pnl"] = "3"

    with pytest.raises(
        ProspectiveTimingLedgerError,
        match="previous timing row changed",
    ):
        _update(
            tuple(changed),
            diagnostics,
            state,
            first,
            run_id=101,
        )


def test_timing_ledger_rejects_disappeared_prior_row(
    tmp_path: Path,
) -> None:
    rows, diagnostics, state = _extract(tmp_path)
    first = _update(rows, diagnostics, state)

    with pytest.raises(
        ProspectiveTimingLedgerError,
        match="previous timing row disappeared",
    ):
        _update(
            rows[1:],
            diagnostics,
            state,
            first,
            run_id=101,
        )


def test_timing_ledger_allows_late_evaluable_older_close(
    tmp_path: Path,
) -> None:
    rows, diagnostics, state = _extract(tmp_path)
    first = _update(rows[1:], diagnostics, state)

    second = _update(
        rows,
        diagnostics,
        state,
        first,
        run_id=101,
    )

    assert second["previous_row_count"] == 1
    assert second["new_row_count"] == 1
    assert second["row_count"] == 2


def test_timing_ledger_rejects_candidate_metadata_drift(
    tmp_path: Path,
) -> None:
    rows, diagnostics, state = _extract(tmp_path)
    first = _update(rows, diagnostics, state)
    changed_state = ProspectiveSideConditionedDelayState(
        started_at_ms=state.started_at_ms + 1,
    )

    with pytest.raises(
        ProspectiveTimingLedgerError,
        match="timing ledger metadata drift",
    ):
        _update(
            rows,
            diagnostics,
            changed_state,
            first,
            run_id=101,
        )


def test_timing_ledger_rejects_corrupt_previous_digest(
    tmp_path: Path,
) -> None:
    rows, diagnostics, state = _extract(tmp_path)
    first = _update(rows, diagnostics, state)
    first["rows_sha256"] = "corrupt"

    with pytest.raises(
        ProspectiveTimingLedgerError,
        match="row digest mismatch",
    ):
        _update(
            rows,
            diagnostics,
            state,
            first,
            run_id=101,
        )
