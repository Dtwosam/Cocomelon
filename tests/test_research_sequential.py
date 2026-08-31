from __future__ import annotations

from decimal import Decimal
from importlib import import_module

from cocomelon.research.contracts import (
    ResearchCandidateState,
    ResearchCheckpointState,
)

sequential = import_module("cocomelon.research.sequential")


def _values(value: str, count: int) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for _ in range(count))


def test_futility_cannot_fire_before_twenty_closed_trades() -> None:
    checkpoint = sequential.evaluate_checkpoint(
        net_r_values=_values("-1.0", 19),
        closed_trade_days=5,
    )

    assert checkpoint.checkpoint_state is ResearchCheckpointState.INSUFFICIENT_TRADES
    assert checkpoint.candidate_state is ResearchCandidateState.RESEARCHING
    assert checkpoint.posterior_probability_positive is None


def test_strongly_negative_candidate_rejects_at_futility_boundary() -> None:
    checkpoint = sequential.evaluate_checkpoint(
        net_r_values=_values("-1.0", 20),
        closed_trade_days=7,
    )

    assert checkpoint.posterior_probability_positive is not None
    assert checkpoint.posterior_probability_positive < Decimal("0.05")
    assert checkpoint.checkpoint_state is ResearchCheckpointState.REJECT_FUTILITY
    assert checkpoint.candidate_state is ResearchCandidateState.REJECTED_FUTILITY


def test_positive_candidate_cannot_be_promising_before_forty_trades() -> None:
    checkpoint = sequential.evaluate_checkpoint(
        net_r_values=_values("1.0", 39),
        closed_trade_days=7,
    )

    assert checkpoint.posterior_probability_positive is not None
    assert checkpoint.posterior_probability_positive >= Decimal("0.80")
    assert checkpoint.checkpoint_state is ResearchCheckpointState.CONTINUE
    assert checkpoint.candidate_state is ResearchCandidateState.RESEARCHING


def test_positive_candidate_cannot_be_promising_before_seven_days() -> None:
    checkpoint = sequential.evaluate_checkpoint(
        net_r_values=_values("1.0", 40),
        closed_trade_days=6,
    )

    assert checkpoint.posterior_probability_positive is not None
    assert checkpoint.posterior_probability_positive >= Decimal("0.80")
    assert checkpoint.checkpoint_state is ResearchCheckpointState.CONTINUE
    assert checkpoint.candidate_state is ResearchCandidateState.RESEARCHING


def test_sufficiently_positive_candidate_can_become_research_promising() -> None:
    checkpoint = sequential.evaluate_checkpoint(
        net_r_values=_values("1.0", 40),
        closed_trade_days=7,
    )

    assert checkpoint.posterior_probability_positive is not None
    assert checkpoint.posterior_probability_positive >= Decimal("0.80")
    assert checkpoint.checkpoint_state is ResearchCheckpointState.RESEARCH_PROMISING
    assert checkpoint.candidate_state is ResearchCandidateState.RESEARCH_PROMISING


def test_posterior_is_deterministic_for_identical_ordered_observations() -> None:
    observations = tuple(Decimal(value) for value in ("0.4", "-0.2", "0.7", "0.1")) * 5

    first = sequential.posterior_probability_positive(observations)
    second = sequential.posterior_probability_positive(observations)

    assert first == second
    assert first.as_tuple() == second.as_tuple()


def test_operational_or_hard_risk_failure_overrides_economic_state() -> None:
    operational = sequential.evaluate_checkpoint(
        net_r_values=_values("1.0", 40),
        closed_trade_days=7,
        operational_failure=True,
    )
    hard_risk = sequential.evaluate_checkpoint(
        net_r_values=_values("1.0", 40),
        closed_trade_days=7,
        hard_risk_failure=True,
    )

    assert operational.candidate_state is ResearchCandidateState.REJECTED_OPERATIONAL
    assert hard_risk.candidate_state is ResearchCandidateState.REJECTED_OPERATIONAL
    assert "operational_failure" in operational.reason_codes
    assert "hard_risk_failure" in hard_risk.reason_codes
