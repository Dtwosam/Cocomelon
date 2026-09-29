from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.prospective_post_rollover_risk_outcomes import (
    ProspectivePostRolloverRiskOutcomeError,
    ProspectivePostRolloverRiskOutcomeState,
    prospective_post_rollover_risk_outcome_summary,
)
from tests.test_prospective_daily_loss_lockout_reflow import (
    _opportunity,
)


def _approved(timestamp_ms: int, risk_id: str):
    return replace(
        _opportunity(
            timestamp_ms=timestamp_ms,
            daily_realized_pnl="0",
        ),
        baseline_risk_approved=True,
        baseline_risk_reason_codes=("approved",),
        baseline_risk_decision_id=risk_id,
    )


def _lineage(
    opportunity,
    *,
    plan_id: str,
) -> ContinuousPaperOpeningLineage:
    return ContinuousPaperOpeningLineage(
        opening_plan_id=plan_id,
        feature_snapshot_id=opportunity.feature_snapshot_id,
        market=opportunity.market,
        opened_at_ms=opportunity.opportunity_timestamp_ms + 1_000,
        runtime=ContinuousPaperRuntimeIdentity(
            worker_run_id=1,
            worker_run_attempt=1,
            worker_head_sha="a" * 40,
        ),
    )


def test_state_round_trip_is_strict() -> None:
    state = ProspectivePostRolloverRiskOutcomeState(
        started_at_ms=123
    )
    assert (
        ProspectivePostRolloverRiskOutcomeState.from_payload(
            state.payload()
        )
        == state
    )

    with pytest.raises(
        ProspectivePostRolloverRiskOutcomeError,
        match="canonical fields",
    ):
        ProspectivePostRolloverRiskOutcomeState.from_payload(
            {**state.payload(), "extra": True}
        )


def test_post_rollover_cohort_tracks_risk_and_real_fills_only() -> None:
    state = ProspectivePostRolloverRiskOutcomeState(
        started_at_ms=1_000
    )
    ignored = _opportunity(
        timestamp_ms=900,
        daily_realized_pnl="-120",
    )
    daily_lockout = _opportunity(
        timestamp_ms=1_100,
        daily_realized_pnl="-120",
    )
    filled = _approved(1_200, "risk-approved-filled")
    unfilled = _approved(1_300, "risk-approved-unfilled")
    low_rank_rejection = replace(
        _opportunity(
            timestamp_ms=1_400,
            daily_realized_pnl="-120",
        ),
        rank_ordinal=12,
        baseline_risk_reason_codes=("correlation_bucket_exhausted",),
    )

    lineage = _lineage(filled, plan_id="plan-filled")
    plan = SimpleNamespace(
        plan_id="plan-filled",
        market=filled.risk_request_object.market,
        strategy_decision_id=filled.strategy_decision_id,
        risk_decision_id=filled.baseline_risk_decision_id,
    )

    result = prospective_post_rollover_risk_outcome_summary(
        (
            ignored,
            daily_lockout,
            filled,
            unfilled,
            low_rank_rejection,
        ),
        (lineage,),
        plan_loader=lambda plan_id: (
            plan if plan_id == "plan-filled" else None
        ),
        state=state,
    )

    assert result["opportunities"] == 4
    assert result["risk_approvals"] == 2
    assert result["risk_rejections"] == 2
    assert result["filled_approvals"] == 1
    assert result["approved_without_observed_fill"] == 1
    assert result["daily_loss_lockout_rejections"] == 1
    assert result["by_rejection_reason"] == {
        "correlation_bucket_exhausted": 1,
        "daily_loss_lockout": 1,
    }
    assert result["candidate_eligible_opportunities"] == 3
    assert result["candidate_eligible_risk_approvals"] == 2
    assert result["candidate_eligible_risk_rejections"] == 1
    assert result["candidate_eligible_filled_approvals"] == 1
    assert (
        result[
            "candidate_eligible_daily_loss_lockout_rejections"
        ]
        == 1
    )
    assert result["integrity_clean"] is True
    assert result["replacement_trades_modeled"] is False
    assert result["pnl_modeled"] is False


def test_post_rollover_cohort_fails_integrity_on_missing_fill_plan() -> None:
    state = ProspectivePostRolloverRiskOutcomeState(
        started_at_ms=1_000
    )
    filled = _approved(1_200, "risk-approved-filled")
    lineage = _lineage(filled, plan_id="missing-plan")

    result = prospective_post_rollover_risk_outcome_summary(
        (filled,),
        (lineage,),
        plan_loader=lambda _plan_id: None,
        state=state,
    )

    assert result["lineage_plan_misses"] == 1
    assert result["filled_approvals"] == 0
    assert result["integrity_clean"] is False
