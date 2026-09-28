from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import ExcursionMetric, TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePath,
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
)
from cocomelon.research.excursion_timing import (
    excursion_timing_summary,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _excursion(
    *,
    kind: str,
    price: str,
    r_multiple: str,
    timestamp_ms: int,
    suffix: str,
) -> ExcursionMetric:
    value = Decimal(r_multiple)
    return ExcursionMetric(
        kind=kind,
        price=Decimal(price),
        per_unit=abs(Decimal(price) - Decimal("100")),
        fraction=abs(Decimal(price) - Decimal("100")) / Decimal("100"),
        currency=value * Decimal("10"),
        r_multiple=value,
        timestamp_ms=timestamp_ms,
        source_event_key=f"{kind}-{suffix}",
        complete=True,
    )


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
    net_r: str,
    mfe_r: str,
    mfe_ms: int,
    mae_r: str,
    mae_ms: int,
    exit_reason: str,
) -> TradeJournalEntry:
    risk = Decimal("10")
    net_r_value = Decimal(net_r)
    net_pnl = net_r_value * risk
    entry = Decimal("100")
    exit_price = (
        entry + net_pnl
        if direction is Direction.LONG
        else entry - net_pnl
    )
    mfe_price = (
        entry + Decimal(mfe_r) * risk
        if direction is Direction.LONG
        else entry - Decimal(mfe_r) * risk
    )
    mae_price = (
        entry - Decimal(mae_r) * risk
        if direction is Direction.LONG
        else entry + Decimal(mae_r) * risk
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
        initial_risk_amount=risk,
        entry_price=entry,
        exit_price=exit_price,
        filled_quantity=Decimal("1"),
        gross_realized_pnl=net_pnl,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=net_pnl,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        mfe=_excursion(
            kind="mfe",
            price=str(mfe_price),
            r_multiple=mfe_r,
            timestamp_ms=mfe_ms,
            suffix=suffix,
        ),
        mae=_excursion(
            kind="mae",
            price=str(mae_price),
            r_multiple=mae_r,
            timestamp_ms=mae_ms,
            suffix=suffix,
        ),
        net_r=net_r_value,
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + net_pnl,
        exit_reason=exit_reason,
        health_refs=("paper-state-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id=RUN_ID,
    )


def _fact(
    trade: TradeJournalEntry,
    *,
    lead_strategy: str,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=RUN_ID,
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=trade.opened_at_ms - 1_000,
        score=Decimal("80"),
        lead_strategy=lead_strategy,
        signal_ids=(f"signal-{trade.strategy_decision_id}",),
        reason_codes=("decision_threshold_met",),
        trend_regime=(
            TrendRegime.UP
            if trade.direction is Direction.LONG
            else TrendRegime.DOWN
        ),
        volatility_regime=VolatilityRegime.NORMAL,
    )


def _path(
    trade: TradeJournalEntry,
    marks: tuple[tuple[int, str], ...],
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
        excursion_complete=True,
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


def test_excursion_timing_tracks_thresholds_and_giveback(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    try:
        winner = _trade(
            suffix="winner",
            direction=Direction.LONG,
            opened_at_ms=1_000,
            closed_at_ms=11_000,
            net_r="0.6",
            mfe_r="1.2",
            mfe_ms=6_000,
            mae_r="0.2",
            mae_ms=2_000,
            exit_reason="OPPOSITE_FRESH_THESIS",
        )
        loser = _trade(
            suffix="loser",
            direction=Direction.SHORT,
            opened_at_ms=20_000,
            closed_at_ms=32_000,
            net_r="-0.4",
            mfe_r="1.1",
            mfe_ms=25_000,
            mae_r="0.7",
            mae_ms=31_000,
            exit_reason="MARK_STOP_TRIGGERED",
        )
        for trade in (winner, loser):
            journal.record_trade(trade)
        facts.record_decision_fact(
            _fact(winner, lead_strategy="breakout")
        )
        facts.record_decision_fact(
            _fact(loser, lead_strategy="trend")
        )
        paths.record(
            _path(
                winner,
                (
                    (2_000, "102.5"),
                    (3_000, "105"),
                    (6_000, "112"),
                    (10_000, "107"),
                ),
            )
        )
        paths.record(
            _path(
                loser,
                (
                    (21_000, "97.5"),
                    (22_000, "95"),
                    (25_000, "89"),
                    (31_000, "107"),
                ),
            )
        )

        result = excursion_timing_summary(
            journal,
            facts,
            paths,
        )
    finally:
        facts.close()
        journal.close()

    assert result["complete_paths_evaluated"] == 2
    overall = result["overall"]
    assert isinstance(overall, dict)
    assert overall["trades"] == 2
    assert overall["wins"] == 1
    assert overall["losses"] == 1
    assert overall["mean_time_to_mfe_ms"] == 5000
    assert overall["median_time_to_mfe_ms"] == 5000
    assert overall["mean_peak_to_close_ms"] == 6000

    thresholds = overall["thresholds"]
    assert isinstance(thresholds, dict)
    half = thresholds["0.5"]
    assert isinstance(half, dict)
    assert half["reached"] == 2
    assert half["mean_first_hit_ms"] == 2000
    assert half["losing_closes_after_reach"] == 1
    assert half["mean_reach_to_close_ms_for_losers"] == 10000

    one = thresholds["1"]
    assert isinstance(one, dict)
    assert one["reached"] == 2
    assert one["mean_first_hit_ms"] == 5000
    assert one["losing_closes_after_reach"] == 1
    assert one["mean_reach_to_close_ms_for_losers"] == 7000

    by_exit = result["by_exit_reason"]
    assert isinstance(by_exit, dict)
    assert by_exit["MARK_STOP_TRIGGERED"]["trades"] == 1
    assert (
        by_exit["OPPOSITE_FRESH_THESIS"]["trades"]
        == 1
    )

    gate = result["evidence_gate"]
    assert isinstance(gate, dict)
    assert gate["ready_for_review"] is False
    assert gate["missing_complete_paths"] == 28


def test_excursion_timing_reports_missing_decision_attribution(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    try:
        trade = _trade(
            suffix="missing",
            direction=Direction.LONG,
            opened_at_ms=1_000,
            closed_at_ms=11_000,
            net_r="-0.2",
            mfe_r="0.5",
            mfe_ms=4_000,
            mae_r="0.4",
            mae_ms=8_000,
            exit_reason="MARK_STOP_TRIGGERED",
        )
        journal.record_trade(trade)
        paths.record(
            _path(
                trade,
                (
                    (2_000, "102.5"),
                    (4_000, "105"),
                    (8_000, "96"),
                ),
            )
        )

        result = excursion_timing_summary(
            journal,
            facts,
            paths,
        )
    finally:
        facts.close()
        journal.close()

    assert result["complete_paths_evaluated"] == 1
    assert result["missing_decision_attribution"] == 1
    by_strategy = result["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["unknown"]["trades"] == 1
    gate = result["evidence_gate"]
    assert isinstance(gate, dict)
    assert gate["ready_for_review"] is False
