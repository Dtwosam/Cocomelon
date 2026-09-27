from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_pair_fill_weighted import (
    delayed_entry_pair_fill_weighted_summary,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
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
    entry_fee = Decimal("0.5")
    exit_fee = Decimal("0.5")
    net = gross - entry_fee - exit_fee
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 180_000,
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
        entry_fees=entry_fee,
        exit_fees=exit_fee,
        funding_cash_pnl=Decimal("0"),
        net_pnl=net,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=180_000,
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
    )


def test_pair_fill_weighting_charges_challenger_for_lost_size(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        long_trade = _trade(
            suffix="long",
            direction=Direction.LONG,
            opened_at_ms=10_000,
            exit_price="102",
        )
        short_trade = _trade(
            suffix="short",
            direction=Direction.SHORT,
            opened_at_ms=20_000,
            exit_price="98",
        )
        for trade in (long_trade, short_trade):
            journal.record_trade(trade)

        base = (
            _outcome(
                long_trade,
                source="partial_visible_book_ioc",
                quantity="1",
                price="99",
                fee="0.2",
            ),
            _outcome(
                short_trade,
                source="full_visible_book_ioc",
                quantity="2",
                price="101",
                fee="0.4",
            ),
        )
        challenger = (
            _outcome(
                long_trade,
                source="no_fill",
                quantity="0",
                price=None,
                fee="0",
            ),
            _outcome(
                short_trade,
                source="partial_visible_book_ioc",
                quantity="1",
                price="102",
                fee="0.2",
            ),
        )

        result = delayed_entry_pair_fill_weighted_summary(
            journal,
            base,
            challenger,
            started_at_ms=1,
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 2
    assert result["paired_evaluable_attempts"] == 2
    assert result["non_evaluable_base"] == 0
    assert result["non_evaluable_challenger"] == 0
    assert result["lineage_mismatches"] == 0

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 2
    assert overall["challenger_better"] == 0
    assert overall["base_better"] == 2
    assert overall["base_fill_weighted_net_pnl"] == "7.65"
    assert overall["challenger_fill_weighted_net_pnl"] == "3.55"
    assert overall["challenger_minus_base_pnl"] == "-4.10"
    assert overall["mean_base_fill_fraction"] == "0.75"
    assert overall["mean_challenger_fill_fraction"] == "0.25"
    assert overall["challenger_loses_fill_fraction"] == 2

    source_pairs = result["source_pairs"]
    assert isinstance(source_pairs, dict)
    assert (
        source_pairs[
            "partial_visible_book_ioc->no_fill"
        ]
        == 1
    )
    assert (
        source_pairs[
            "full_visible_book_ioc->partial_visible_book_ioc"
        ]
        == 1
    )


def test_pair_fill_weighting_can_reward_later_partial_fill(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="loss",
            direction=Direction.LONG,
            opened_at_ms=10_000,
            exit_price="98",
        )
        journal.record_trade(trade)
        result = delayed_entry_pair_fill_weighted_summary(
            journal,
            (
                _outcome(
                    trade,
                    source="no_fill",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
            (
                _outcome(
                    trade,
                    source="partial_visible_book_ioc",
                    quantity="1",
                    price="97",
                    fee="0.2",
                ),
            ),
            started_at_ms=1,
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["challenger_better"] == 1
    assert overall["base_fill_weighted_net_pnl"] == "0"
    assert overall["challenger_fill_weighted_net_pnl"] == "0.55"
    assert overall["challenger_minus_base_pnl"] == "0.55"
    assert overall["mean_base_fill_fraction"] == "0"
    assert overall["mean_challenger_fill_fraction"] == "0.5"
    assert overall["challenger_gains_fill_fraction"] == 1


def test_pair_fill_weighting_excludes_unresolved_sources(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="expired",
            direction=Direction.LONG,
            opened_at_ms=10_000,
            exit_price="98",
        )
        journal.record_trade(trade)
        result = delayed_entry_pair_fill_weighted_summary(
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
            (
                _outcome(
                    trade,
                    source="no_fill",
                    quantity="0",
                    price=None,
                    fee="0",
                ),
            ),
            started_at_ms=1,
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 1
    assert result["paired_evaluable_attempts"] == 0
    assert result["non_evaluable_base"] == 1
    assert result["non_evaluable_challenger"] == 0
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_pair_fill_weighting_reports_missing_outcomes(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    try:
        trade = _trade(
            suffix="missing",
            direction=Direction.SHORT,
            opened_at_ms=10_000,
            exit_price="98",
        )
        journal.record_trade(trade)
        result = delayed_entry_pair_fill_weighted_summary(
            journal,
            (),
            (),
            started_at_ms=1,
        )
    finally:
        journal.close()

    assert result["missing_base_outcome"] == 1
    assert result["missing_challenger_outcome"] == 0
    assert result["paired_evaluable_attempts"] == 0
