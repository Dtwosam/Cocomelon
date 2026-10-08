from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

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
from cocomelon.research.profit_lock_counterfactual import (
    ProfitLockTradeOutcome,
)
from cocomelon.research.prospective_combined_entry_filter import (
    COMBINED_FILTER_CANDIDATE_ID,
    MAX_ACCEPTED_RANK_AGE_MS,
    ProspectiveCombinedEntryFilterError,
    ProspectiveCombinedEntryFilterState,
    evaluate_prospective_combined_entry_filter,
    evaluate_prospective_combined_matched_overlap,
    prospective_combined_block_reason,
)
from cocomelon.research.prospective_entry_filter import (
    ProspectiveEntryFilterState,
)
from cocomelon.research.prospective_trend_outside_top10 import (
    ProspectiveTrendOutsideTop10Error,
    ProspectiveTrendOutsideTop10State,
    prospective_trend_outside_top10_comparison,
)
from cocomelon.research.prospective_top10_rank_filter import (
    ProspectiveTop10RankFilterState,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
    market: str = "SOL",
) -> TradeJournalEntry:
    value = Decimal(pnl)
    entry = Decimal("100")
    exit_price = (
        entry + value
        if direction is Direction.LONG
        else entry - value
    )
    return TradeJournalEntry(
        market=MarketId("", market),
        direction=direction,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 60_000,
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
        filled_quantity=Decimal("1"),
        gross_realized_pnl=value,
        entry_fees=Decimal("0"),
        exit_fees=Decimal("0"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=value,
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        entry_slippage_fraction=Decimal("0"),
        exit_slippage_fraction=Decimal("0"),
        holding_duration_ms=60_000,
        mfe=None,
        mae=None,
        net_r=value / Decimal("10"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10000") + value,
        exit_reason="fixture",
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
    age_ms: int = 1_000,
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


def test_combined_filter_requires_both_frozen_conditions(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        old = _trade(
            suffix="old",
            direction=Direction.LONG,
            opened_at_ms=90_000,
            pnl="-20",
        )
        long_trend_top10 = _trade(
            suffix="long-trend",
            direction=Direction.LONG,
            opened_at_ms=110_000,
            pnl="-8",
        )
        short_trend_low_rank = _trade(
            suffix="rank",
            direction=Direction.SHORT,
            opened_at_ms=120_000,
            pnl="-6",
        )
        long_trend_low_rank = _trade(
            suffix="both",
            direction=Direction.LONG,
            opened_at_ms=130_000,
            pnl="-7",
        )
        allowed = _trade(
            suffix="allowed",
            direction=Direction.SHORT,
            opened_at_ms=140_000,
            pnl="5",
        )
        rows = (
            (old, "trend", 15),
            (long_trend_top10, "trend", 5),
            (short_trend_low_rank, "trend", 15),
            (long_trend_low_rank, "trend", 16),
            (allowed, "breakout", 4),
        )
        for trade, strategy, ordinal in rows:
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(trade, lead_strategy=strategy)
            )
            ranks.record(_rank(trade, ordinal=ordinal))

        result = evaluate_prospective_combined_entry_filter(
            journal,
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(
                started_at_ms=100_000
            ),
        )
    finally:
        facts.close()
        journal.close()

    assert result["prospective_closed_trades"] == 4
    assert result["attributed_trades"] == 4
    assert result["allowed_trades"] == 1
    assert result["blocked_trades"] == 3
    assert result["allowed_net_pnl"] == "5"
    assert result["blocked_net_pnl"] == "-21"
    assert result["actual_net_pnl"] == "-16"
    assert result["candidate_trade_contribution_pnl"] == "5"
    assert result["delta_trade_contribution_pnl"] == "21"
    robustness = result["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["total_delta_trade_contribution_pnl"] == "21"
    assert robustness["leave_one_trade_out_min_delta"] == "13"
    assert robustness["changes_readiness_gate"] is False
    residual = result["allowed_residual"]
    assert isinstance(residual, dict)
    residual_overall = residual["overall"]
    assert isinstance(residual_overall, dict)
    assert residual_overall["trades"] == 1
    assert residual_overall["net_pnl"] == "5"
    by_strategy = residual["by_lead_strategy"]
    assert isinstance(by_strategy, dict)
    assert by_strategy["breakout"]["net_pnl"] == "5"
    by_rank = residual["by_rank_band"]
    assert isinstance(by_rank, dict)
    assert by_rank["1-5"]["net_pnl"] == "5"
    assert residual["changes_readiness_gate"] is False
    portfolio = result["fixed_schedule_portfolio"]
    assert isinstance(portfolio, dict)
    assert portfolio["attributed_trades"] == 4
    assert portfolio["admitted_trades"] == 1
    assert portfolio["blocked_trades"] == 3
    actual_timeline = portfolio["actual"]
    candidate_timeline = portfolio["candidate"]
    assert isinstance(actual_timeline, dict)
    assert isinstance(candidate_timeline, dict)
    assert actual_timeline["final_realized_contribution"] == "-16"
    assert candidate_timeline["final_realized_contribution"] == "5"
    assert portfolio["delta_final_realized_contribution"] == "21"
    assert portfolio["replacement_trades_modeled"] is False
    assert portfolio["candidate_equity_resizing_modeled"] is False
    assert portfolio["changes_readiness_gate"] is False

    reasons = result["by_block_reason"]
    assert isinstance(reasons, dict)
    assert reasons["long_trend"]["trades"] == 1
    assert reasons["long_trend"]["net_pnl"] == "-8"
    assert reasons["rank_above_10"]["trades"] == 1
    assert reasons["rank_above_10"]["net_pnl"] == "-6"
    assert reasons["long_trend_and_rank_above_10"]["trades"] == 1
    assert (
        reasons["long_trend_and_rank_above_10"]["net_pnl"]
        == "-7"
    )


def test_combined_filter_matched_overlap_uses_later_standalone_start(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        entry_only_history = _trade(
            suffix="entry-only-history",
            direction=Direction.LONG,
            opened_at_ms=110_000,
            pnl="-8",
        )
        rank_blocked = _trade(
            suffix="rank-overlap",
            direction=Direction.SHORT,
            opened_at_ms=120_000,
            pnl="-6",
        )
        blocked_by_both = _trade(
            suffix="both-overlap",
            direction=Direction.LONG,
            opened_at_ms=130_000,
            pnl="-7",
        )
        allowed = _trade(
            suffix="allowed-overlap",
            direction=Direction.SHORT,
            opened_at_ms=140_000,
            pnl="5",
        )
        rows = (
            (entry_only_history, "trend", 5),
            (rank_blocked, "trend", 15),
            (blocked_by_both, "trend", 16),
            (allowed, "breakout", 4),
        )
        for trade, strategy, ordinal in rows:
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(trade, lead_strategy=strategy)
            )
            ranks.record(_rank(trade, ordinal=ordinal))

        result = evaluate_prospective_combined_matched_overlap(
            journal,
            facts,
            ranks,
            ProspectiveEntryFilterState(started_at_ms=100_000),
            ProspectiveTop10RankFilterState(
                started_at_ms=115_000
            ),
        )
    finally:
        facts.close()
        journal.close()

    assert result["descriptive_only"] is True
    assert result["changes_readiness_gate"] is False
    assert result["fresh_combined_gate_credit"] == 0
    assert result["entry_filter_started_at_ms"] == 100_000
    assert result["top10_rank_filter_started_at_ms"] == 115_000
    assert result["overlap_started_at_ms"] == 115_000
    assert result["closed_trades_since_overlap_start"] == 3
    assert result["matched_trades"] == 3
    assert result["integrity_clean"] is True
    assert result["allowed_trades"] == 1
    assert result["blocked_trades"] == 2
    assert result["actual_net_pnl"] == "-8"
    assert result["candidate_trade_contribution_pnl"] == "5"
    assert result["delta_trade_contribution_pnl"] == "13"
    reasons = result["by_block_reason"]
    assert isinstance(reasons, dict)
    assert reasons["rank_above_10"]["net_pnl"] == "-6"
    assert (
        reasons["long_trend_and_rank_above_10"]["net_pnl"]
        == "-7"
    )

def test_combined_filter_tracks_decision_rank_and_stale_misses(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        missing_fact = _trade(
            suffix="fact",
            direction=Direction.LONG,
            opened_at_ms=110_000,
            pnl="-1",
        )
        missing_rank = _trade(
            suffix="rank",
            direction=Direction.SHORT,
            opened_at_ms=120_000,
            pnl="-1",
        )
        stale = _trade(
            suffix="stale",
            direction=Direction.SHORT,
            opened_at_ms=500_000,
            pnl="-1",
        )
        for trade in (missing_fact, missing_rank, stale):
            journal.record_trade(trade)
        facts.record_decision_fact(
            _fact(missing_rank, lead_strategy="trend")
        )
        facts.record_decision_fact(
            _fact(stale, lead_strategy="trend")
        )
        ranks.record(
            _rank(
                stale,
                ordinal=5,
                age_ms=MAX_ACCEPTED_RANK_AGE_MS + 1,
            )
        )

        result = evaluate_prospective_combined_entry_filter(
            journal,
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(
                started_at_ms=100_000
            ),
        )
    finally:
        facts.close()
        journal.close()

    assert result["prospective_closed_trades"] == 3
    assert result["attributed_trades"] == 0
    assert result["decision_attribution_misses"] == 1
    assert result["missing_rank_evidence"] == 1
    assert result["stale_rank_evidence"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["integrity_clean"] is False
    assert readiness["ready_for_review"] is False


def test_combined_filter_fails_closed_on_rank_lineage_mismatch(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        trade = _trade(
            suffix="mismatch",
            direction=Direction.SHORT,
            opened_at_ms=120_000,
            pnl="-1",
        )
        journal.record_trade(trade)
        facts.record_decision_fact(
            _fact(trade, lead_strategy="trend")
        )
        ranks.record(
            ContinuousPaperOpeningRankEvidence(
                opening_plan_id=trade.opening_plan_id,
                market=trade.market.canonical,
                opened_at_ms=trade.opened_at_ms + 1,
                rank_observed_at_ms=trade.opened_at_ms,
                rank_age_ms=1,
                ordinal=5,
                score=Decimal("0.7"),
                rank_pool_size=20,
                reason_codes=("fixture",),
            )
        )

        with pytest.raises(
            ProspectiveCombinedEntryFilterError,
            match="rank lineage",
        ):
            evaluate_prospective_combined_entry_filter(
                journal,
                facts,
                ranks,
                ProspectiveCombinedEntryFilterState(
                    started_at_ms=100_000
                ),
            )
    finally:
        facts.close()
        journal.close()


def test_combined_filter_state_round_trip_locks_rule() -> None:
    state = ProspectiveCombinedEntryFilterState(
        started_at_ms=123
    )
    restored = ProspectiveCombinedEntryFilterState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.candidate_id == COMBINED_FILTER_CANDIDATE_ID

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["max_admitted_ordinal"] = 12

    with pytest.raises(
        ProspectiveCombinedEntryFilterError,
        match="frozen candidate",
    ):
        ProspectiveCombinedEntryFilterState.from_payload(payload)


def test_combined_filter_crosses_allowed_losses_with_profit_lock_paths(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        allowed_loss = _trade(
            suffix="allowed-profit-lock",
            direction=Direction.SHORT,
            opened_at_ms=120_000,
            pnl="-6",
        )
        blocked_loss = _trade(
            suffix="blocked-profit-lock",
            direction=Direction.LONG,
            opened_at_ms=130_000,
            pnl="-8",
        )
        for trade, strategy, ordinal in (
            (allowed_loss, "breakout", 4),
            (blocked_loss, "trend", 5),
        ):
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(trade, lead_strategy=strategy)
            )
            ranks.record(_rank(trade, ordinal=ordinal))

        candidate = Decimal("-1")
        outcome = ProfitLockTradeOutcome(
            trade_id=allowed_loss.trade_id,
            market=allowed_loss.market.canonical,
            direction=allowed_loss.direction.value,
            rule_id="breakeven_after_0_5r",
            activated=True,
            activation_timestamp_ms=121_000,
            triggered=True,
            trigger_timestamp_ms=122_000,
            trigger_mark_px=Decimal("100"),
            actual_net_pnl=allowed_loss.net_pnl,
            actual_net_r=allowed_loss.net_r,
            candidate_net_pnl_estimate=candidate,
            candidate_net_r_estimate=(
                candidate / allowed_loss.initial_risk_amount
            ),
            delta_net_pnl_estimate=(
                candidate - allowed_loss.net_pnl
            ),
            delta_net_r_estimate=(
                candidate / allowed_loss.initial_risk_amount
                - allowed_loss.net_r
            ),
            used_actual_close=False,
        )

        result = evaluate_prospective_combined_entry_filter(
            journal,
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(
                started_at_ms=100_000
            ),
            profit_lock_outcomes=(outcome,),
        )
    finally:
        facts.close()
        journal.close()

    residual = result["residual_profit_lock"]
    assert isinstance(residual, dict)
    assert residual["allowed_trades"] == 1
    assert residual["residual_loss_trades"] == 1
    by_rule = residual["by_rule"]
    assert isinstance(by_rule, dict)
    breakeven = by_rule["breakeven_after_0_5r"]
    assert breakeven["matched_exact_path_losses"] == 1
    assert breakeven["missing_exact_path_losses"] == 0
    assert breakeven["triggered_losses"] == 1
    assert breakeven["delta_net_pnl_estimate"] == "5"
    lock = by_rule["lock_0_5r_after_1r"]
    assert lock["matched_exact_path_losses"] == 0
    assert lock["missing_exact_path_losses"] == 1
    assert residual["changes_readiness_gate"] is False


def test_combined_block_reason_is_reusable_for_observed_opportunities() -> None:
    assert (
        prospective_combined_block_reason(
            direction=Direction.LONG,
            lead_strategy="trend",
            ordinal=4,
        )
        == "long_trend"
    )
    assert (
        prospective_combined_block_reason(
            direction=Direction.SHORT,
            lead_strategy="trend",
            ordinal=11,
        )
        == "rank_above_10"
    )
    assert (
        prospective_combined_block_reason(
            direction=Direction.LONG,
            lead_strategy="trend",
            ordinal=11,
        )
        == "long_trend_and_rank_above_10"
    )
    assert (
        prospective_combined_block_reason(
            direction=Direction.SHORT,
            lead_strategy="breakout",
            ordinal=4,
        )
        is None
    )


def test_combined_filter_requires_profitable_robust_economics(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        for index in range(30):
            allowed = index < 20
            market = "SOL" if index % 2 == 0 else "ETH"
            direction = (
                Direction.LONG
                if index % 2 == 0
                else Direction.SHORT
            )
            trade = _trade(
                suffix=f"economic-ready-{index}",
                direction=direction,
                opened_at_ms=120_000 + index * 120_000,
                pnl="2" if allowed else "-1",
                market=market,
            )
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(trade, lead_strategy="breakout")
            )
            ranks.record(
                _rank(
                    trade,
                    ordinal=4 if allowed else 15,
                )
            )

        result = evaluate_prospective_combined_entry_filter(
            journal,
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(
                started_at_ms=100_000
            ),
        )
    finally:
        facts.close()
        journal.close()

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["candidate_profitable"] is True
    assert readiness["improvement_positive"] is True
    assert readiness["candidate_single_trade_robust"] is True
    assert readiness["candidate_single_market_robust"] is True
    assert readiness["delta_single_trade_robust"] is True
    assert readiness["delta_single_market_robust"] is True
    assert readiness["economics_positive"] is True
    assert readiness["single_trade_robust"] is True
    assert readiness["single_market_robust"] is True
    assert readiness["ready_for_review"] is True
    assert result["candidate_trade_contribution_pnl"] == "40"
    assert result["delta_trade_contribution_pnl"] == "10"
    assert result["candidate_net_r"] == "4.0"
    assert result["delta_net_r"] == "1.0"


def test_combined_filter_rejects_less_bad_losing_candidate(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    facts = EvaluationFactStore(tmp_path / "facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-ranks"
    )
    try:
        for index in range(30):
            allowed = index < 20
            market = "SOL" if index % 2 == 0 else "ETH"
            trade = _trade(
                suffix=f"economic-losing-{index}",
                direction=(
                    Direction.LONG
                    if index % 2 == 0
                    else Direction.SHORT
                ),
                opened_at_ms=120_000 + index * 120_000,
                pnl="-1" if allowed else "-2",
                market=market,
            )
            journal.record_trade(trade)
            facts.record_decision_fact(
                _fact(trade, lead_strategy="breakout")
            )
            ranks.record(
                _rank(
                    trade,
                    ordinal=4 if allowed else 15,
                )
            )

        result = evaluate_prospective_combined_entry_filter(
            journal,
            facts,
            ranks,
            ProspectiveCombinedEntryFilterState(
                started_at_ms=100_000
            ),
        )
    finally:
        facts.close()
        journal.close()

    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["candidate_profitable"] is False
    assert readiness["improvement_positive"] is True
    assert readiness["economics_positive"] is False
    assert readiness["ready_for_review"] is False
    assert result["candidate_trade_contribution_pnl"] == "-20"
    assert result["delta_trade_contribution_pnl"] == "20"


def _targeted_trend_rank_fixture(
    tmp_path: Path,
    *,
    blocked_pnl: str = "-4",
    nontrend_outside_pnl: str = "5",
    missing_rank_index: int | None = None,
) -> tuple[
    tuple[TradeJournalEntry, ...],
    EvaluationFactStore,
    ContinuousPaperOpeningRankStore,
    ProspectiveTrendOutsideTop10State,
]:
    facts = EvaluationFactStore(tmp_path / "trend-facts.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(tmp_path / "trend-ranks")
    state = ProspectiveTrendOutsideTop10State(
        frozen_at_ms=1_000_000
    )
    trades: list[TradeJournalEntry] = []
    for i in range(80):
        kind = i % 4
        blocked = kind == 0
        rank_outside = kind in (0, 1)
        strategy = "trend" if kind in (0, 2) else "breakout"
        value = (
            blocked_pnl if blocked
            else (
                nontrend_outside_pnl
                if kind == 1 else "3"
            )
        )
        trade = _trade(
            suffix=f"trend-rank-{i}",
            direction=(
                Direction.LONG if (i // 4) % 2 == 0
                else Direction.SHORT
            ),
            opened_at_ms=(
                state.started_at_ms + 60_000 + i * 120_000
            ),
            pnl=value,
            market=("SOL", "BTC", "ETH", "ADA", "JUP")[i % 5],
        )
        trades.append(trade)
        facts.record_decision_fact(
            _fact(trade, lead_strategy=strategy)
        )
        if i != missing_rank_index:
            ranks.record(_rank(
                trade,
                ordinal=15 if rank_outside else 3,
            ))
    return tuple(trades), facts, ranks, state


def test_frozen_trend_outside_top10_keeps_both_sides_and_nontrend_winners(
    tmp_path: Path,
) -> None:
    trades, facts, ranks, state = _targeted_trend_rank_fixture(tmp_path)
    try:
        report = prospective_trend_outside_top10_comparison(
            trades, facts, ranks, state
        )
        assert report["prospective_closed_trades"] == 80
        assert report["fully_attributed_future_trades"] == 80
        assert report["integrity_clean"] is True
        assert report["blocked_targeted_trades"] == 20
        assert report["blocked_targeted_losers"] == 20
        assert report["blocked_targeted_winners"] == 0
        assert report["retained_outside_top10_nontrend_trades"] == 20
        assert report["retained_outside_top10_nontrend_winners"] == 20
        assert report["overall"]["targeted_net_pnl"] == "220"
        assert report["overall"]["actual_net_pnl"] == "140"
        assert report["overall"]["broad_top10_net_pnl"] == "120"
        assert report["overall"]["targeted_minus_actual_net_pnl"] == "80"
        assert report["overall"]["targeted_minus_broad_net_pnl"] == "100"
        assert report["strict_descriptive_screen_passes"] is True
        assert report["by_direction"]["long"][
            "targeted_absolutely_profitable"
        ] is True
        assert report["by_direction"]["short"][
            "targeted_absolutely_profitable"
        ] is True
        assert all(
            b["passes"] is True
            for b in report["chronological_blocks"]
        )
        assert report["execution_authority"] is False
        assert report["promotion_authority"] is False
        assert report["selected_winner"] is None
    finally:
        facts.close()


def test_frozen_trend_outside_top10_rejects_stolen_winner_advantage(
    tmp_path: Path,
) -> None:
    trades, facts, ranks, state = _targeted_trend_rank_fixture(
        tmp_path, blocked_pnl="9"
    )
    try:
        report = prospective_trend_outside_top10_comparison(
            trades, facts, ranks, state
        )
        assert report["blocked_targeted_winners"] == 20
        assert report["overall"]["targeted_beats_actual"] is False
        assert report["strict_descriptive_screen_passes"] is False
    finally:
        facts.close()


def test_frozen_trend_outside_top10_fails_closed_on_missing_rank(
    tmp_path: Path,
) -> None:
    trades, facts, ranks, state = _targeted_trend_rank_fixture(
        tmp_path, missing_rank_index=4
    )
    try:
        report = prospective_trend_outside_top10_comparison(
            trades, facts, ranks, state
        )
        assert report["missing_rank"] == 1
        assert report["integrity_clean"] is False
        assert report["strict_descriptive_screen_passes"] is False
    finally:
        facts.close()


def test_frozen_trend_outside_top10_detects_duplicate_and_future_trade(
    tmp_path: Path,
) -> None:
    trades, facts, ranks, state = _targeted_trend_rank_fixture(tmp_path)
    try:
        with pytest.raises(
            ProspectiveTrendOutsideTop10Error,
            match="duplicate trade IDs",
        ):
            prospective_trend_outside_top10_comparison(
                (*trades, trades[0]), facts, ranks, state
            )
        # A pre-embargo close can never vote in the frozen future cohort.
        historical = _trade(
            suffix="old-trend",
            direction=Direction.SHORT,
            opened_at_ms=state.frozen_at_ms,
            pnl="-900",
        )
        future = prospective_trend_outside_top10_comparison(
            (*trades, historical), facts, ranks, state
        )
        assert future["prospective_closed_trades"] == 80
    finally:
        facts.close()


def test_frozen_trend_outside_top10_state_refuses_retrospective_drift() -> None:
    state = ProspectiveTrendOutsideTop10State(frozen_at_ms=100_000)
    assert state.started_at_ms == 100_000 + 6 * 3_600_000
    assert ProspectiveTrendOutsideTop10State.from_payload(
        state.payload()
    ) == state
    tampered = state.payload()
    tampered["rule"]["direction_policy"] = "short_only"
    with pytest.raises(
        ProspectiveTrendOutsideTop10Error,
        match="rule or retrospective provenance drift",
    ):
        ProspectiveTrendOutsideTop10State.from_payload(tampered)
    old = state.payload()
    old["historical_hypothesis_only"][
        "retrospective_skip_only_delta_usd"
    ] = "1000"
    with pytest.raises(ProspectiveTrendOutsideTop10Error):
        ProspectiveTrendOutsideTop10State.from_payload(old)
