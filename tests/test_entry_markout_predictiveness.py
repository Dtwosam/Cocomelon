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
from cocomelon.research.entry_markout_predictiveness import (
    entry_markout_predictiveness,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
    net_pnl: str,
) -> TradeJournalEntry:
    pnl = Decimal(net_pnl)
    entry = Decimal("100")
    quantity = Decimal("1")
    exit_price = (
        entry + pnl
        if direction is Direction.LONG
        else entry - pnl
    )
    return TradeJournalEntry(
        market=MARKET,
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        feature_snapshot_id=f"feature-{suffix}",
        strategy_decision_id=f"strategy-{suffix}",
        risk_decision_id=f"risk-{suffix}",
        opening_plan_id=f"open-plan-{suffix}",
        opening_attempt_id=f"open-attempt-{suffix}",
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
        exit_price=exit_price,
        filled_quantity=quantity,
        gross_realized_pnl=pnl,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=None,
        mae=None,
        net_r=pnl / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + pnl,
        exit_reason="fixture",
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
    *,
    complete: bool = True,
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
        venue_max_leverage=Decimal("20"),
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
        known_gap_intervals=(),
    )


def test_predictiveness_distinguishes_signal_from_reversal_noise(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    try:
        favorable_winner = _trade(
            suffix="fav-win",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            closed_at_ms=2_100_000,
            net_pnl="5",
        )
        favorable_loser = _trade(
            suffix="fav-loss",
            direction=Direction.LONG,
            opened_at_ms=3_000_000,
            closed_at_ms=4_100_000,
            net_pnl="-4",
        )
        adverse_loser = _trade(
            suffix="adv-loss",
            direction=Direction.SHORT,
            opened_at_ms=5_000_000,
            closed_at_ms=6_100_000,
            net_pnl="-6",
        )
        adverse_winner = _trade(
            suffix="adv-win",
            direction=Direction.SHORT,
            opened_at_ms=7_000_000,
            closed_at_ms=8_100_000,
            net_pnl="3",
        )
        trades = (
            favorable_winner,
            favorable_loser,
            adverse_loser,
            adverse_winner,
        )
        for trade in trades:
            journal.record_trade(trade)

        paths.record(
            _path(
                favorable_winner,
                (
                    (1_060_000, "101"),
                    (1_300_000, "102"),
                    (1_900_000, "103"),
                ),
            )
        )
        paths.record(
            _path(
                favorable_loser,
                (
                    (3_060_000, "101"),
                    (3_300_000, "99"),
                    (3_900_000, "98"),
                ),
            )
        )
        paths.record(
            _path(
                adverse_loser,
                (
                    (5_060_000, "101"),
                    (5_300_000, "102"),
                    (5_900_000, "103"),
                ),
            )
        )
        paths.record(
            _path(
                adverse_winner,
                (
                    (7_060_000, "101"),
                    (7_300_000, "99"),
                    (7_900_000, "98"),
                ),
            )
        )

        result = entry_markout_predictiveness(
            journal,
            paths,
        )
    finally:
        journal.close()

    horizons = result["by_horizon_ms"]
    assert isinstance(horizons, dict)
    one = horizons["60000"]
    assert isinstance(one, dict)
    assert one["observations"] == 4
    assert one["sign_correct_final_outcomes"] == 2
    assert one["sign_accuracy"] == "0.5"

    favorable = one["favorable"]
    adverse = one["adverse"]
    assert isinstance(favorable, dict)
    assert isinstance(adverse, dict)
    assert favorable["trades"] == 2
    assert favorable["wins"] == 1
    assert favorable["losses"] == 1
    assert favorable["win_rate"] == "0.5"
    assert favorable["net_pnl"] == "1"
    assert favorable["mean_final_net_r"] == "0.05"
    assert adverse["trades"] == 2
    assert adverse["wins"] == 1
    assert adverse["losses"] == 1
    assert adverse["win_rate"] == "0.5"
    assert adverse["net_pnl"] == "-3"
    assert adverse["mean_final_net_r"] == "-0.15"

    readiness = one["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert readiness["missing_observations"] == 26
    assert readiness["missing_favorable"] == 8
    assert readiness["missing_adverse"] == 8


def test_predictiveness_censors_short_lifecycle_and_incomplete_path(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    try:
        short_lived = _trade(
            suffix="short-lived",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            closed_at_ms=1_200_000,
            net_pnl="-2",
        )
        incomplete = _trade(
            suffix="incomplete",
            direction=Direction.LONG,
            opened_at_ms=2_000_000,
            closed_at_ms=3_100_000,
            net_pnl="-2",
        )
        journal.record_trade(short_lived)
        journal.record_trade(incomplete)
        paths.record(
            _path(
                short_lived,
                ((1_060_000, "99"),),
            )
        )
        paths.record(
            _path(
                incomplete,
                ((2_060_000, "99"),),
                complete=False,
            )
        )

        result = entry_markout_predictiveness(
            journal,
            paths,
        )
    finally:
        journal.close()

    assert result["complete_path_records"] == 1
    assert result["incomplete_paths_skipped"] == 1
    horizons = result["by_horizon_ms"]
    assert isinstance(horizons, dict)
    one = horizons["60000"]
    five = horizons["300000"]
    fifteen = horizons["900000"]
    assert isinstance(one, dict)
    assert isinstance(five, dict)
    assert isinstance(fifteen, dict)
    assert one["observations"] == 1
    assert five["observations"] == 0
    assert five["censored_before_horizon"] == 1
    assert fifteen["observations"] == 0
    assert fifteen["censored_before_horizon"] == 1
