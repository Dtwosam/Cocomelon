from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V3,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    execution_learning_record,
    prospective_learning_record,
    sync_prospective_learning_evidence,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveEvidenceStore,
    ProspectiveObservation,
    ProspectiveOutcome,
)
from cocomelon.research.prospective_context_report import HYPE_PROSPECTIVE_VALIDATION_V3

HYPE = MarketId("", "HYPE")
SPEC = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V3
PLAN = HYPE_PROSPECTIVE_VALIDATION_V3
HOUR_MS = 3_600_000


def _prospective_trade() -> tuple[ProspectiveObservation, ProspectiveOutcome]:
    anchor = PLAN.first_expected_anchor_ms
    target = anchor + SPEC.horizon_ms
    observation = ProspectiveObservation(
        candidate_spec_id=SPEC.spec_id,
        raw_decision_id="raw-decision-1",
        market=HYPE,
        decision_as_of_ms=anchor + 1_000,
        source_received_at_ms=anchor + 500,
        anchor_end_ms=anchor,
        target_end_ms=target,
        raw_direction=Direction.LONG,
        effective_direction=Direction.LONG,
        hold_until_ms=target,
        context_state_1h=SPEC.context_state_1h,
        feature_snapshot_id="feature-1",
        cross_market_snapshot_id="cross-1",
        entry_candle_id="entry-candle-1",
        entry_px=Decimal("50"),
        modeled_cost_fraction=Decimal("0.0016"),
        reason_codes=("frozen_historical_context_match",),
    )
    outcome = ProspectiveOutcome(
        candidate_spec_id=SPEC.spec_id,
        observation_id=observation.observation_id,
        market=HYPE,
        anchor_end_ms=anchor,
        target_end_ms=target,
        direction=Direction.LONG,
        entry_px=Decimal("50"),
        exit_px=Decimal("55"),
        exit_candle_id="exit-candle-1",
        exit_source_received_at_ms=target + 1_000,
        gross_return=Decimal("0.1"),
        modeled_cost_fraction=Decimal("0.0016"),
        net_return=Decimal("0.0984"),
    )
    return observation, outcome


