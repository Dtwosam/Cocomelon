from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePath,
    ContinuousPaperTradePathMark,
    ContinuousPaperTradePathStore,
)
from cocomelon.research.entry_markout import (
    MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS,
    entry_markout_summary,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    closed_at_ms: int,
) -> TradeJournalEntry:
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
        replay_run_id=RUN_ID,
    )


def _fact(
    trade: TradeJournalEntry,
    *,
    lead_strategy: str,
    decision_age_ms: int = 1,
) -> DecisionEvaluationFact:
    return DecisionEvaluationFact(
        strategy_decision_id=trade.strategy_decision_id,
        feature_snapshot_id=trade.feature_snapshot_id,
        replay_run_id=RUN_ID,
        market=trade.market,
        direction=trade.direction,
        timestamp_ms=trade.opened_at_ms - decision_age_ms,
        score=Decimal("75"),
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


def _rank(
    trade: TradeJournalEntry,
    *,
    ordinal: int,
    age_ms: int = 30_000,
) -> ContinuousPaperOpeningRankEvidence:
    return ContinuousPaperOpeningRankEvidence(
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        opened_at_ms=trade.opened_at_ms,
        rank_observed_at_ms=trade.opened_at_ms - age_ms,
        rank_age_ms=age_ms,
        ordinal=ordinal,
        score=Decimal("0.7"),
        rank_pool_size=20,
        reason_codes=("fixture",),
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
                event_key=(
                    f"{trade.trade_id}-{timestamp_ms}"
                ),
                mark_px=Decimal(mark_px),
            )
            for timestamp_ms, mark_px in marks
        ),
        known_gap_intervals=(),
    )


