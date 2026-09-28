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
from cocomelon.research.prospective_combined_entry_filter import (
    COMBINED_FILTER_CANDIDATE_ID,
    MAX_ACCEPTED_RANK_AGE_MS,
    ProspectiveCombinedEntryFilterError,
    ProspectiveCombinedEntryFilterState,
    evaluate_prospective_combined_entry_filter,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    direction: Direction,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    value = Decimal(pnl)
    entry = Decimal("100")
    exit_price = (
        entry + value
        if direction is Direction.LONG
        else entry - value
    )
    return TradeJournalEntry(
        market=MARKET,
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
