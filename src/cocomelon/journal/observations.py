from __future__ import annotations

import hashlib
import json

from cocomelon.domain.execution import ExecutionAttempt, PositionAction
from cocomelon.domain.journal import JournalObservation, ObservationKind
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import StrategyDecision
from cocomelon.execution.funding import FundingAccrual, FundingGap


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _position_action_id(action: PositionAction) -> str:
    return _digest(
        {
            "action_type": action.action_type.value,
            "market": action.market.canonical,
            "quantity": None if action.quantity is None else str(action.quantity),
            "new_stop_price": (
                None if action.new_stop_price is None else str(action.new_stop_price)
            ),
            "reason_codes": action.reason_codes,
            "timestamp_ms": action.timestamp_ms,
        }
    )


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


def observation_from_position_action(
    action: PositionAction,
    *,
    replay_run_id: str | None,
) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.POSITION_ACTION,
        timestamp_ms=action.timestamp_ms,
        market=action.market,
        feature_snapshot_id=None,
        strategy_decision_id=None,
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=_position_action_id(action),
        account_state_id=None,
        reason_codes=action.reason_codes,
        health_refs=(),
        replay_run_id=replay_run_id,
    )


def observation_from_funding_accrual(
    accrual: FundingAccrual,
    *,
    replay_run_id: str | None,
) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.FUNDING_EVENT,
        timestamp_ms=accrual.boundary_ms,
        market=accrual.market,
        feature_snapshot_id=None,
        strategy_decision_id=None,
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=(),
        health_refs=(
            f"oracle_event:{accrual.oracle_event_key}",
            f"funding_source:{accrual.funding_source}",
        ),
        replay_run_id=replay_run_id,
        funding_event_id=accrual.accrual_id,
    )


def observation_from_funding_gap(
    gap: FundingGap,
    *,
    replay_run_id: str | None,
) -> JournalObservation:
    return JournalObservation(
        kind=ObservationKind.FUNDING_GAP,
        timestamp_ms=gap.as_of_ms,
        market=gap.market,
        feature_snapshot_id=None,
        strategy_decision_id=None,
        risk_decision_id=None,
        plan_id=None,
        attempt_id=None,
        position_action_id=None,
        account_state_id=None,
        reason_codes=(gap.reason,),
        health_refs=(f"funding_boundary:{gap.boundary_ms}",),
        replay_run_id=replay_run_id,
        funding_event_id=gap.gap_id,
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
