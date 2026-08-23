from dataclasses import replace
from decimal import Decimal

import pytest

from cocomelon.domain.journal import JournalEvent, JournalEventType, TradeSummary
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalConflictError, JournalStore

MARKET = MarketId(dex="", coin="SOL")


def event() -> JournalEvent:
    return JournalEvent.create(
        event_type=JournalEventType.POSITION_CLOSE,
        occurred_at_ms=2_000,
        code_version="abc123",
        config_snapshot_id="cfg-1",
        payload={"reason": "STOP", "net_pnl": Decimal("-10")},
        decision_id="decision-1",
        market=MARKET,
    )


def summary() -> TradeSummary:
    return TradeSummary(
        trade_id="trade-1",
        decision_id="decision-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-1",
        replay_run_id="run-1",
        market=MARKET,
        direction=Direction.LONG,
        entry_timestamp_ms=1_000,
        exit_timestamp_ms=2_000,
        entry_price=Decimal("100"),
        exit_price=Decimal("99"),
        quantity=Decimal("10"),
        initial_stop_price=Decimal("95"),
        approved_risk_amount=Decimal("50"),
        maximum_actual_notional=Decimal("1000"),
        gross_pnl=Decimal("-10"),
        fees=Decimal("1"),
        funding=Decimal("0"),
        entry_slippage=Decimal("0.2"),
        exit_slippage=Decimal("0.3"),
        net_pnl=Decimal("-11.5"),
        mfe_pnl=Decimal("20"),
        mae_pnl=Decimal("-15"),
        exit_reason="STOP",
        reason_trace=("TREND", "RISK_APPROVED", "STOP"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("9988.5"),
    )


def test_append_event_is_idempotent_and_survives_restart(tmp_path) -> None:
    path = tmp_path / "journal.sqlite3"
    first = JournalStore(path)
    row = event()

    first.append_event(row)
    first.append_event(row)
    first.close()

    reopened = JournalStore(path)
    assert reopened.load_events() == (row,)
    reopened.close()


def test_same_event_id_with_different_content_is_rejected(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    row = event()
    store.append_event(row)
    conflict = replace(row, payload_json='{"reason":"OTHER"}')

    with pytest.raises(JournalConflictError, match="journal_event_id"):
        store.append_event(conflict)
    store.close()


def test_trade_close_event_and_summary_commit_atomically(tmp_path) -> None:
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path)
    store.commit_trade_close(event(), summary())
    store.close()

    reopened = JournalStore(path)
    assert reopened.load_events() == (event(),)
    assert reopened.load_trade_summary("trade-1") == summary()
    reopened.close()


def test_injected_trade_close_failure_rolls_back_both_rows(tmp_path) -> None:
    path = tmp_path / "journal.sqlite3"
    store = JournalStore(path)

    def fail_after_event() -> None:
        raise OSError("injected failure")

    with pytest.raises(OSError, match="injected failure"):
        store.commit_trade_close(event(), summary(), after_event_write=fail_after_event)

    assert store.load_events() == ()
    assert store.load_trade_summary("trade-1") is None
    store.close()


def test_trade_summary_conflict_is_rejected_without_mutating_original(tmp_path) -> None:
    store = JournalStore(tmp_path / "journal.sqlite3")
    row = summary()
    store.upsert_trade_summary(row)
    conflict = replace(row, net_pnl=Decimal("99"))

    with pytest.raises(JournalConflictError, match="trade_id"):
        store.upsert_trade_summary(conflict)
    assert store.load_trade_summary("trade-1") == row
    store.close()
