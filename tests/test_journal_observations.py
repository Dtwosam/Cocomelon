from decimal import Decimal

import pytest

from cocomelon.domain.execution import ExecutionAttempt, ExecutionResult
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskDecision
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.journal.observations import (
    observation_from_execution,
    observation_from_risk,
    observation_from_strategy,
    should_sample_no_trade,
)

MARKET = MarketId("", "SOL")


def strategy(direction: Direction = Direction.NO_TRADE) -> StrategyDecision:
    return StrategyDecision(
        market=MARKET,
        direction=direction,
        score=Decimal("61"),
        timestamp_ms=1_000,
        feature_snapshot_id="feature-1",
        lead_strategy=None if direction is Direction.NO_TRADE else "trend",
        invalidation_price=None if direction is Direction.NO_TRADE else Decimal("95"),
        signal_ids=("signal-1",),
        reason_codes=("NO_EDGE",) if direction is Direction.NO_TRADE else ("TREND_CONFIRMED",),
    )


def risk(*, approved: bool) -> RiskDecision:
    decision = strategy(Direction.LONG)
    return RiskDecision(
        strategy_decision_id=decision.decision_id,
        market=MARKET,
        direction=Direction.LONG,
        approved=approved,
        reason_codes=("APPROVED",) if approved else ("DAILY_LOCKOUT",),
        target_risk_amount=Decimal("25"),
        approved_risk_amount=Decimal("25") if approved else Decimal("0"),
        approved_notional=Decimal("500") if approved else Decimal("0"),
        entry_reference_price=Decimal("100"),
        stop_price=Decimal("95") if approved else None,
        stop_distance_fraction=Decimal("0.05") if approved else None,
        effective_loss_fraction=Decimal("0.0525") if approved else None,
        correlation_bucket="majors",
        binding_caps=("RISK_PER_TRADE",) if approved else (),
        timestamp_ms=1_010,
    )


def attempt(result: ExecutionResult, *, filled: str, reason_codes: tuple[str, ...]) -> ExecutionAttempt:
    filled_quantity = Decimal(filled)
    requested = Decimal("5")
    return ExecutionAttempt(
        plan_id="plan-1",
        source_event_key="l2:SOL:1",
        requested_quantity=requested,
        filled_quantity=filled_quantity,
        average_fill_price=Decimal("100") if filled_quantity > 0 else None,
        gross_fill_notional=filled_quantity * Decimal("100"),
        fee=filled_quantity * Decimal("0.045"),
        unfilled_quantity=requested - filled_quantity,
        result=result,
        reason_codes=reason_codes,
        snapshot_exchange_ms=1_015,
        snapshot_received_ms=1_020,
        attempt_timestamp_ms=1_025,
    )


def test_strategy_observation_preserves_no_trade_reason_and_source_ids() -> None:
    decision = strategy()
    observation = observation_from_strategy(decision, replay_run_id="replay-1")

    assert observation.kind.value == "strategy_decision"
    assert observation.market == MARKET
    assert observation.timestamp_ms == decision.timestamp_ms
    assert observation.feature_snapshot_id == decision.feature_snapshot_id
    assert observation.strategy_decision_id == decision.decision_id
    assert observation.reason_codes == ("NO_EDGE",)
    assert observation.replay_run_id == "replay-1"


def test_risk_observations_preserve_approval_and_rejection_identity() -> None:
    approved = risk(approved=True)
    rejected = risk(approved=False)

    approved_observation = observation_from_risk(approved, replay_run_id=None)
    rejected_observation = observation_from_risk(rejected, replay_run_id="replay-2")

    assert approved_observation.risk_decision_id == approved.risk_decision_id
    assert approved_observation.reason_codes == ("APPROVED",)
    assert rejected_observation.risk_decision_id == rejected.risk_decision_id
    assert rejected_observation.reason_codes == ("DAILY_LOCKOUT",)
    assert rejected_observation.strategy_decision_id == rejected.strategy_decision_id


def test_execution_observations_cover_full_partial_and_zero_fill() -> None:
    full = attempt(ExecutionResult.FULL, filled="5", reason_codes=("FILLED",))
    partial = attempt(ExecutionResult.PARTIAL, filled="2", reason_codes=("IOC_PARTIAL",))
    zero = attempt(ExecutionResult.NO_FILL, filled="0", reason_codes=("NO_VISIBLE_DEPTH",))

    observations = tuple(
        observation_from_execution(item, replay_run_id="replay-3")
        for item in (full, partial, zero)
    )

    assert tuple(item.attempt_id for item in observations) == (
        full.attempt_id,
        partial.attempt_id,
        zero.attempt_id,
    )
    assert tuple(item.plan_id for item in observations) == ("plan-1", "plan-1", "plan-1")
    assert tuple(item.reason_codes for item in observations) == (
        ("FILLED",),
        ("IOC_PARTIAL",),
        ("NO_VISIBLE_DEPTH",),
    )


def test_no_trade_sampling_is_hash_deterministic_and_has_exact_edges() -> None:
    ids = tuple(f"decision-{index}" for index in range(100))
    first = tuple(should_sample_no_trade(item, numerator=1, denominator=10) for item in ids)
    second = tuple(should_sample_no_trade(item, numerator=1, denominator=10) for item in ids)

    assert first == second
    assert any(first)
    assert not all(first)
    assert not should_sample_no_trade("decision-1", numerator=0, denominator=10)
    assert should_sample_no_trade("decision-1", numerator=10, denominator=10)


@pytest.mark.parametrize(
    ("numerator", "denominator"),
    ((-1, 10), (1, 0), (11, 10)),
)
def test_no_trade_sampling_rejects_invalid_fraction(numerator: int, denominator: int) -> None:
    with pytest.raises(ValueError):
        should_sample_no_trade("decision-1", numerator=numerator, denominator=denominator)
