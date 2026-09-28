from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePath,
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_stop_survivability import (
    delayed_entry_stop_survivability,
)

MARKET = MarketId("", "SOL")


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int = 100_000,
    closed_at_ms: int = 400_000,
) -> TradeJournalEntry:
    stop = (
        Decimal("90")
        if direction is Direction.LONG
        else Decimal("110")
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"plan-{suffix}",
        opening_attempt_id=f"attempt-{suffix}",
        exit_plan_ids=(f"exit-plan-{suffix}",),
        exit_attempt_ids=(f"exit-attempt-{suffix}",),
        fill_ids=(f"fill-open-{suffix}", f"fill-exit-{suffix}"),
        position_action_ids=(f"action-{suffix}",),
        funding_event_ids=(),
        initial_stop=stop,
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100"),
        filled_quantity=Decimal("1"),
        gross_realized_pnl=Decimal("0"),
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("0"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=Decimal("0"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000"),
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="continuous-paper-mainnet-v1",
    )


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
    *,
    complete: bool = True,
    gaps: tuple[tuple[int, int | None], ...] = (),
) -> ContinuousPaperTradePath:
    return ContinuousPaperTradePath(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        opened_at_ms=trade.opened_at_ms,
        closed_at_ms=trade.closed_at_ms,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        initial_stop=trade.initial_stop,
        initial_risk_amount=trade.initial_risk_amount,
        filled_quantity=trade.filled_quantity,
        excursion_complete=complete,
        health_refs=trade.health_refs,
        marks=tuple(
            ContinuousPaperTradePathMark(
                available_at_ms=timestamp_ms,
                exchange_time_ms=timestamp_ms,
                event_key=f"{trade.trade_id}-{timestamp_ms}",
                mark_px=Decimal(mark_px),
            )
            for timestamp_ms, mark_px in marks
        ),
        known_gap_intervals=gaps,
    )


def _outcome(
    trade: TradeJournalEntry,
    *,
    source: str = "full_visible_book_ioc",
    quantity: str = "1",
    price: str | None = "100",
    observation_lag_ms: int = 0,
) -> DelayedEntryOutcome:
    delayed_price = None if price is None else Decimal(price)
    return DelayedEntryOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=source,
        delayed_filled_quantity=Decimal(quantity),
        delayed_average_fill_price=delayed_price,
        delayed_fee=Decimal("0"),
        observation_lag_ms=observation_lag_ms,
        signed_price_improvement_bps=None,
        gross_r_improvement=None,
        attempt_reason=None,
        capacity_cause=None,
    )


def test_stop_survivability_detects_long_original_stop_crossing(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="long-hit",
            direction=Direction.LONG,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (160_000, "89"),
                    (170_000, "88"),
                    (300_000, "100"),
                ),
            )
        )

        result = delayed_entry_stop_survivability(
            journal,
            (_outcome(trade, price="100"),),
            paths,
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert result["evaluated_filled_candidates"] == 1
    assert overall["definite_original_stop_crossings"] == 1
    assert overall["survived_observed_path_to_actual_close"] == 0
    assert overall["min_time_to_stop_ms"] == 10_000
    assert result["mark_ordering_assumption"] == (
        "only_marks_strictly_after_delayed_open_are_causal"
    )


def test_stop_survivability_handles_short_and_survival(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        stopped = _trade(
            suffix="short-hit",
            direction=Direction.SHORT,
        )
        survived = _trade(
            suffix="short-survive",
            direction=Direction.SHORT,
            opened_at_ms=500_000,
            closed_at_ms=800_000,
        )
        for trade in (stopped, survived):
            journal.record_trade(trade)
        paths.record(
            _path(
                stopped,
                (
                    (170_000, "111"),
                    (300_000, "100"),
                ),
            )
        )
        paths.record(
            _path(
                survived,
                (
                    (570_000, "109"),
                    (700_000, "100"),
                ),
            )
        )

        result = delayed_entry_stop_survivability(
            journal,
            (
                _outcome(stopped, price="100"),
                _outcome(survived, price="100"),
            ),
            paths,
        )
    finally:
        journal.close()

    overall = result["overall"]
    by_side = result["by_side"]
    assert isinstance(overall, dict)
    assert isinstance(by_side, dict)
    assert overall["definite_original_stop_crossings"] == 1
    assert overall["survived_observed_path_to_actual_close"] == 1
    short = by_side["short"]
    assert isinstance(short, dict)
    assert short["filled_candidates"] == 2
    assert short["definite_original_stop_crossings"] == 1


def test_stop_survivability_no_fill_needs_no_trade_path(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="no-fill",
            direction=Direction.LONG,
        )
        journal.record_trade(trade)
        result = delayed_entry_stop_survivability(
            journal,
            (
                _outcome(
                    trade,
                    source="no_fill",
                    quantity="0",
                    price=None,
                ),
            ),
            paths,
        )
    finally:
        journal.close()

    assert result["candidate_no_fill_trades"] == 1
    assert result["evaluated_filled_candidates"] == 0
    assert result["missing_exact_paths"] == 0


def test_stop_survivability_gapped_path_blocks_review(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="gap",
            direction=Direction.LONG,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "95"),
                    (300_000, "100"),
                ),
                gaps=((200_000, 250_000),),
            )
        )
        result = delayed_entry_stop_survivability(
            journal,
            (_outcome(trade),),
            paths,
        )
    finally:
        journal.close()

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert result["incomplete_or_gapped_paths"] == 1
    assert result["evaluated_filled_candidates"] == 0
    assert readiness["ready_for_review"] is False



def test_stop_survivability_ignores_gaps_before_delayed_open(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="pre-delay-gap",
            direction=Direction.LONG,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (170_000, "95"),
                    (300_000, "100"),
                ),
                complete=False,
                gaps=(
                    (10_000, 50_000),
                    (120_000, 160_000),
                    (500_000, 600_000),
                ),
            )
        )
        result = delayed_entry_stop_survivability(
            journal,
            (_outcome(trade),),
            paths,
        )
    finally:
        journal.close()

    overall = result["overall"]
    assert isinstance(overall, dict)
    assert result["incomplete_or_gapped_paths"] == 0
    assert result["evaluated_filled_candidates"] == 1
    assert overall["survived_observed_path_to_actual_close"] == 1


def test_stop_survivability_requires_causal_mark_after_delayed_open(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(tmp_path / "trade-paths")
    try:
        trade = _trade(
            suffix="no-causal-mark",
            direction=Direction.LONG,
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (120_000, "95"),
                    (150_000, "100"),
                ),
            )
        )
        result = delayed_entry_stop_survivability(
            journal,
            (_outcome(trade),),
            paths,
        )
    finally:
        journal.close()

    assert result["incomplete_or_gapped_paths"] == 1
    assert result["evaluated_filled_candidates"] == 0
    assert result["lineage_mismatches"] == 0
