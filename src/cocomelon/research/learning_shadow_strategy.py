from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cocomelon.domain.strategy import Direction, StrategyContext, StrategyDecision
from cocomelon.research.learning_candidate_predictor import (
    LearningCandidatePredictor,
    build_learning_candidate_predictor,
)
from cocomelon.research.learning_shadow_admission import (
    LearningShadowAdmission,
    verify_learning_shadow_admission,
)
from cocomelon.research.learning_training_rows import SNAPSHOT_FEATURES
from cocomelon.strategies.engine import evaluate_strategies

LEARNED_SHADOW_LEAD_STRATEGY = "learned_shadow_filter"


class LearningShadowStrategyError(RuntimeError):
    pass


def _snapshot_feature_value(context: StrategyContext, feature: str) -> str:
    value = getattr(context.feature_snapshot, feature)
    if value is None:
        raise LearningShadowStrategyError(
            f"LEARNING_SHADOW_FEATURE_MISSING:{feature}"
        )
    if feature in {"trend_regime", "volatility_regime"}:
        return str(value.value)
    return str(value)


def resolve_learning_shadow_feature_values(
    context: StrategyContext,
    *,
    direction: Direction,
    feature_registry: tuple[str, ...],
) -> tuple[str, ...]:
    if direction is Direction.NO_TRADE:
        raise LearningShadowStrategyError(
            "LEARNING_SHADOW_DIRECTIONAL_FEATURES_REQUIRED"
        )

    values: list[str] = []
    for feature in feature_registry:
        if feature == "market":
            values.append(context.feature_snapshot.market.canonical)
            continue
        if feature == "direction":
            values.append(direction.value)
            continue
        if feature in SNAPSHOT_FEATURES:
            values.append(_snapshot_feature_value(context, feature))
            continue
        raise LearningShadowStrategyError(
            f"LEARNING_SHADOW_FEATURE_UNSUPPORTED:{feature}"
        )
    return tuple(values)


def _reason_codes(
    source: StrategyDecision,
    *,
    admission: LearningShadowAdmission,
    outcome: str,
) -> tuple[str, ...]:
    return (
        *source.reason_codes,
        f"learned_shadow_admission:{admission.shadow_admission_id}",
        outcome,
    )


def _no_trade(
    source: StrategyDecision,
    *,
    admission: LearningShadowAdmission,
    reason: str,
) -> StrategyDecision:
    return StrategyDecision(
        market=source.market,
        direction=Direction.NO_TRADE,
        score=source.score,
        timestamp_ms=source.timestamp_ms,
        feature_snapshot_id=source.feature_snapshot_id,
        lead_strategy=None,
        invalidation_price=None,
        signal_ids=source.signal_ids,
        reason_codes=_reason_codes(
            source,
            admission=admission,
            outcome=reason,
        ),
    )


@dataclass(slots=True)
class LearningShadowStrategyEvaluator:
    predictor: LearningCandidatePredictor
    admission: LearningShadowAdmission

    def __post_init__(self) -> None:
        if self.predictor.package.candidate_id != self.admission.candidate_id:
            raise ValueError("shadow strategy candidate identity mismatch")
        if (
            self.predictor.package.package_id
            != self.admission.candidate_package_id
        ):
            raise ValueError("shadow strategy package identity mismatch")
        if self.predictor.spec.spec_id != self.admission.validation_spec_id:
            raise ValueError("shadow strategy validation spec identity mismatch")

    @property
    def feature_registry(self) -> tuple[str, ...]:
        return self.predictor.feature_registry

    def evaluate(self, context: StrategyContext) -> StrategyDecision:
        source = evaluate_strategies(context).decision

        if context.as_of_ms < self.admission.shadow_start_ms:
            return _no_trade(
                source,
                admission=self.admission,
                reason="learned_shadow_before_admission",
            )

        if source.direction is Direction.NO_TRADE:
            return _no_trade(
                source,
                admission=self.admission,
                reason="learned_shadow_source_no_trade",
            )

        feature_values = resolve_learning_shadow_feature_values(
            context,
            direction=source.direction,
            feature_registry=self.predictor.feature_registry,
        )
        prediction = self.predictor.score(
            feature_values=feature_values,
            observed_at_ms=context.feature_snapshot.as_of_ms,
        )
        if not prediction.trade_eligible:
            return _no_trade(
                source,
                admission=self.admission,
                reason="learned_shadow_filter_reject",
            )

        return StrategyDecision(
            market=source.market,
            direction=source.direction,
            score=source.score,
            timestamp_ms=source.timestamp_ms,
            feature_snapshot_id=source.feature_snapshot_id,
            lead_strategy=source.lead_strategy,
            invalidation_price=source.invalidation_price,
            signal_ids=source.signal_ids,
            reason_codes=_reason_codes(
                source,
                admission=self.admission,
                outcome="learned_shadow_filter_accept",
            ),
        )


def build_learning_shadow_strategy_evaluator(
    *,
    package_root: Path,
    validation_spec_path: Path,
    shadow_admission_path: Path,
    review_decision_path: Path,
    review_dossier_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    clean_evidence_root: Path,
) -> LearningShadowStrategyEvaluator:
    admission = verify_learning_shadow_admission(
        shadow_admission_path,
        review_decision_path=review_decision_path,
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        evidence_root=clean_evidence_root,
    )
    predictor = build_learning_candidate_predictor(
        package_root=package_root,
        validation_spec_path=validation_spec_path,
    )
    return LearningShadowStrategyEvaluator(
        predictor=predictor,
        admission=admission,
    )
