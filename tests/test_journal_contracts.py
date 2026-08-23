from decimal import ROUND_UP, Context, Decimal, getcontext, setcontext

import pytest

from cocomelon.domain.journal import JournalEvent, JournalEventType, TradeSummary
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction

MARKET = MarketId(dex="", coin="SOL")


def test_journal_event_id_is_deterministic_and_preserves_decimal_text() -> None:
    first = JournalEvent.create(
        event_type=JournalEventType.STRATEGY_DECISION,
        occurred_at_ms=1_000,
        code_version="abc123",
        config_snapshot_id="cfg-1",
        payload={"score": Decimal("0.2500"), "reasons": ("TREND",)},
        decision_id="decision-1",
        market=MARKET,
    )
    second = JournalEvent.create(
        event_type=JournalEventType.STRATEGY_DECISION,
        occurred_at_ms=1_000,
        code_version="abc123",
        config_snapshot_id="cfg-1",
        payload={"reasons": ["TREND"], "score": Decimal("0.2500")},
        decision_id="decision-1",
        market=MARKET,
    )

    assert first.journal_event_id == second.journal_event_id
    assert len(first.journal_event_id) == 64
    assert first.payload_sha256 == second.payload_sha256
    assert '"score":"0.2500"' in first.payload_json
    assert first.market == MARKET


def test_journal_event_rejects_non_finite_payload_decimal() -> None:
    with pytest.raises(ValueError, match="finite"):
        JournalEvent.create(
            event_type=JournalEventType.RISK_DECISION,
            occurred_at_ms=1_000,
            code_version="abc123",
            config_snapshot_id="cfg-1",
            payload={"risk": Decimal("NaN")},
        )


def test_trade_summary_net_r_does_not_depend_on_ambient_decimal_context() -> None:
    original = getcontext().copy()
    try:
        setcontext(Context(prec=4, rounding=ROUND_UP))
        summary = TradeSummary(
            trade_id="trade-1",
            decision_id="decision-1",
            risk_decision_id="risk-1",
            opening_plan_id="plan-1",
            replay_run_id="run-1",
            market=MARKET,
            direction=Direction.LONG,
            entry_timestamp_ms=1_000,
            exit_timestamp_ms=6_000,
            entry_price=Decimal("100"),
            exit_price=Decimal("102"),
            quantity=Decimal("10"),
            initial_stop_price=Decimal("95"),
            approved_risk_amount=Decimal("50"),
            maximum_actual_notional=Decimal("1000"),
            gross_pnl=Decimal("20"),
            fees=Decimal("1.5"),
            funding=Decimal("-0.5"),
            entry_slippage=Decimal("0.4"),
            exit_slippage=Decimal("0.6"),
            net_pnl=Decimal("17.4"),
            mfe_pnl=Decimal("50"),
            mae_pnl=Decimal("-20"),
            exit_reason="THESIS_EXIT",
            reason_trace=("TREND", "RISK_APPROVED", "THESIS_EXIT"),
            equity_before=Decimal("10000"),
            equity_after=Decimal("10017.4"),
        )

        assert summary.holding_ms == 5_000
        assert summary.net_r == Decimal("0.348")
        assert summary.mfe_r == Decimal("1")
        assert summary.mae_r == Decimal("-0.4")
    finally:
        setcontext(original)


def test_trade_summary_requires_trade_direction_and_positive_risk() -> None:
    common = dict(
        trade_id="trade-1",
        decision_id="decision-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-1",
        replay_run_id="run-1",
        market=MARKET,
        entry_timestamp_ms=1_000,
        exit_timestamp_ms=2_000,
        entry_price=Decimal("100"),
        exit_price=Decimal("99"),
        quantity=Decimal("1"),
        initial_stop_price=Decimal("95"),
        maximum_actual_notional=Decimal("100"),
        gross_pnl=Decimal("-1"),
        fees=Decimal("0"),
        funding=Decimal("0"),
        entry_slippage=Decimal("0"),
        exit_slippage=Decimal("0"),
        net_pnl=Decimal("-1"),
        mfe_pnl=Decimal("0"),
        mae_pnl=Decimal("-1"),
        exit_reason="STOP",
        reason_trace=("STOP",),
        equity_before=Decimal("1000"),
        equity_after=Decimal("999"),
    )

    with pytest.raises(ValueError, match="LONG or SHORT"):
        TradeSummary(direction=Direction.NO_TRADE, approved_risk_amount=Decimal("10"), **common)
    with pytest.raises(ValueError, match="approved_risk_amount"):
        TradeSummary(direction=Direction.LONG, approved_risk_amount=Decimal("0"), **common)