def _journal_trade() -> TradeJournalEntry:
    return TradeJournalEntry(
        market=MarketId("", "SOL"),
        direction=Direction.SHORT,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id="feature-live-1",
        strategy_decision_id="strategy-live-1",
        risk_decision_id="risk-live-1",
        opening_plan_id="plan-open-live-1",
        opening_attempt_id="attempt-open-live-1",
        exit_plan_ids=("plan-close-live-1",),
        exit_attempt_ids=("attempt-close-live-1",),
        fill_ids=("fill-open-live-1", "fill-close-live-1"),
        position_action_ids=("action-close-live-1",),
        funding_event_ids=("funding-live-1",),
        initial_stop=Decimal("105"),
        initial_risk_amount=Decimal("25"),
        entry_price=Decimal("100"),
        exit_price=Decimal("99"),
        filled_quantity=Decimal("10"),
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.4455"),
        funding_cash_pnl=Decimal("-0.10"),
        net_pnl=Decimal("9.0045"),
        entry_slippage_amount=Decimal("0.10"),
        exit_slippage_amount=Decimal("0.20"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.002"),
        holding_duration_ms=10_000,
        mfe=None,
        mae=None,
        net_r=Decimal("0.36018"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10009.0045"),
        exit_reason="exit_thesis",
        health_refs=("execution-healthy",),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        replay_run_id="run-live-1",
    )


def test_prospective_outcome_is_quarantined_until_campaign_finalization(
    tmp_path: Path,
) -> None:
    observation, outcome = _prospective_trade()
    source = ProspectiveEvidenceStore(tmp_path / "source", spec=SPEC)
    source.record_observation(observation)
    source.record_outcome(outcome)
    ledger = LearningEvidenceLedger(tmp_path / "learning")

    result = sync_prospective_learning_evidence(
        source,
        ledger,
        spec=SPEC,
        plan=PLAN,
    )

    assert result.scanned_outcomes == 1
    assert result.created_records == 1
    assert result.existing_records == 0
    record = ledger.iter_records()[0]
    assert record.kind is LearningEvidenceKind.PROSPECTIVE_PAPER
    assert record.candidate_id == SPEC.candidate_id
    assert record.candidate_spec_id == SPEC.spec_id
    assert record.campaign_id == source.manifest.campaign_id
    assert record.context_state_1h == SPEC.context_state_1h
    assert record.net_return_fraction == Decimal("0.0984")
    assert record.research_eligible_at_ms == PLAN.finalization_not_before_ms
    assert ledger.eligible_records(as_of_ms=PLAN.finalization_not_before_ms - 1) == ()
    assert ledger.quarantined_records(
        as_of_ms=PLAN.finalization_not_before_ms - 1
    ) == (record,)
    assert ledger.eligible_records(
        as_of_ms=PLAN.finalization_not_before_ms
    ) == (record,)


def test_prospective_sync_is_idempotent(tmp_path: Path) -> None:
    observation, outcome = _prospective_trade()
    source = ProspectiveEvidenceStore(tmp_path / "source", spec=SPEC)
    source.record_observation(observation)
    source.record_outcome(outcome)
    ledger = LearningEvidenceLedger(tmp_path / "learning")

    first = sync_prospective_learning_evidence(source, ledger, spec=SPEC, plan=PLAN)
    second = sync_prospective_learning_evidence(source, ledger, spec=SPEC, plan=PLAN)

    assert first.created_records == 1
    assert second.created_records == 0
    assert second.existing_records == 1
    assert len(ledger.iter_records()) == 1


def test_prospective_adapter_rejects_mismatched_outcome() -> None:
    observation, outcome = _prospective_trade()
    wrong = ProspectiveOutcome(
        candidate_spec_id=SPEC.spec_id,
        observation_id="different-observation",
        market=HYPE,
        anchor_end_ms=outcome.anchor_end_ms,
        target_end_ms=outcome.target_end_ms,
        direction=Direction.LONG,
        entry_px=outcome.entry_px,
        exit_px=outcome.exit_px,
        exit_candle_id=outcome.exit_candle_id,
        exit_source_received_at_ms=outcome.exit_source_received_at_ms,
        gross_return=outcome.gross_return,
        modeled_cost_fraction=outcome.modeled_cost_fraction,
        net_return=outcome.net_return,
    )

    with pytest.raises(ValueError, match="does not match prospective observation"):
        prospective_learning_record(
            SPEC,
            PLAN,
            campaign_id="campaign-1",
            observation=observation,
            outcome=wrong,
        )


def test_execution_learning_preserves_real_execution_costs() -> None:
    trade = _journal_trade()
    record = execution_learning_record(
        trade,
        candidate_id="future-sol-short",
        kind=LearningEvidenceKind.LIVE_EXECUTION,
        research_eligible_at_ms=trade.closed_at_ms + HOUR_MS,
    )

    assert record.kind is LearningEvidenceKind.LIVE_EXECUTION
    assert record.source_record_id == trade.trade_id
    assert record.source_evidence_class == EvidenceClass.MICROSTRUCTURE.value
    assert record.net_pnl == Decimal("9.0045")
    assert record.net_r == Decimal("0.36018")
    assert record.entry_fees == Decimal("0.45")
    assert record.exit_fees == Decimal("0.4455")
    assert record.funding_cash_pnl == Decimal("-0.10")
    assert record.entry_slippage_fraction == Decimal("0.001")
    assert record.exit_slippage_fraction == Decimal("0.002")
    assert record.net_return_fraction is None


def test_execution_learning_requires_explicit_future_or_close_eligibility() -> None:
    trade = _journal_trade()

    with pytest.raises(ValueError, match="cannot predate trade close"):
        execution_learning_record(
            trade,
            candidate_id="future-sol-short",
            kind=LearningEvidenceKind.PAPER_EXECUTION,
            research_eligible_at_ms=trade.closed_at_ms - 1,
        )

    with pytest.raises(ValueError, match="paper_execution or live_execution"):
        execution_learning_record(
            trade,
            candidate_id="future-sol-short",
            kind=LearningEvidenceKind.PROSPECTIVE_PAPER,
            research_eligible_at_ms=trade.closed_at_ms,
        )
