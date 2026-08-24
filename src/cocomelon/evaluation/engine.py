from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.evaluation import (
    ConfidenceInterval,
    EdgeEvidenceStatus,
    EvaluationDatasetManifest,
    EvaluationPolicy,
    EvaluationResult,
    FrozenCandidateSet,
    FrozenSplitManifest,
    OOSStatus,
    PerformanceMetrics,
    PromotionGatePreview,
    SplitName,
    TradeEvaluationSample,
    WalkForwardWindowResult,
)
from cocomelon.evaluation.dataset import EvaluationDatasetError, build_evaluation_dataset
from cocomelon.evaluation.metrics import compute_performance_metrics
from cocomelon.evaluation.sensitivity import (
    CostStressProfile,
    apply_cost_stress,
    predeclared_cost_stress_profiles,
)
from cocomelon.evaluation.slices import evaluate_slices
from cocomelon.evaluation.splits import consume_untouched_test, split_samples
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evaluation.uncertainty import mean_net_r_confidence_interval
from cocomelon.evaluation.walkforward import (
    WalkForwardPlan,
    evaluate_walkforward,
    generate_walkforward_windows,
)
from cocomelon.journal.store import JournalStore

ZERO = Decimal("0")
MARKET_CONCENTRATION_LIMIT = Decimal("0.35")
SEVEN_DAY_CONCENTRATION_LIMIT = Decimal("0.50")
LIVE_PROFIT_FACTOR_LIMIT = Decimal("1.20")
LIVE_DRAWDOWN_LIMIT = Decimal("0.08")
LIVE_TRADE_COUNT = 500
LIVE_COVERED_DAYS = 45
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    dataset: EvaluationDatasetManifest
    split: FrozenSplitManifest
    candidates: FrozenCandidateSet
    policy: EvaluationPolicy
    walkforward_plan: WalkForwardPlan
    sensitivity_profiles: tuple[CostStressProfile, ...]

    def __post_init__(self) -> None:
        if not self.sensitivity_profiles:
            raise ValueError("sensitivity_profiles must not be empty")
        profile_ids = tuple(sorted(item.profile_id for item in self.sensitivity_profiles))
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("sensitivity_profiles must be unique")


def _eligible_walkforward(
    results: Sequence[WalkForwardWindowResult],
) -> tuple[WalkForwardWindowResult, ...]:
    return tuple(item for item in results if item.eligible)


def derive_edge_status(
    *,
    evidence_valid: bool,
    oos_status: OOSStatus,
    test_metrics: PerformanceMetrics,
    confidence_interval: ConfidenceInterval | None,
    walkforward_results: Sequence[WalkForwardWindowResult],
    policy: EvaluationPolicy,
) -> EdgeEvidenceStatus:
    if not evidence_valid:
        return EdgeEvidenceStatus.INVALID_EVIDENCE
    if oos_status is OOSStatus.CONTAMINATED:
        return EdgeEvidenceStatus.OOS_CONTAMINATED

    eligible = _eligible_walkforward(walkforward_results)
    if (
        test_metrics.trade_count < policy.min_oos_trades
        or test_metrics.covered_days < policy.min_oos_days
        or confidence_interval is None
        or len(eligible) < policy.min_walkforward_windows
    ):
        return EdgeEvidenceStatus.INSUFFICIENT_EVIDENCE

    with localcontext(AUTHORITATIVE_CONTEXT):
        aggregate_trade_count = sum(item.metrics.trade_count for item in eligible)
        aggregate_net_r = sum((item.metrics.total_net_r for item in eligible), ZERO)
        aggregate_mean_net_r = (
            ZERO
            if aggregate_trade_count == 0
            else aggregate_net_r / Decimal(aggregate_trade_count)
        )
        positive_fraction = Decimal(
            sum(item.metrics.mean_net_r > ZERO for item in eligible)
        ) / Decimal(len(eligible))

    if (
        test_metrics.mean_net_r <= ZERO
        or confidence_interval.lower <= ZERO
        or aggregate_mean_net_r <= ZERO
        or positive_fraction < policy.positive_walkforward_fraction
        or test_metrics.max_market_positive_pnl_share is None
        or test_metrics.max_market_positive_pnl_share > MARKET_CONCENTRATION_LIMIT
        or test_metrics.max_seven_day_positive_pnl_share is None
        or test_metrics.max_seven_day_positive_pnl_share > SEVEN_DAY_CONCENTRATION_LIMIT
    ):
        return EdgeEvidenceStatus.NO_EDGE_DEMONSTRATED

    return EdgeEvidenceStatus.CANDIDATE_EDGE


