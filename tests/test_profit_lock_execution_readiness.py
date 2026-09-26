from __future__ import annotations

import pytest

from cocomelon.research.profit_lock_execution_readiness import (
    MIN_ACTIVATED_TRADES_PER_RULE,
    MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE,
    MIN_SIMULATED_FULL_CLOSES_PER_RULE,
    MIN_TRIGGERED_TRADES_PER_RULE,
    ProfitLockExecutionReadinessError,
    ProfitLockExecutionReadinessStatus,
    profit_lock_execution_readiness,
)


def _summary(
    *,
    evaluated: int,
    activated: int,
    triggered: int,
    full: int,
    incomplete: int = 0,
) -> dict[str, object]:
    return {
        "research_only": True,
        "execution_authority": False,
        "rules": [
            {
                "rule_id": "breakeven_after_0_5r",
                "economically_evaluated_trades": evaluated,
                "activated_trades": activated,
                "triggered_trades": triggered,
                "simulated_full_closes": full,
                "triggered_incomplete": incomplete,
            }
        ],
    }


def test_execution_readiness_collects_until_every_volume_gate_is_met() -> None:
    readiness = profit_lock_execution_readiness(
        _summary(
            evaluated=29,
            activated=14,
            triggered=9,
            full=9,
        )
    )

    rule = readiness.rules[0]
    assert rule.status is ProfitLockExecutionReadinessStatus.COLLECTING
    assert rule.missing_evaluated_trades == 1
    assert rule.missing_activated_trades == 1
    assert rule.missing_triggered_trades == 1
    assert rule.missing_simulated_full_closes == 1
    assert readiness.all_rules_ready_for_review is False
    assert readiness.promotion_authority is False
    assert readiness.execution_authority is False


def test_execution_readiness_only_grants_review_not_authority() -> None:
    readiness = profit_lock_execution_readiness(
        _summary(
            evaluated=MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE,
            activated=MIN_ACTIVATED_TRADES_PER_RULE,
            triggered=MIN_TRIGGERED_TRADES_PER_RULE,
            full=MIN_SIMULATED_FULL_CLOSES_PER_RULE,
        )
    )

    rule = readiness.rules[0]
    assert (
        rule.status
        is ProfitLockExecutionReadinessStatus.READY_FOR_REVIEW
    )
    assert rule.missing_evaluated_trades == 0
    assert rule.missing_activated_trades == 0
    assert rule.missing_triggered_trades == 0
    assert rule.missing_simulated_full_closes == 0
    assert readiness.all_rules_ready_for_review is True
    assert readiness.promotion_authority is False
    assert readiness.execution_authority is False


def test_execution_readiness_accepts_incomplete_triggered_evidence_without_counting_it_as_economic(
) -> None:
    readiness = profit_lock_execution_readiness(
        _summary(
            evaluated=20,
            activated=21,
            triggered=11,
            full=10,
            incomplete=1,
        )
    )

    rule = readiness.rules[0]
    assert rule.triggered_incomplete == 1
    assert rule.missing_evaluated_trades == 10
    assert rule.missing_triggered_trades == 0
    assert rule.missing_simulated_full_closes == 0
    assert rule.status is ProfitLockExecutionReadinessStatus.COLLECTING


def test_execution_readiness_rejects_authoritative_or_inconsistent_input() -> None:
    authoritative = _summary(
        evaluated=30,
        activated=15,
        triggered=10,
        full=10,
    )
    authoritative["execution_authority"] = True
    with pytest.raises(
        ProfitLockExecutionReadinessError,
        match="must not have execution authority",
    ):
        profit_lock_execution_readiness(authoritative)

    inconsistent = _summary(
        evaluated=30,
        activated=15,
        triggered=10,
        full=9,
        incomplete=2,
    )
    with pytest.raises(
        ProfitLockExecutionReadinessError,
        match="completion counts",
    ):
        profit_lock_execution_readiness(inconsistent)
