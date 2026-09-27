from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE = 30
MIN_ACTIVATED_TRADES_PER_RULE = 15
MIN_TRIGGERED_TRADES_PER_RULE = 10
MIN_SIMULATED_FULL_CLOSES_PER_RULE = 10


class ProfitLockExecutionReadinessError(RuntimeError):
    pass


class ProfitLockExecutionReadinessStatus(StrEnum):
    COLLECTING = "collecting"
    READY_FOR_REVIEW = "ready_for_review"


@dataclass(frozen=True, slots=True)
class ProfitLockExecutionRuleReadiness:
    rule_id: str
    economically_evaluated_trades: int
    activated_trades: int
    triggered_trades: int
    simulated_full_closes: int
    triggered_incomplete: int
    missing_evaluated_trades: int
    missing_activated_trades: int
    missing_triggered_trades: int
    missing_simulated_full_closes: int
    status: ProfitLockExecutionReadinessStatus

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        for field in (
            "economically_evaluated_trades",
            "activated_trades",
            "triggered_trades",
            "simulated_full_closes",
            "triggered_incomplete",
            "missing_evaluated_trades",
            "missing_activated_trades",
            "missing_triggered_trades",
            "missing_simulated_full_closes",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.simulated_full_closes > self.triggered_trades:
            raise ValueError(
                "simulated_full_closes cannot exceed triggered_trades"
            )
        if (
            self.simulated_full_closes + self.triggered_incomplete
            > self.triggered_trades
        ):
            raise ValueError(
                "full and incomplete triggered counts cannot exceed triggers"
            )


@dataclass(frozen=True, slots=True)
class ProfitLockExecutionReadiness:
    rules: tuple[ProfitLockExecutionRuleReadiness, ...]
    lineage_mismatch_closed_trades: int
    orphaned_restored_positions: int
    all_rules_ready_for_review: bool
    promotion_authority: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if (
            self.lineage_mismatch_closed_trades < 0
            or self.orphaned_restored_positions < 0
        ):
            raise ValueError(
                "research integrity counters must be non-negative"
            )
        expected = (
            bool(self.rules)
            and self.lineage_mismatch_closed_trades == 0
            and self.orphaned_restored_positions == 0
            and all(
                rule.status
                is ProfitLockExecutionReadinessStatus.READY_FOR_REVIEW
                for rule in self.rules
            )
        )
        if self.all_rules_ready_for_review != expected:
            raise ValueError(
                "all_rules_ready_for_review must reconcile"
            )
        if self.promotion_authority or self.execution_authority:
            raise ValueError(
                "execution-shadow readiness cannot grant authority"
            )


def _nonnegative_int(
    raw: Mapping[str, object],
    key: str,
) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfitLockExecutionReadinessError(
            f"{key} must be an integer"
        )
    if value < 0:
        raise ProfitLockExecutionReadinessError(
            f"{key} must be non-negative"
        )
    return value


def _rule_readiness(
    raw: Mapping[str, object],
) -> ProfitLockExecutionRuleReadiness:
    rule_id = raw.get("rule_id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ProfitLockExecutionReadinessError(
            "rule_id must be a non-empty string"
        )
    evaluated = _nonnegative_int(
        raw,
        "economically_evaluated_trades",
    )
    activated = _nonnegative_int(raw, "activated_trades")
    triggered = _nonnegative_int(raw, "triggered_trades")
    full = _nonnegative_int(raw, "simulated_full_closes")
    incomplete = _nonnegative_int(raw, "triggered_incomplete")
    if activated > evaluated + incomplete:
        # Activated trades may include triggered-incomplete outcomes that are
        # deliberately excluded from economic aggregation.
        raise ProfitLockExecutionReadinessError(
            "activated count does not reconcile with evaluated evidence"
        )
    if triggered > activated:
        raise ProfitLockExecutionReadinessError(
            "triggered_trades cannot exceed activated_trades"
        )
    if full > triggered or full + incomplete > triggered:
        raise ProfitLockExecutionReadinessError(
            "trigger completion counts do not reconcile"
        )

    missing_evaluated = max(
        0,
        MIN_ECONOMICALLY_EVALUATED_TRADES_PER_RULE - evaluated,
    )
    missing_activated = max(
        0,
        MIN_ACTIVATED_TRADES_PER_RULE - activated,
    )
    missing_triggered = max(
        0,
        MIN_TRIGGERED_TRADES_PER_RULE - triggered,
    )
    missing_full = max(
        0,
        MIN_SIMULATED_FULL_CLOSES_PER_RULE - full,
    )
    status = (
        ProfitLockExecutionReadinessStatus.READY_FOR_REVIEW
        if (
            missing_evaluated == 0
            and missing_activated == 0
            and missing_triggered == 0
            and missing_full == 0
        )
        else ProfitLockExecutionReadinessStatus.COLLECTING
    )
    return ProfitLockExecutionRuleReadiness(
        rule_id=rule_id,
        economically_evaluated_trades=evaluated,
        activated_trades=activated,
        triggered_trades=triggered,
        simulated_full_closes=full,
        triggered_incomplete=incomplete,
        missing_evaluated_trades=missing_evaluated,
        missing_activated_trades=missing_activated,
        missing_triggered_trades=missing_triggered,
        missing_simulated_full_closes=missing_full,
        status=status,
    )


def profit_lock_execution_readiness(
    shadow_summary: Mapping[str, object],
) -> ProfitLockExecutionReadiness:
    if shadow_summary.get("execution_authority") is not False:
        raise ProfitLockExecutionReadinessError(
            "execution shadow must not have execution authority"
        )
    rules_raw = shadow_summary.get("rules")
    if not isinstance(rules_raw, Sequence) or isinstance(
        rules_raw,
        (str, bytes),
    ):
        raise ProfitLockExecutionReadinessError(
            "execution shadow rules must be an array"
        )

    rules: list[ProfitLockExecutionRuleReadiness] = []
    for item in rules_raw:
        if not isinstance(item, Mapping):
            raise ProfitLockExecutionReadinessError(
                "execution shadow rule must be an object"
            )
        rules.append(_rule_readiness(item))
    resolved = tuple(rules)
    if len({rule.rule_id for rule in resolved}) != len(resolved):
        raise ProfitLockExecutionReadinessError(
            "execution shadow rule ids must be unique"
        )
    lineage_mismatch = shadow_summary.get(
        "lineage_mismatch_closed_trades",
        0,
    )
    orphaned_restored = shadow_summary.get(
        "orphaned_restored_positions",
        0,
    )
    if (
        isinstance(lineage_mismatch, bool)
        or not isinstance(lineage_mismatch, int)
        or lineage_mismatch < 0
    ):
        raise ProfitLockExecutionReadinessError(
            "lineage_mismatch_closed_trades must be non-negative integer"
        )
    if (
        isinstance(orphaned_restored, bool)
        or not isinstance(orphaned_restored, int)
        or orphaned_restored < 0
    ):
        raise ProfitLockExecutionReadinessError(
            "orphaned_restored_positions must be non-negative integer"
        )
    return ProfitLockExecutionReadiness(
        rules=resolved,
        lineage_mismatch_closed_trades=lineage_mismatch,
        orphaned_restored_positions=orphaned_restored,
        all_rules_ready_for_review=(
            bool(resolved)
            and lineage_mismatch == 0
            and orphaned_restored == 0
            and all(
                rule.status
                is ProfitLockExecutionReadinessStatus.READY_FOR_REVIEW
                for rule in resolved
            )
        ),
    )
