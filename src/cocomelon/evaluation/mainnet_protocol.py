from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from cocomelon.domain.evaluation import (
    EvaluationDatasetManifest,
    EvaluationPolicy,
    FrozenSplitManifest,
    SplitName,
    TimePartition,
    TradeEvaluationSample,
)
from cocomelon.evaluation.splits import split_samples
from cocomelon.evaluation.walkforward import WalkForwardPlan, generate_walkforward_windows

DAY_MS = 86_400_000
V2_TRAIN_DAYS = 1
V2_VALIDATION_DAYS = 1
V2_TEST_DAYS = 45
V2_WALKFORWARD_EVALUATION_DAYS = 7
V2_WALKFORWARD_STEP_DAYS = 7


@dataclass(frozen=True, slots=True)
class MainnetPhase9Protocol:
    split: FrozenSplitManifest
    walkforward: WalkForwardPlan


@dataclass(frozen=True, slots=True)
class MainnetPhase9Readiness:
    dataset_manifest_id: str
    test_window_complete: bool
    test_trade_count: int
    test_covered_days: int
    eligible_walkforward_windows: int
    minimum_oos_trades: int
    minimum_oos_days: int
    minimum_walkforward_windows: int
    minimum_trades_per_walkforward_window: int
    ready: bool
    reason_codes: tuple[str, ...]


def build_v2_protocol(
    dataset: EvaluationDatasetManifest,
    *,
    policy: EvaluationPolicy | None = None,
) -> MainnetPhase9Protocol:
    rules = EvaluationPolicy() if policy is None else policy
    start = dataset.start_ms
    train_end = start + V2_TRAIN_DAYS * DAY_MS
    validation_end = train_end + V2_VALIDATION_DAYS * DAY_MS
    test_end = validation_end + V2_TEST_DAYS * DAY_MS

    split = FrozenSplitManifest(
        dataset_manifest_id=dataset.manifest_id,
        train=TimePartition(SplitName.TRAIN, start, train_end),
        validation=TimePartition(SplitName.VALIDATION, train_end, validation_end),
        test=TimePartition(SplitName.TEST, validation_end, test_end),
        embargo_ms=rules.split_embargo_ms,
        policy_id=rules.policy_id,
    )
    walkforward = WalkForwardPlan(
        dataset_manifest_id=dataset.manifest_id,
        first_window_start_ms=start,
        development_duration_ms=V2_TRAIN_DAYS * DAY_MS,
        validation_duration_ms=V2_VALIDATION_DAYS * DAY_MS,
        evaluation_duration_ms=V2_WALKFORWARD_EVALUATION_DAYS * DAY_MS,
        step_ms=V2_WALKFORWARD_STEP_DAYS * DAY_MS,
        embargo_ms=rules.split_embargo_ms,
        expanding=True,
        policy_id=rules.policy_id,
    )
    return MainnetPhase9Protocol(split=split, walkforward=walkforward)


def evaluate_v2_readiness(
    dataset: EvaluationDatasetManifest,
    samples: Sequence[TradeEvaluationSample],
    *,
    policy: EvaluationPolicy | None = None,
) -> MainnetPhase9Readiness:
    rules = EvaluationPolicy() if policy is None else policy
    protocol = build_v2_protocol(dataset, policy=rules)
    test_samples = split_samples(samples, protocol.split)[SplitName.TEST]
    test_trade_count = len(test_samples)
    test_covered_days = len({item.closed_at_ms // DAY_MS for item in test_samples})
    test_window_complete = dataset.end_ms >= protocol.split.test.end_ms

    window_end = min(dataset.end_ms, protocol.split.test.end_ms)
    windows = generate_walkforward_windows(
        protocol.walkforward,
        dataset_end_ms=window_end,
    )
    eligible_walkforward_windows = sum(
        1
        for window in windows
        if len(split_samples(samples, window)[SplitName.TEST])
        >= rules.min_trades_per_walkforward_window
    )

    reasons: list[str] = []
    if not test_window_complete:
        reasons.append("TEST_WINDOW_INCOMPLETE")
    if test_trade_count < rules.min_oos_trades:
        reasons.append("OOS_TRADES_SHORTFALL")
    if test_covered_days < rules.min_oos_days:
        reasons.append("OOS_DAYS_SHORTFALL")
    if eligible_walkforward_windows < rules.min_walkforward_windows:
        reasons.append("WALKFORWARD_WINDOWS_SHORTFALL")

    return MainnetPhase9Readiness(
        dataset_manifest_id=dataset.manifest_id,
        test_window_complete=test_window_complete,
        test_trade_count=test_trade_count,
        test_covered_days=test_covered_days,
        eligible_walkforward_windows=eligible_walkforward_windows,
        minimum_oos_trades=rules.min_oos_trades,
        minimum_oos_days=rules.min_oos_days,
        minimum_walkforward_windows=rules.min_walkforward_windows,
        minimum_trades_per_walkforward_window=(
            rules.min_trades_per_walkforward_window
        ),
        ready=not reasons,
        reason_codes=tuple(reasons),
    )
