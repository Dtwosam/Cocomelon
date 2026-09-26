from decimal import Decimal

from cocomelon.research.profit_lock_counterfactual import (
    ProfitLockRuleSummary,
    ProfitLockStudy,
)
from cocomelon.research.profit_lock_readiness import (
    MIN_ACTIVATED_TRADES_PER_RULE,
    MIN_COMPLETE_PATHS,
    MIN_TRIGGERED_TRADES_PER_RULE,
    ProfitLockReadinessStatus,
    profit_lock_readiness,
)


def _summary(
    rule_id: str,
    *,
    evaluated: int,
    activated: int,
    triggered: int,
) -> ProfitLockRuleSummary:
    return ProfitLockRuleSummary(
        rule_id=rule_id,
        activate_at_r=Decimal("0.5"),
        lock_at_r=Decimal("0"),
        evaluated_trades=evaluated,
        activated_trades=activated,
        triggered_trades=triggered,
        actual_positive_trades=1 if evaluated else 0,
        candidate_positive_trades_estimate=1 if evaluated else 0,
        actual_net_pnl=Decimal("-1"),
        candidate_net_pnl_estimate=Decimal("0"),
        delta_net_pnl_estimate=Decimal("1"),
        actual_mean_net_r=Decimal("-0.1") if evaluated else None,
        candidate_mean_net_r_estimate=Decimal("0") if evaluated else None,
        delta_mean_net_r_estimate=Decimal("0.1") if evaluated else None,
    )


def _study(
    rules: tuple[ProfitLockRuleSummary, ...],
    *,
    complete_paths: int,
    skipped: int = 0,
) -> ProfitLockStudy:
    return ProfitLockStudy(
        path_record_count=complete_paths + skipped,
        evaluated_trade_count=complete_paths,
        skipped_incomplete_paths=skipped,
        rules=rules,
        outcomes=(),
    )


def test_profit_lock_readiness_collects_until_all_count_gates_are_met() -> None:
    study = _study(
        (
            _summary(
                "breakeven_after_0_5r",
                evaluated=MIN_COMPLETE_PATHS - 1,
                activated=MIN_ACTIVATED_TRADES_PER_RULE,
                triggered=MIN_TRIGGERED_TRADES_PER_RULE,
            ),
            _summary(
                "lock_0_5r_after_1r",
                evaluated=MIN_COMPLETE_PATHS,
                activated=MIN_ACTIVATED_TRADES_PER_RULE - 1,
                triggered=MIN_TRIGGERED_TRADES_PER_RULE - 1,
            ),
        ),
        complete_paths=MIN_COMPLETE_PATHS,
    )

    readiness = profit_lock_readiness(study)

    assert readiness.all_rules_ready_for_review is False
    assert readiness.promotion_authority is False
    assert readiness.execution_authority is False
    first, second = readiness.rules
    assert first.status is ProfitLockReadinessStatus.COLLECTING
    assert first.missing_complete_paths == 1
    assert second.status is ProfitLockReadinessStatus.COLLECTING
    assert second.missing_activated_trades == 1
    assert second.missing_triggered_trades == 1


def test_profit_lock_readiness_only_means_ready_for_review() -> None:
    study = _study(
        (
            _summary(
                "breakeven_after_0_5r",
                evaluated=MIN_COMPLETE_PATHS,
                activated=MIN_ACTIVATED_TRADES_PER_RULE,
                triggered=MIN_TRIGGERED_TRADES_PER_RULE,
            ),
            _summary(
                "lock_0_5r_after_1r",
                evaluated=MIN_COMPLETE_PATHS + 5,
                activated=MIN_ACTIVATED_TRADES_PER_RULE + 2,
                triggered=MIN_TRIGGERED_TRADES_PER_RULE + 1,
            ),
        ),
        complete_paths=MIN_COMPLETE_PATHS,
        skipped=2,
    )

    readiness = profit_lock_readiness(study)

    assert readiness.complete_path_count == MIN_COMPLETE_PATHS
    assert readiness.skipped_incomplete_paths == 2
    assert readiness.all_rules_ready_for_review is True
    assert all(
        rule.status is ProfitLockReadinessStatus.READY_FOR_REVIEW
        for rule in readiness.rules
    )
    assert readiness.promotion_authority is False
    assert readiness.execution_authority is False


def test_economic_direction_does_not_change_count_readiness() -> None:
    summary = ProfitLockRuleSummary(
        rule_id="bad-economics",
        activate_at_r=Decimal("0.5"),
        lock_at_r=Decimal("0"),
        evaluated_trades=MIN_COMPLETE_PATHS,
        activated_trades=MIN_ACTIVATED_TRADES_PER_RULE,
        triggered_trades=MIN_TRIGGERED_TRADES_PER_RULE,
        actual_positive_trades=20,
        candidate_positive_trades_estimate=1,
        actual_net_pnl=Decimal("100"),
        candidate_net_pnl_estimate=Decimal("-100"),
        delta_net_pnl_estimate=Decimal("-200"),
        actual_mean_net_r=Decimal("0.5"),
        candidate_mean_net_r_estimate=Decimal("-0.5"),
        delta_mean_net_r_estimate=Decimal("-1"),
    )
    readiness = profit_lock_readiness(
        _study((summary,), complete_paths=MIN_COMPLETE_PATHS)
    )

    assert readiness.rules[0].status is ProfitLockReadinessStatus.READY_FOR_REVIEW
    assert readiness.promotion_authority is False
    assert readiness.execution_authority is False
