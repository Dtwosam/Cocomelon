from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
from cocomelon.research.prospective_top10_rank_filter import (
    MAX_ACCEPTED_RANK_AGE_MS,
    TOP10_RANK_FILTER_CANDIDATE_ID,
    ProspectiveTop10RankFilterError,
    ProspectiveTop10RankFilterState,
    evaluate_prospective_top10_rank_filter,
)

MARKET = MarketId("", "SOL")
RUN_ID = "continuous-paper-mainnet-v1"


def _trade(
    *,
    suffix: str,
    opened_at_ms: int,
    pnl: str,
) -> TradeJournalEntry:
    value = Decimal(pnl)
    return TradeJournalEntry(
        market=MARKET,
        direction=Direction.LONG,
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
        initial_stop=Decimal("90"),
        initial_risk_amount=Decimal("10"),
        entry_price=Decimal("100"),
        exit_price=Decimal("100") + value,
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


def test_top10_filter_blocks_only_prospective_rank_above_10(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-rank"
    )
    try:
        old = _trade(
            suffix="old",
            opened_at_ms=90_000,
            pnl="-20",
        )
        allowed = _trade(
            suffix="allowed",
            opened_at_ms=110_000,
            pnl="5",
        )
        blocked = _trade(
            suffix="blocked",
            opened_at_ms=120_000,
            pnl="-8",
        )
        for trade in (old, allowed, blocked):
            journal.record_trade(trade)
        ranks.record(_rank(old, ordinal=18))
        ranks.record(_rank(allowed, ordinal=5))
        ranks.record(_rank(blocked, ordinal=15))

        result = evaluate_prospective_top10_rank_filter(
            journal,
            ranks,
            ProspectiveTop10RankFilterState(
                started_at_ms=100_000
            ),
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 2
    assert result["attributed_trades"] == 2
    assert result["missing_rank_evidence"] == 0
    assert result["stale_rank_evidence"] == 0
    assert result["allowed_trades"] == 1
    assert result["blocked_trades"] == 1
    assert result["allowed_wins"] == 1
    assert result["blocked_losses"] == 1
    assert result["allowed_net_pnl"] == "5"
    assert result["blocked_net_pnl"] == "-8"
    assert result["actual_net_pnl"] == "-3"
    assert result["candidate_trade_contribution_pnl"] == "5"
    assert result["delta_trade_contribution_pnl"] == "8"
    robustness = result["robustness"]
    assert isinstance(robustness, dict)
    assert robustness["total_delta_trade_contribution_pnl"] == "8"
    assert robustness["largest_abs_trade_contribution"] == "8"
    assert robustness["changes_readiness_gate"] is False
    residual = result["allowed_residual"]
    assert isinstance(residual, dict)
    residual_overall = residual["overall"]
    assert isinstance(residual_overall, dict)
    assert residual_overall["trades"] == 1
    assert residual_overall["net_pnl"] == "5"
    by_rank = residual["by_rank_band"]
    assert isinstance(by_rank, dict)
    assert by_rank["1-5"]["net_pnl"] == "5"
    assert residual["changes_readiness_gate"] is False
    assert result["allowed_mean_net_r"] == "0.5"
    assert result["blocked_mean_net_r"] == "-0.8"
    assert result["allowed_mean_ordinal"] == "5"
    assert result["blocked_mean_ordinal"] == "15"
    assert result["portfolio_counterfactual"] is False
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False


def test_top10_filter_tracks_missing_and_stale_rank_evidence(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-rank"
    )
    try:
        missing = _trade(
            suffix="missing",
            opened_at_ms=11_000,
            pnl="-1",
        )
        stale = _trade(
            suffix="stale",
            opened_at_ms=500_000,
            pnl="-2",
        )
        journal.record_trade(missing)
        journal.record_trade(stale)
        ranks.record(
            _rank(
                stale,
                ordinal=12,
                age_ms=MAX_ACCEPTED_RANK_AGE_MS + 1,
            )
        )

        result = evaluate_prospective_top10_rank_filter(
            journal,
            ranks,
            ProspectiveTop10RankFilterState(
                started_at_ms=10_000
            ),
        )
    finally:
        journal.close()

    assert result["prospective_closed_trades"] == 2
    assert result["attributed_trades"] == 0
    assert result["missing_rank_evidence"] == 1
    assert result["stale_rank_evidence"] == 1
    readiness = result["readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_review"] is False
    assert (
        readiness["requires_zero_missing_rank_evidence"]
        is True
    )
    assert (
        readiness["requires_zero_stale_rank_evidence"]
        is True
    )


def test_top10_filter_fails_closed_on_rank_trade_mismatch(
    tmp_path: Path,
) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    ranks = ContinuousPaperOpeningRankStore(
        tmp_path / "opening-rank"
    )
    try:
        trade = _trade(
            suffix="mismatch",
            opened_at_ms=20_000,
            pnl="-1",
        )
        journal.record_trade(trade)
        ranks.record(
            ContinuousPaperOpeningRankEvidence(
                opening_plan_id=trade.opening_plan_id,
                market=trade.market.canonical,
                opened_at_ms=trade.opened_at_ms + 1,
                rank_observed_at_ms=trade.opened_at_ms,
                rank_age_ms=1,
                ordinal=12,
                score=Decimal("0.7"),
                rank_pool_size=20,
                reason_codes=("fixture",),
            )
        )

        with pytest.raises(
            ProspectiveTop10RankFilterError,
            match="does not match trade",
        ):
            evaluate_prospective_top10_rank_filter(
                journal,
                ranks,
                ProspectiveTop10RankFilterState(
                    started_at_ms=10_000
                ),
            )
    finally:
        journal.close()


def test_top10_filter_state_round_trip_preserves_frozen_rule() -> None:
    state = ProspectiveTop10RankFilterState(started_at_ms=123)
    restored = ProspectiveTop10RankFilterState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.candidate_id == TOP10_RANK_FILTER_CANDIDATE_ID

    payload = state.payload()
    rule = payload["rule"]
    assert isinstance(rule, dict)
    rule["max_admitted_ordinal"] = 12

    with pytest.raises(
        ProspectiveTop10RankFilterError,
        match="frozen candidate",
    ):
        ProspectiveTop10RankFilterState.from_payload(payload)