def build_promotion_preview(
    metrics: PerformanceMetrics,
    *,
    invariant_health_pass: bool | None,
) -> PromotionGatePreview:
    profit_factor_pass = (
        None
        if metrics.profit_factor is None
        else metrics.profit_factor >= LIVE_PROFIT_FACTOR_LIMIT
    )
    max_drawdown_pass = (
        None
        if metrics.account_equity_max_drawdown_fraction is None
        else metrics.account_equity_max_drawdown_fraction <= LIVE_DRAWDOWN_LIMIT
    )
    market_concentration_pass = (
        None
        if metrics.max_market_positive_pnl_share is None
        else metrics.max_market_positive_pnl_share <= MARKET_CONCENTRATION_LIMIT
    )
    seven_day_concentration_pass = (
        None
        if metrics.max_seven_day_positive_pnl_share is None
        else metrics.max_seven_day_positive_pnl_share <= SEVEN_DAY_CONCENTRATION_LIMIT
    )

    reasons: list[str] = []
    checks = (
        ("PROFIT_FACTOR", profit_factor_pass),
        ("ACCOUNT_DRAWDOWN", max_drawdown_pass),
        ("MARKET_CONCENTRATION", market_concentration_pass),
        ("SEVEN_DAY_CONCENTRATION", seven_day_concentration_pass),
        ("CLOSED_TRADE_COUNT", metrics.trade_count >= LIVE_TRADE_COUNT),
        ("COVERED_DAYS", metrics.covered_days >= LIVE_COVERED_DAYS),
        ("INVARIANT_HEALTH", invariant_health_pass),
    )
    for label, result in checks:
        if result is None:
            reasons.append(f"{label}_UNAVAILABLE")
        elif not result:
            reasons.append(f"{label}_FAIL")

    return PromotionGatePreview(
        profit_factor_pass=profit_factor_pass,
        max_drawdown_pass=max_drawdown_pass,
        market_concentration_pass=market_concentration_pass,
        seven_day_concentration_pass=seven_day_concentration_pass,
        closed_trade_count_pass=metrics.trade_count >= LIVE_TRADE_COUNT,
        covered_days_pass=metrics.covered_days >= LIVE_COVERED_DAYS,
        invariant_health_pass=invariant_health_pass,
        reason_codes=tuple(reasons),
    )


def _validate_request(request: EvaluationRequest) -> None:
    policy_id = request.policy.policy_id
    if request.split.dataset_manifest_id != request.dataset.manifest_id:
        raise ValueError("split dataset does not match evaluation dataset")
    if request.split.policy_id != policy_id:
        raise ValueError("split policy does not match evaluation policy")
    if request.split.embargo_ms != request.policy.split_embargo_ms:
        raise ValueError("split embargo does not match evaluation policy")
    if request.candidates.policy_id != policy_id:
        raise ValueError("candidate set policy does not match evaluation policy")
    if request.walkforward_plan.dataset_manifest_id != request.dataset.manifest_id:
        raise ValueError("walk-forward dataset does not match evaluation dataset")
    if request.walkforward_plan.policy_id != policy_id:
        raise ValueError("walk-forward policy does not match evaluation policy")
    if request.walkforward_plan.embargo_ms != request.policy.split_embargo_ms:
        raise ValueError("walk-forward embargo does not match evaluation policy")

    requested_ids = tuple(sorted(item.profile_id for item in request.sensitivity_profiles))
    if requested_ids != request.candidates.sensitivity_profile_ids:
        raise ValueError("sensitivity profiles do not match frozen candidate set")
    predeclared = {item.profile_id: item for item in predeclared_cost_stress_profiles()}
    for profile in request.sensitivity_profiles:
        if predeclared.get(profile.profile_id) != profile:
            raise ValueError("sensitivity profile is not the predeclared frozen profile")


