from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_contribution_decomposition import (
    delayed_entry_contribution_decomposition,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    exit_price: str,
) -> TradeJournalEntry:
    entry = Decimal("100")
    exit_px = Decimal(exit_price)
    quantity = Decimal("2")
    gross = (
        (exit_px - entry) * quantity
        if direction is Direction.LONG
        else (entry - exit_px) * quantity
    )
    entry_fees = Decimal("0.5")
    exit_fees = Decimal("0.5")
    net = gross - entry_fees - exit_fees
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=1_000,
        closed_at_ms=61_000,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(
            f"open-fill-{suffix}",
            f"exit-fill-{suffix}",
        ),
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
        filled_quantity=quantity,
        gross_realized_pnl=gross,
        entry_fees=entry_fees,
        exit_fees=exit_fees,
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
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str,
    quantity: str,
    price: str | None,
    fee: str,
    reason: str | None = None,
    capacity_cause: str | None = None,
) -> DelayedEntryOutcome:
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=Decimal(quantity),
        delayed_average_fill_price=(
            None if price is None else Decimal(price)
        ),
        delayed_fee=Decimal(fee),
        observation_lag_ms=1_000,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=reason,
        capacity_cause=capacity_cause,
    )


def test_decomposition_reconciles_full_partial_and_no_fill(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        full = _trade(
            suffix="full",
            direction=Direction.LONG,
            exit_price="102",
        )
        partial = _trade(
            suffix="partial",
            direction=Direction.LONG,
            exit_price="102",
        )
        no_fill = _trade(
            suffix="no-fill",
            direction=Direction.LONG,
            exit_price="98",
        )
        for trade in (full, partial, no_fill):
            journal.record_trade(trade)

        result = delayed_entry_contribution_decomposition(
            journal,
            (
                _outcome(
                    full,
                    source="full_visible_book_ioc",
                    quantity="2",
                    price="99",
                    fee="0.4",
                ),
                _outcome(
                    partial,
                    source="partial_visible_book_ioc",
                    quantity="1",
                    price="99",
                    fee="0.2",
                    reason=(
                        "IOC_REMAINDER_CANCELLED,"
                        "RISK_CEILING_REACHED"
                    ),
                ),
                _outcome(
                    no_fill,
                    source="no_fill",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 3
    assert Decimal(str(overall["price_effect_pnl"])) == Decimal("3")
    assert Decimal(str(overall["entry_fee_effect_pnl"])) == Decimal("0.15")
    assert Decimal(str(overall["exposure_effect_pnl"])) == Decimal("3.5")
    assert Decimal(str(overall["total_delta_pnl"])) == Decimal("6.65")

    by_source = result["by_source"]
    assert isinstance(by_source, dict)
    full_summary = by_source["full_visible_book_ioc"]
    partial_summary = by_source["partial_visible_book_ioc"]
    no_fill_summary = by_source["no_fill"]

    assert Decimal(str(full_summary["price_effect_pnl"])) == Decimal("2")
    assert Decimal(str(full_summary["entry_fee_effect_pnl"])) == Decimal("0.1")
    assert Decimal(str(full_summary["exposure_effect_pnl"])) == Decimal("0")
    assert Decimal(str(full_summary["total_delta_pnl"])) == Decimal("2.1")

    assert Decimal(str(partial_summary["price_effect_pnl"])) == Decimal("1.0")
    assert Decimal(str(partial_summary["entry_fee_effect_pnl"])) == Decimal("0.05")
    assert Decimal(str(partial_summary["exposure_effect_pnl"])) == Decimal("-1.50")
    assert Decimal(str(partial_summary["total_delta_pnl"])) == Decimal("-0.45")

    assert Decimal(str(no_fill_summary["price_effect_pnl"])) == Decimal("0")
    assert Decimal(str(no_fill_summary["entry_fee_effect_pnl"])) == Decimal("0.0")
    assert Decimal(str(no_fill_summary["exposure_effect_pnl"])) == Decimal("5.0")
    assert Decimal(str(no_fill_summary["total_delta_pnl"])) == Decimal("5.0")

    by_cause = result["by_capacity_cause"]
    assert isinstance(by_cause, dict)
    assert "risk_ceiling_clip" in by_cause


def test_exposure_effect_is_positive_when_unfilled_trade_was_loser(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        loser = _trade(
            suffix="loser",
            direction=Direction.SHORT,
            exit_price="102",
        )
        journal.record_trade(loser)
        result = delayed_entry_contribution_decomposition(
            journal,
            (
                _outcome(
                    loser,
                    source="partial_visible_book_ioc",
                    quantity="1",
                    price="101",
                    fee="0.2",
                    capacity_cause="slippage_boundary_reached",
                ),
            ),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert Decimal(str(overall["exposure_effect_pnl"])) > 0
    assert overall["exposure_effect_positive"] == 1
    assert overall["exposure_effect_negative"] == 0


def test_r_decomposition_reconciles_with_repeating_division(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="repeat-risk",
            direction=Direction.LONG,
            exit_price="102",
        )
        trade = TradeJournalEntry(
            **{
                field: getattr(trade, field)
                for field in trade.__dataclass_fields__
                if field not in {"initial_risk_amount", "net_r"}
            },
            initial_risk_amount=Decimal("7"),
            net_r=trade.net_pnl / Decimal("7"),
        )
        journal.record_trade(trade)
        result = delayed_entry_contribution_decomposition(
            journal,
            (
                _outcome(
                    trade,
                    source="partial_visible_book_ioc",
                    quantity="1",
                    price="99",
                    fee="0.2",
                    reason=(
                        "IOC_REMAINDER_CANCELLED,"
                        "RISK_CEILING_REACHED"
                    ),
                ),
            ),
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    components = (
        Decimal(str(overall["mean_price_effect_r"]))
        + Decimal(str(overall["mean_entry_fee_effect_r"]))
        + Decimal(str(overall["mean_exposure_effect_r"]))
    )
    assert components == Decimal(str(overall["mean_total_delta_r"]))


def test_unresolved_outcomes_are_excluded_not_zeroed(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="expired",
            direction=Direction.LONG,
            exit_price="98",
        )
        journal.record_trade(trade)
        result = delayed_entry_contribution_decomposition(
            journal,
            (
                _outcome(
                    trade,
                    source="expired",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
        )
    finally:
        journal.close()

    assert result["closed_shadow_outcomes"] == 1
    assert result["evaluated_delayed_attempts"] == 0
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 0
    assert Decimal(str(overall["total_delta_pnl"])) == Decimal("0")