def test_entry_markout_uses_signed_long_short_economics_and_censors(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    try:
        long_trade = _trade(
            suffix="long",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            closed_at_ms=2_000_000,
        )
        short_trade = _trade(
            suffix="short",
            direction=Direction.SHORT,
            opened_at_ms=3_000_000,
            closed_at_ms=3_360_000,
        )
        for trade in (long_trade, short_trade):
            journal.record_trade(trade)
        facts.record_decision_fact(
            _fact(long_trade, lead_strategy="trend")
        )
        facts.record_decision_fact(
            _fact(
                short_trade,
                lead_strategy="breakout",
                decision_age_ms=7_000,
            )
        )

        paths.record(
            _path(
                long_trade,
                (
                    (1_060_000, "101"),
                    (1_300_000, "99"),
                    (1_900_000, "102"),
                ),
            )
        )
        paths.record(
            _path(
                short_trade,
                (
                    (3_060_000, "99"),
                    (3_300_000, "101"),
                ),
            )
        )

        result = entry_markout_summary(
            journal,
            facts,
            paths,
        )
    finally:
        facts.close()
        journal.close()

    horizons = result["by_horizon_ms"]
    assert isinstance(horizons, dict)

    one = horizons["60000"]
    assert isinstance(one, dict)
    assert one["observations"] == 2
    assert one["positive"] == 2
    assert one["negative"] == 0
    assert one["mean_signed_return_bps"] == "100.00"
    assert one["mean_gross_r"] == "0.1"
    assert one["mean_observation_lag_ms"] == 0
    assert one["stale_observed_mark"] == 0
    by_side = one["by_side"]
    assert isinstance(by_side, dict)
    assert by_side["long"]["mean_gross_r"] == "0.1"
    assert by_side["short"]["mean_gross_r"] == "0.1"
    by_age = one["by_decision_age_bucket"]
    assert isinstance(by_age, dict)
    assert by_age["<1s"]["observations"] == 1
    assert by_age["5-<15s"]["observations"] == 1
    assert by_age["<1s"]["mean_gross_r"] == "0.1"
    assert by_age["5-<15s"]["mean_gross_r"] == "0.1"

    five = horizons["300000"]
    assert isinstance(five, dict)
    assert five["observations"] == 2
    assert five["positive"] == 0
    assert five["negative"] == 2
    assert five["mean_signed_return_bps"] == "-100.00"
    assert five["mean_gross_r"] == "-0.1"
    assert five["stale_observed_mark"] == 0

    fifteen = horizons["900000"]
    assert isinstance(fifteen, dict)
    assert fifteen["observations"] == 1
    assert fifteen["positive"] == 1
    assert fifteen["censored_before_horizon"] == 1
    assert fifteen["mean_signed_return_bps"] == "200.00"
    assert fifteen["mean_gross_r"] == "0.2"
    assert fifteen["stale_observed_mark"] == 0
    by_strategy = fifteen["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["trend"]["observations"] == 1





def test_entry_markout_rejects_marks_beyond_freshness_bound(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    try:
        trade = _trade(
            suffix="stale",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            closed_at_ms=2_000_000,
        )
        journal.record_trade(trade)
        facts.record_decision_fact(
            _fact(trade, lead_strategy="trend")
        )
        paths.record(
            _path(
                trade,
                (
                    (
                        1_060_000
                        + MAX_ENTRY_MARKOUT_OBSERVATION_LAG_MS
                        + 1,
                        "101",
                    ),
                ),
            )
        )

        result = entry_markout_summary(
            journal,
            facts,
            paths,
        )
    finally:
        facts.close()
        journal.close()

    assert result["max_observation_lag_ms"] == 60_000
    horizons = result["by_horizon_ms"]
    assert isinstance(horizons, dict)
    one = horizons["60000"]
    assert isinstance(one, dict)
    assert one["observations"] == 0
    assert one["stale_observed_mark"] == 1
    assert one["missing_observed_mark"] == 0
    assert one["mean_gross_r"] is None


def test_entry_markout_skips_incomplete_paths_and_tracks_missing_fact(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    try:
        incomplete = _trade(
            suffix="incomplete",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            closed_at_ms=2_000_000,
        )
        missing_fact = _trade(
            suffix="missing-fact",
            direction=Direction.LONG,
            opened_at_ms=3_000_000,
            closed_at_ms=4_000_000,
        )
        journal.record_trade(incomplete)
        journal.record_trade(missing_fact)
        facts.record_decision_fact(
            _fact(incomplete, lead_strategy="trend")
        )
        paths.record(
            _path(
                incomplete,
                ((1_060_000, "101"),),
                complete=False,
            )
        )
        paths.record(
            _path(
                missing_fact,
                ((3_060_000, "101"),),
            )
        )

        result = entry_markout_summary(
            journal,
            facts,
            paths,
        )
    finally:
        facts.close()
        journal.close()

    assert result["incomplete_paths_skipped"] == 1
    assert result["complete_path_records"] == 1
    assert result["missing_decision_attribution"] == 1
    horizons = result["by_horizon_ms"]
    assert isinstance(horizons, dict)
    one = horizons["60000"]
    assert isinstance(one, dict)
    by_strategy = one["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["unknown"]["observations"] == 1


def test_entry_markout_groups_fresh_scanner_rank_buckets(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        top5 = _trade(
            suffix="top5",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            closed_at_ms=2_000_000,
        )
        lower = _trade(
            suffix="lower",
            direction=Direction.SHORT,
            opened_at_ms=3_000_000,
            closed_at_ms=4_000_000,
        )
        for trade in (top5, lower):
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(trade, lead_strategy="trend")
            )
        ranks.record(_rank(top5, ordinal=4))
        ranks.record(_rank(lower, ordinal=14))
        paths.record(
            _path(
                top5,
                (
                    (1_060_000, "101"),
                    (1_300_000, "102"),
                    (1_900_000, "103"),
                ),
            )
        )
        paths.record(
            _path(
                lower,
                (
                    (3_060_000, "101"),
                    (3_300_000, "102"),
                    (3_900_000, "103"),
                ),
            )
        )

        result = entry_markout_summary(
            journal,
            facts,
            paths,
            ranks,
        )
    finally:
        facts.close()
        journal.close()

    assert result["missing_rank_attribution"] == 0
    assert result["stale_rank_attribution"] == 0
    assert result["mean_rank_age_ms"] == 30_000
    assert result["max_rank_age_ms"] == 30_000

    horizons = result["by_horizon_ms"]
    assert isinstance(horizons, dict)
    one = horizons["60000"]
    assert isinstance(one, dict)
    grouped = one["by_scanner_rank_bucket"]
    assert isinstance(grouped, dict)
    assert grouped["1-5"]["observations"] == 1
    assert grouped["1-5"]["mean_gross_r"] == "0.1"
    assert grouped["11-20"]["observations"] == 1
    assert grouped["11-20"]["mean_gross_r"] == "-0.1"


def test_entry_markout_tracks_missing_and_stale_scanner_rank(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    paths = ContinuousPaperTradePathStore(
        tmp_path / "trade-paths"
    )
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        missing = _trade(
            suffix="rank-missing",
            direction=Direction.LONG,
            opened_at_ms=1_000_000,
            closed_at_ms=2_000_000,
        )
        stale = _trade(
            suffix="rank-stale",
            direction=Direction.LONG,
            opened_at_ms=3_000_000,
            closed_at_ms=4_000_000,
        )
        for trade in (missing, stale):
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(trade, lead_strategy="trend")
            )
            paths.record(
                _path(
                    trade,
                    (
                        (trade.opened_at_ms + 60_000, "101"),
                        (trade.opened_at_ms + 300_000, "102"),
                        (trade.opened_at_ms + 900_000, "103"),
                    ),
                )
            )
        ranks.record(
            _rank(
                stale,
                ordinal=15,
                age_ms=300_001,
            )
        )

        result = entry_markout_summary(
            journal,
            facts,
            paths,
            ranks,
        )
    finally:
        facts.close()
        journal.close()

    assert result["missing_rank_attribution"] == 1
    assert result["stale_rank_attribution"] == 1
    one = result["by_horizon_ms"]["60000"]
    grouped = one["by_scanner_rank_bucket"]
    assert grouped["unknown"]["observations"] == 1
    assert grouped["stale"]["observations"] == 1
