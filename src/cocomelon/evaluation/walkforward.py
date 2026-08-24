from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from cocomelon.domain.evaluation import (
    EvaluationPolicy,
    FrozenSplitManifest,
    SplitName,
    TimePartition,
    TradeEvaluationSample,
    WalkForwardWindowResult,
)
from cocomelon.evaluation.metrics import compute_performance_metrics
from cocomelon.evaluation.splits import split_samples


@dataclass(frozen=True, slots=True)
class WalkForwardPlan:
    dataset_manifest_id: str
    first_window_start_ms: int
    development_duration_ms: int
    validation_duration_ms: int
    evaluation_duration_ms: int
    step_ms: int
    embargo_ms: int
    expanding: bool
    policy_id: str

    def __post_init__(self) -> None:
        if not self.dataset_manifest_id.strip():
            raise ValueError("dataset_manifest_id must not be empty")
        if not self.policy_id.strip():
            raise ValueError("policy_id must not be empty")
        if self.first_window_start_ms < 0:
            raise ValueError("first_window_start_ms must be non-negative")
        for field in (
            "development_duration_ms",
            "validation_duration_ms",
            "evaluation_duration_ms",
            "step_ms",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.embargo_ms < 0:
            raise ValueError("embargo_ms must be non-negative")


def generate_walkforward_windows(
    plan: WalkForwardPlan,
    *,
    dataset_end_ms: int,
) -> tuple[FrozenSplitManifest, ...]:
    if dataset_end_ms <= plan.first_window_start_ms:
        return ()

    windows: list[FrozenSplitManifest] = []
    ordinal = 0
    while True:
        shift = ordinal * plan.step_ms
        train_start = plan.first_window_start_ms if plan.expanding else plan.first_window_start_ms + shift
        train_end = plan.first_window_start_ms + plan.development_duration_ms + shift
        validation_start = train_end
        validation_end = validation_start + plan.validation_duration_ms
        evaluation_start = validation_end
        evaluation_end = evaluation_start + plan.evaluation_duration_ms
        if evaluation_end > dataset_end_ms:
            break

        windows.append(
            FrozenSplitManifest(
                dataset_manifest_id=plan.dataset_manifest_id,
                train=TimePartition(SplitName.TRAIN, train_start, train_end),
                validation=TimePartition(
                    SplitName.VALIDATION,
                    validation_start,
                    validation_end,
                ),
                test=TimePartition(
                    SplitName.TEST,
                    evaluation_start,
                    evaluation_end,
                ),
                embargo_ms=plan.embargo_ms,
                policy_id=plan.policy_id,
            )
        )
        ordinal += 1
    return tuple(windows)


def _overlaps_evaluation(
    sample: TradeEvaluationSample,
    window: FrozenSplitManifest,
) -> bool:
    return sample.closed_at_ms >= window.test.start_ms and sample.opened_at_ms < window.test.end_ms


def evaluate_walkforward(
    samples: Sequence[TradeEvaluationSample],
    windows: Sequence[FrozenSplitManifest],
    *,
    policy: EvaluationPolicy,
) -> tuple[WalkForwardWindowResult, ...]:
    results: list[WalkForwardWindowResult] = []
    for window in windows:
        if window.policy_id != policy.policy_id:
            raise ValueError("walk-forward window policy does not match evaluation policy")
        if window.embargo_ms != policy.split_embargo_ms:
            raise ValueError("walk-forward window embargo does not match evaluation policy")

        partitions = split_samples(samples, window)
        included = partitions[SplitName.TEST]
        included_ids = {item.trade_id for item in included}
        excluded = tuple(
            sorted(
                item.trade_id
                for item in samples
                if _overlaps_evaluation(item, window) and item.trade_id not in included_ids
            )
        )
        metrics = compute_performance_metrics(included)
        eligible = metrics.trade_count >= policy.min_trades_per_walkforward_window
        reason_codes = () if eligible else ("INSUFFICIENT_WALKFORWARD_TRADES",)
        results.append(
            WalkForwardWindowResult(
                split_manifest_id=window.split_manifest_id,
                evaluation_start_ms=window.test.start_ms,
                evaluation_end_ms=window.test.end_ms,
                included_trade_ids=tuple(item.trade_id for item in included),
                excluded_trade_ids=excluded,
                metrics=metrics,
                eligible=eligible,
                reason_codes=reason_codes,
            )
        )
    return tuple(results)
