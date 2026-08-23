from __future__ import annotations

import hashlib

from cocomelon.domain.execution import ExecutionAttempt
from cocomelon.domain.journal import JournalObservation, ObservationKind
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import StrategyDecision


def observation_from_strategy(
    decision: StrategyDecision,
    *,
    replay_run_id: str | None,
) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.STRATEGY_DECISION,
        timestamp_ms=decision.timestamp_ms,
        market=decision.market,
        feature_snapshot_id=decision.feature_snapshot_id,
        strategy_decision_id=decision.decision_id,
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=decision.reason_codes,
        health_refs=(),
        replay_run_id=replay_run_id,
    )


def observation_from_risk(
    decision: RiskDecision,
    *,
    replay_run_id: str | None,
) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.RISK_DECISION,
        timestamp_ms=decision.timestamp_ms,
        market=decision.market,
        feature_snapshot_id=None,
        strategy_decision_id=decision.strategy_decision_id,
        risk_decision_id=decision.risk_decision_id,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=decision.reason_codes,
        health_refs=(),
        replay_run_id=replay_run_id,
    )


def observation_from_execution(
    attempt: ExecutionAttempt,
    *,
    replay_run_id: str | None,
) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.EXECUTION_ATTEMPT,
        timestamp_ms=attempt.attempt_timestamp_ms,
        market=None,
        feature_snapshot_id=None,
        strategy_decision_id=None,
        risk_decision_id=None,
        plan_id=attempt.plan_id,
        attempt_id=attempt.attempt_id,
        position_action_id=None,
        account_state_id=None,
        reason_codes=attempt.reason_codes,
        health_refs=(),
        replay_run_id=replay_run_id,
    )


def should_sample_no_trade(
    decision_id: str,
    *,
    numerator: int,
    denominator: int,
) -> bool:
    if not decision_id.strip():
        raise ValueError("decision_id must not be empty")
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0 or numerator > denominator:
        raise ValueError("numerator must be between 0 and denominator")
    if numerator == 0:
        return False
    if numerator == denominator:
        return True
    bucket = int.from_bytes(hashlib.sha256(decision_id.encode("utf-8")).digest()[:8], "big")
    return bucket % denominator < numerator
