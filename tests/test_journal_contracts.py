from decimal import ROUND_UP, Context, Decimal, localcontext

import pytest

from cocomelon.domain.journal import (
    ExcursionMetric,
    JournalObservation,
    ObservationKind,
    TradeJournalEntry,
)
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction

MARKET = MarketId("", "SOL")


def observation() -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.STRATEGY_DECISION,
        timestamp_ms=1_000,
        market=MARKET,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=("trend_confirmed", "trend_confirmed", "liquid"),
        health_refs=("health-2", "health-1", "health-2"),
        replay_run_id="run-1",
    )


def excursion(kind: str, value: str) -> ExcursionMetric:
    return ExcursionMetric(
        kind=kind,
        price=Decimal(value),
        per_unit=Decimal("2"),
        fraction=Decimal("0.02"),
        currency=Decimal("20"),
        r_multiple=Decimal("0.8"),
        timestamp_ms=1_500,
        source_event_key=f"ctx:SOL:{kind}",
        complete=True,
    )


def trade_entry(*, funding_event_ids: tuple[str, ...] = ("funding-1",)) -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
        opened_at_ms=1_000,
        closed_at_ms=2_000,
        feature_snapshot_id="feature-1",
        strategy_decision_id="strategy-1",
        risk_decision_id="risk-1",
        opening_plan_id="plan-open",
        opening_attempt_id="attempt-open",
        exit_plan_ids=("plan-exit",),
        exit_attempt_ids=("attempt-exit",),
        fill_ids=("fill-open", "fill-exit"),
        position_action_ids=("action-exit",),
        funding_event_ids=funding_event_ids,
        initial_stop=Decimal("95"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("102"),
        filled_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("20"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.459"),
        funding_cash_pnl=Decimal("-0.1"),
        net_pnl=Decimal("18.991"),
        entry_slippage_amount=Decimal("1"),
        exit_slippage_amount=Decimal("1.5"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.0015"),
        holding_duration_ms=1_000,
        mfe=excursion("mfe", "103"),
        mae=excursion("mae", "98"),
        net_r=Decimal("0.75964"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10018.991"),
        exit_reason="exit_thesis",
        health_refs=("health-1",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="run-1",
    )


def test_observation_normalizes_repeatable_reason_and_health_refs() -> None:
    item = observation()

    assert item.reason_codes == ("trend_confirmed", "liquid")
    assert item.health_refs == ("health-1", "health-2")
    assert len(item.observation_id) == 24


def test_trade_id_changes_when_funding_reference_changes() -> None:
    first = trade_entry(funding_event_ids=("funding-1",))
    second = trade_entry(funding_event_ids=("funding-2",))

    assert first.trade_id != second.trade_id


def test_journal_ids_ignore_ambient_decimal_context() -> None:
    expected = trade_entry().trade_id

    with localcontext(Context(prec=7, rounding=ROUND_UP)):
        assert trade_entry().trade_id == expected


def test_trade_financial_values_must_be_finite_and_lifecycle_ordered() -> None:
    with pytest.raises(ValueError, match="closed_at_ms"):
        TradeJournalEntry(**{**trade_entry_kwargs(), "closed_at_ms": 999})

    with pytest.raises(ValueError, match="net_pnl"):
        TradeJournalEntry(**{**trade_entry_kwargs(), "net_pnl": Decimal("NaN")})


def test_trade_slippage_is_signed_and_holding_duration_must_reconcile() -> None:
    favorable = TradeJournalEntry(
        **{
            **trade_entry_kwargs(),
            "entry_slippage_amount": Decimal("-1"),
            "exit_slippage_amount": Decimal("-2"),
            "entry_slippage_fraction": Decimal("-0.001"),
            "exit_slippage_fraction": Decimal("-0.002"),
        }
    )

    assert favorable.entry_slippage_amount == Decimal("-1")
    assert favorable.exit_slippage_fraction == Decimal("-0.002")
    assert favorable.holding_duration_ms == 1_000

    with pytest.raises(ValueError, match="holding_duration_ms"):
        TradeJournalEntry(**{**trade_entry_kwargs(), "holding_duration_ms": 999})


def test_excursion_requires_supported_kind_and_source_identity() -> None:
    with pytest.raises(ValueError, match="kind"):
        excursion("mystery", "101")

    with pytest.raises(ValueError, match="source_event_key"):
        ExcursionMetric(
            kind="mfe",
            price=Decimal("101"),
            per_unit=Decimal("1"),
            fraction=Decimal("0.01"),
            currency=Decimal("10"),
            r_multiple=None,
            timestamp_ms=1_500,
            source_event_key="",
            complete=False,
        )


def trade_entry_kwargs() -> dict[str, object]:
    item = trade_entry()
    return {
        field: getattr(item, field)
        for field in item.__dataclass_fields__
        if field != "trade_id"
    }
