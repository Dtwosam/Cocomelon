from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cocomelon.research.profit_lock_counterfactual import ProfitLockStudy

MIN_COMPLETE_PATHS = 30
MIN_ACTIVATED_TRADES_PER_RULE = 15
MIN_TRIGGERED_TRADES_PER_RULE = 10


class ProfitLockReadinessStatus(StrEnum):
    COLLECTING = "collecting"
    READY_FOR_REVIEW = "ready_for_review"


@dataclass(frozen=True, slots=True)
class ProfitLockRuleReadiness:
    rule_id: str
    evaluated_trades: int
    activated_trades: int
    triggered_trades: int
    missing_complete_paths: int
    missing_activated_trades: int
    missing_triggered_trades: int
    status: ProfitLockReadinessStatus

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        for field in (
            "evaluated_trades",
            "activated_trades",
            "triggered_trades",
            "missing_complete_paths",
            "missing_activated_trades",
            "missing_triggered_trades",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")


@dataclass(frozen=True, slots=True)
class ProfitLockReadiness:
    complete_path_count: int
    skipped_incomplete_paths: int
    rules: tuple[ProfitLockRuleReadiness, ...]
    all_rules_ready_for_review: bool
    promotion_authority: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if self.complete_path_count < 0 or self.skipped_incomplete_paths < 0:
            raise ValueError("path counts must be non-negative")
        expected = bool(self.rules) and all(
            rule.status is ProfitLockReadinessStatus.READY_FOR_REVIEW
            for rule in self.rules
        )
        if self.all_rules_ready_for_review != expected:
            raise ValueError("all_rules_ready_for_review must reconcile")
        if self.promotion_authority or self.execution_authority:
            raise ValueError("readiness cannot grant promotion or execution authority")


def profit_lock_readiness(study: ProfitLockStudy) -> ProfitLockReadiness:
    rules: list[ProfitLockRuleReadiness] = []
    for rule in study.rules:
        missing_paths = max(0, MIN_COMPLETE_PATHS - rule.evaluated_trades)
        missing_activated = max(
            0,
            MIN_ACTIVATED_TRADES_PER_RULE - rule.activated_trades,
        )
        missing_triggered = max(
            0,
            MIN_TRIGGERED_TRADES_PER_RULE - rule.triggered_trades,
        )
        status = (
            ProfitLockReadinessStatus.READY_FOR_REVIEW
            if missing_paths == 0
            and missing_activated == 0
            and missing_triggered == 0
            else ProfitLockReadinessStatus.COLLECTING
        )
        rules.append(
            ProfitLockRuleReadiness(
                rule_id=rule.rule_id,
                evaluated_trades=rule.evaluated_trades,
                activated_trades=rule.activated_trades,
                triggered_trades=rule.triggered_trades,
                missing_complete_paths=missing_paths,
                missing_activated_trades=missing_activated,
                missing_triggered_trades=missing_triggered,
                status=status,
            )
        )

    resolved = tuple(rules)
    return ProfitLockReadiness(
        complete_path_count=study.evaluated_trade_count,
        skipped_incomplete_paths=study.skipped_incomplete_paths,
        rules=resolved,
        all_rules_ready_for_review=bool(resolved)
        and all(
            rule.status is ProfitLockReadinessStatus.READY_FOR_REVIEW
            for rule in resolved
        ),
    )
