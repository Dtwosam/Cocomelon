from __future__ import annotations

from decimal import Decimal
from importlib import import_module

from cocomelon.research.contracts import ResearchCandidateState, ResearchCheckpointState

sequential = import_module("cocomelon.research.sequential")


def test_operational_failure_bypasses_economic_posterior(monkeypatch: object) -> None:
    def forbidden_posterior(*args: object, **kwargs: object) -> Decimal:
        raise AssertionError("operational rejection must not compute economic posterior")

    monkeypatch.setattr(sequential, "posterior_probability_positive", forbidden_posterior)

    checkpoint = sequential.evaluate_checkpoint(
        net_r_values=tuple(Decimal("1") for _ in range(40)),
        closed_trade_days=7,
        operational_failure=True,
    )

    assert checkpoint.checkpoint_state is ResearchCheckpointState.REJECT_OPERATIONAL
    assert checkpoint.candidate_state is ResearchCandidateState.REJECTED_OPERATIONAL
    assert checkpoint.posterior_probability_positive is None
    assert checkpoint.reason_codes == ("operational_failure",)


def test_hard_risk_failure_bypasses_economic_posterior(monkeypatch: object) -> None:
    def forbidden_posterior(*args: object, **kwargs: object) -> Decimal:
        raise AssertionError("hard-risk rejection must not compute economic posterior")

    monkeypatch.setattr(sequential, "posterior_probability_positive", forbidden_posterior)

    checkpoint = sequential.evaluate_checkpoint(
        net_r_values=tuple(Decimal("1") for _ in range(40)),
        closed_trade_days=7,
        hard_risk_failure=True,
    )

    assert checkpoint.checkpoint_state is ResearchCheckpointState.REJECT_OPERATIONAL
    assert checkpoint.candidate_state is ResearchCandidateState.REJECTED_OPERATIONAL
    assert checkpoint.posterior_probability_positive is None
    assert checkpoint.reason_codes == ("hard_risk_failure",)