def _request_digest(request: EvaluationRequest) -> str:
    payload = {
        "dataset_manifest_id": request.dataset.manifest_id,
        "split_manifest_id": request.split.split_manifest_id,
        "candidate_set_id": request.candidates.candidate_set_id,
        "policy_id": request.policy.policy_id,
        "walkforward_plan": {
            "dataset_manifest_id": request.walkforward_plan.dataset_manifest_id,
            "first_window_start_ms": request.walkforward_plan.first_window_start_ms,
            "development_duration_ms": request.walkforward_plan.development_duration_ms,
            "validation_duration_ms": request.walkforward_plan.validation_duration_ms,
            "evaluation_duration_ms": request.walkforward_plan.evaluation_duration_ms,
            "step_ms": request.walkforward_plan.step_ms,
            "embargo_ms": request.walkforward_plan.embargo_ms,
            "expanding": request.walkforward_plan.expanding,
            "policy_id": request.walkforward_plan.policy_id,
        },
        "sensitivity_profile_ids": tuple(
            sorted(item.profile_id for item in request.sensitivity_profiles)
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sensitivity_report_ids(
    samples: Sequence[TradeEvaluationSample],
    profiles: Sequence[CostStressProfile],
) -> tuple[str, ...]:
    ordered_samples = tuple(sorted(samples, key=lambda item: item.trade_id))
    reports: list[str] = []
    for profile in sorted(profiles, key=lambda item: item.profile_id):
        payload = {
            "profile": {
                "profile_id": profile.profile_id,
                "fee_multiplier": str(profile.fee_multiplier),
                "adverse_slippage_multiplier": str(profile.adverse_slippage_multiplier),
                "adverse_funding_multiplier": str(profile.adverse_funding_multiplier),
                "remove_favorable_slippage": profile.remove_favorable_slippage,
                "remove_favorable_funding": profile.remove_favorable_funding,
            },
            "stressed_samples": tuple(
                (item.trade_id, str(apply_cost_stress(item, profile)))
                for item in ordered_samples
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        reports.append(hashlib.sha256(encoded).hexdigest()[:24])
    return tuple(sorted(reports))


def _edge_reason_codes(status: EdgeEvidenceStatus) -> tuple[str, ...]:
    return (status.value.upper(),)


class EvaluationEngine:
    def __init__(
        self,
        journal: JournalStore,
        facts: EvaluationFactStore,
    ) -> None:
        self.journal = journal
        self.facts = facts

    def _invalid_result(
        self,
        request: EvaluationRequest,
        *,
        reason: str,
    ) -> EvaluationResult:
        empty = compute_performance_metrics(())
        result = EvaluationResult(
            dataset_manifest_id=request.dataset.manifest_id,
            split_manifest_id=request.split.split_manifest_id,
            candidate_set_id=request.candidates.candidate_set_id,
            policy_id=request.policy.policy_id,
            oos_status=OOSStatus.UNTOUCHED,
            train_metrics=empty,
            validation_metrics=empty,
            test_metrics=empty,
            mean_net_r_confidence_interval=None,
            walkforward_results=(),
            slice_reports=(),
            sensitivity_report_ids=(),
            no_trade_report_ids=(),
            edge_status=EdgeEvidenceStatus.INVALID_EVIDENCE,
            promotion_preview=build_promotion_preview(
                empty,
                invariant_health_pass=None,
            ),
            included_sample_count=0,
            excluded_sample_count=0,
            reason_codes=(reason,),
        )
        self.facts.record_evaluation_result(result)
        return result

    def run(self, request: EvaluationRequest) -> EvaluationResult:
        _validate_request(request)
        run_ids = tuple(source.run_id for source in request.dataset.sources)
        try:
            rebuilt = build_evaluation_dataset(
                self.journal,
                self.facts,
                replay_run_ids=run_ids,
                code_revision=request.dataset.code_revision,
                allow_mixed_evidence=request.dataset.mixed_evidence_diagnostic,
            )
        except EvaluationDatasetError:
            return self._invalid_result(request, reason="DATASET_RECONCILIATION_FAILED")

        evidence_valid = (
            rebuilt.manifest == request.dataset
            and not rebuilt.exclusion_reasons
            and request.dataset.data_complete
            and not request.dataset.mixed_evidence_diagnostic
            and all(source.data_complete for source in request.dataset.sources)
        )
        if not evidence_valid:
            return self._invalid_result(request, reason="INVALID_DATASET_EVIDENCE")

        observed_oos = consume_untouched_test(
            self.facts,
            request.split,
            request.candidates,
            request.policy,
        )
        semantic_oos = (
            OOSStatus.UNTOUCHED
            if observed_oos is OOSStatus.REPRODUCTION
            else observed_oos
        )

        partitions = split_samples(rebuilt.samples, request.split)
        train_samples = partitions[SplitName.TRAIN]
        validation_samples = partitions[SplitName.VALIDATION]
        test_samples = partitions[SplitName.TEST]
        train_metrics = compute_performance_metrics(train_samples)
        validation_metrics = compute_performance_metrics(validation_samples)
        test_metrics = compute_performance_metrics(test_samples)
        confidence = mean_net_r_confidence_interval(
            test_samples,
            evaluation_manifest_id=_request_digest(request),
            policy=request.policy,
        )
        windows = generate_walkforward_windows(
            request.walkforward_plan,
            dataset_end_ms=request.dataset.end_ms,
        )
        walkforward_results = evaluate_walkforward(
            rebuilt.samples,
            windows,
            policy=request.policy,
        )
        slice_reports = evaluate_slices(test_samples, policy=request.policy)
        sensitivity_report_ids = _sensitivity_report_ids(
            test_samples,
            request.sensitivity_profiles,
        )
        edge_status = derive_edge_status(
            evidence_valid=True,
            oos_status=semantic_oos,
            test_metrics=test_metrics,
            confidence_interval=confidence,
            walkforward_results=walkforward_results,
            policy=request.policy,
        )

        included_samples = tuple(
            sorted(
                (*train_samples, *validation_samples, *test_samples),
                key=lambda item: (item.closed_at_ms, item.trade_id),
            )
        )
        included_ids = {item.trade_id for item in included_samples}
        excluded_count = len(rebuilt.excluded_trade_ids) + sum(
            item.trade_id not in included_ids for item in rebuilt.samples
        )
        preview_metrics = compute_performance_metrics(included_samples)
        result = EvaluationResult(
            dataset_manifest_id=request.dataset.manifest_id,
            split_manifest_id=request.split.split_manifest_id,
            candidate_set_id=request.candidates.candidate_set_id,
            policy_id=request.policy.policy_id,
            oos_status=semantic_oos,
            train_metrics=train_metrics,
            validation_metrics=validation_metrics,
            test_metrics=test_metrics,
            mean_net_r_confidence_interval=confidence,
            walkforward_results=walkforward_results,
            slice_reports=slice_reports,
            sensitivity_report_ids=sensitivity_report_ids,
            no_trade_report_ids=(),
            edge_status=edge_status,
            promotion_preview=build_promotion_preview(
                preview_metrics,
                invariant_health_pass=None,
            ),
            included_sample_count=len(included_samples),
            excluded_sample_count=excluded_count,
            reason_codes=_edge_reason_codes(edge_status),
        )
        self.facts.record_evaluation_result(result)
        if observed_oos is not OOSStatus.CONTAMINATED:
            self.facts.bind_oos_consumption(
                test_partition_digest=request.split.test_partition_digest,
                candidate_set_id=request.candidates.candidate_set_id,
                policy_id=request.policy.policy_id,
                evaluation_id=result.evaluation_id,
            )
        return result
