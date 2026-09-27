from __future__ import annotations

from decimal import Decimal

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.execution.accounting import (
    PaperAccountState,
    PaperPosition,
    PositionSide,
)
from cocomelon.research.account_lifecycle_bridge import (
    AccountLifecycleBridgeError,
    account_lifecycle_bridge,
)

MARKET = MarketId("", "SOL")


def _closed_trade() -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        feature_snapshot_id="feature-closed",
        strategy_decision_id="strategy-closed",
        risk_decision_id="risk-closed",
        opening_plan_id="plan-closed",
        opening_attempt_id="attempt-closed",
        exit_plan_ids=("exit-plan-closed",),
        exit_attempt_ids=("exit-attempt-closed",),
        fill_ids=("fill-open-closed", "fill-exit-closed"),
        position_action_ids=("action-closed",),
        funding_event_ids=(),
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("92"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("-8"),
        entry_fees=Decimal("1"),
        exit_fees=Decimal("1"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("-10"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=1_000,
        mfe=None,
        mae=None,
        net_r=Decimal("-1"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("9990"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _open_position(
    *,
    latest_mark: Decimal | None = Decimal("101"),
) -> PaperPosition:
    return PaperPosition(
        market=MarketId("", "BTC"),
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        average_entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        opening_plan_id="plan-open",
        opened_at_ms=3_000,
        updated_at_ms=4_000,
        planned_risk=Decimal("5"),
        cumulative_realized_gross_pnl=Decimal("60"),
        cumulative_fees=Decimal("1"),
        cumulative_funding=Decimal("0"),
        latest_mark=latest_mark,
    )


def _account(
    *,
    position: PaperPosition | None = None,
    cash: Decimal = Decimal("10049"),
) -> PaperAccountState:
    positions = () if position is None else (position,)
    unrealized = Decimal("0") if position is None else Decimal("1")
    gross_notional = (
        Decimal("0")
        if position is None
        else position.quantity * Decimal("101")
    )
    return PaperAccountState(
        starting_cash=Decimal("10000"),
        cash=cash,
        positions=positions,
        realized_gross_pnl=Decimal("52"),
        cumulative_fees=Decimal("3"),
        cumulative_funding=Decimal("0"),
        unrealized_pnl=unrealized,
        equity=cash + unrealized,
        gross_open_notional=gross_notional,
        updated_at_ms=4_000,
        available_margin=Decimal("9900"),
    )


def test_bridge_separates_open_realized_cash_from_closed_journal() -> None:
    position = _open_position()
    payload = account_lifecycle_bridge(
        _account(position=position),
        (_closed_trade(),),
    )

    account = payload["account"]
    open_lifecycles = payload["open_lifecycles"]
    closed = payload["implied_fully_closed_lifecycles"]
    journal = payload["journal_closed_trades"]
    reconciliation = payload["reconciliation"]

    assert isinstance(account, dict)
    assert isinstance(open_lifecycles, dict)
    assert isinstance(closed, dict)
    assert isinstance(journal, dict)
    assert isinstance(reconciliation, dict)

    assert account["realized_net_cash"] == "49"
    assert account["total_account_pnl"] == "50"
    assert open_lifecycles["realized_gross_pnl"] == "60"
    assert open_lifecycles["fees"] == "1"
    assert open_lifecycles["realized_net_cash"] == "59"
    assert open_lifecycles["unrealized_pnl"] == "1"
    assert open_lifecycles["mark_to_market_pnl"] == "60"

    positions = open_lifecycles["positions"]
    assert isinstance(positions, list)
    assert positions[0]["market"] == "BTC"
    assert positions[0]["realized_net_cash"] == "59"
    assert positions[0]["unrealized_gross_pnl"] == "1"
    assert positions[0]["lifecycle_mark_to_market_pnl"] == "60"

    assert closed == {
        "realized_gross_pnl": "-8",
        "fees": "2",
        "funding": "0",
        "net_pnl": "-10",
    }
    assert journal == closed
    assert reconciliation["absolute_tolerance"] == "1E-18"
    assert reconciliation["cash_bridge_delta"] == "0"
    assert reconciliation["closed_gross_delta"] == "0"
    assert reconciliation["closed_fees_delta"] == "0"
    assert reconciliation["closed_funding_delta"] == "0"
    assert reconciliation["closed_net_delta"] == "0"
    assert reconciliation["realized_bridge_delta"] == "0"
    assert reconciliation["equity_bridge_delta"] == "0"
    assert reconciliation["cash_bridge_matches_account"] is True
    assert reconciliation["closed_journal_matches_account"] is True
    assert reconciliation["realized_bridge_matches_account"] is True
    assert reconciliation["equity_bridge_matches_account"] is True


def test_bridge_reports_missing_closed_journal_without_guessing() -> None:
    payload = account_lifecycle_bridge(
        _account(position=_open_position()),
        (),
    )
    reconciliation = payload["reconciliation"]
    assert isinstance(reconciliation, dict)

    assert reconciliation["closed_gross_delta"] == "-8"
    assert reconciliation["closed_fees_delta"] == "2"
    assert reconciliation["closed_net_delta"] == "-10"
    assert reconciliation["realized_bridge_delta"] == "-10"
    assert reconciliation["equity_bridge_delta"] == "-10"
    assert reconciliation["closed_journal_matches_account"] is False


def test_bridge_reports_account_cash_reconciliation_failure() -> None:
    payload = account_lifecycle_bridge(
        _account(
            position=_open_position(),
            cash=Decimal("10048"),
        ),
        (_closed_trade(),),
    )
    reconciliation = payload["reconciliation"]
    assert isinstance(reconciliation, dict)
    assert reconciliation["cash_bridge_delta"] == "-1"
    assert reconciliation["cash_bridge_matches_account"] is False


def test_bridge_requires_latest_mark_for_open_position() -> None:
    with pytest.raises(
        AccountLifecycleBridgeError,
        match="missing latest mark",
    ):
        account_lifecycle_bridge(
            _account(position=_open_position(latest_mark=None)),
            (_closed_trade(),),
        )


def test_bridge_accepts_sub_tolerance_decimal_dust() -> None:
    position = _open_position()
    account = _account(
        position=position,
        cash=Decimal("10049.0000000000000000000001"),
    )
    payload = account_lifecycle_bridge(
        account,
        (_closed_trade(),),
    )
    reconciliation = payload["reconciliation"]
    assert isinstance(reconciliation, dict)

    assert reconciliation["cash_bridge_delta"] == "1E-22"
    assert reconciliation["cash_bridge_matches_account"] is True
    assert reconciliation["closed_journal_matches_account"] is True
    assert reconciliation["realized_bridge_matches_account"] is True
    assert reconciliation["equity_bridge_matches_account"] is True


def test_bridge_rejects_above_tolerance_decimal_delta() -> None:
    position = _open_position()
    account = _account(
        position=position,
        cash=Decimal("10049.000000000000001"),
    )
    payload = account_lifecycle_bridge(
        account,
        (_closed_trade(),),
    )
    reconciliation = payload["reconciliation"]
    assert isinstance(reconciliation, dict)

    assert reconciliation["cash_bridge_delta"] == "1E-15"
    assert reconciliation["cash_bridge_matches_account"] is False
