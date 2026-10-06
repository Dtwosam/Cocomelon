from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.evaluation import DecisionEvaluationFact
from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_decision_facts import (
    ContinuousPaperDecisionFactStore,
)
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
)

ZERO: Final = Decimal("0")
NO_TRADE_FORWARD_SCHEMA_VERSION = 1
FORWARD_HORIZON_FIELDS: Final = {
    15 * 60 * 1000: "return_15m",
    60 * 60 * 1000: "return_1h",
}
MARGINAL_CONTEXT_DIMENSIONS: Final = (
    "trend_regime",
    "volatility_regime",
    "return_15m_sign",
    "return_1h_sign",
    "funding_sign",
    "book_imbalance_sign",
)


class NoTradeForwardOpportunityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ResolvedDecision:
    fact: DecisionEvaluationFact
    feature: FeatureSnapshot


@dataclass(frozen=True, slots=True)
class NoTradeForwardOutcome:
    decision_fact_id: str
    strategy_decision_id: str
    market: str
    decision_timestamp_ms: int
    feature_snapshot_id: str
    feature_as_of_ms: int
    horizon_ms: int
    target_as_of_ms: int
    forward_mark_return: Decimal
    favored_direction: Direction
    reason_codes: tuple[str, ...]
    trend_regime: str
    volatility_regime: str
    return_15m_sign: str
    return_1h_sign: str
    funding_sign: str
    book_imbalance_sign: str

    def __post_init__(self) -> None:
        if self.favored_direction not in {
            Direction.LONG,
            Direction.SHORT,
            Direction.NO_TRADE,
        }:
            raise ValueError("favored_direction is invalid")
        if not self.forward_mark_return.is_finite():
            raise ValueError("forward_mark_return must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "decision_fact_id": self.decision_fact_id,
            "strategy_decision_id": self.strategy_decision_id,
            "market": self.market,
            "decision_timestamp_ms": self.decision_timestamp_ms,
            "feature_snapshot_id": self.feature_snapshot_id,
            "feature_as_of_ms": self.feature_as_of_ms,
            "horizon_ms": self.horizon_ms,
            "target_as_of_ms": self.target_as_of_ms,
            "forward_mark_return": str(self.forward_mark_return),
            "favored_direction": self.favored_direction.value,
            "reason_codes": self.reason_codes,
            "trend_regime": self.trend_regime,
            "volatility_regime": self.volatility_regime,
            "return_15m_sign": self.return_15m_sign,
            "return_1h_sign": self.return_1h_sign,
            "funding_sign": self.funding_sign,
            "book_imbalance_sign": self.book_imbalance_sign,
        }


@dataclass(frozen=True, slots=True)
class NoTradeForwardOpportunityReport:
    as_of_ms: int
    min_group_rows: int
    decision_records: int
    no_trade_decisions: int
    resolved_decisions: int
    missing_feature_snapshot_ids: tuple[str, ...]
    censored_by_horizon: dict[str, int]
    missing_future_snapshot_by_horizon: dict[str, int]
    missing_forward_return_by_horizon: dict[str, int]
    horizon_summary: dict[str, object]
    reason_summary: dict[str, tuple[dict[str, object], ...]]
    marginal_summary: dict[str, tuple[dict[str, object], ...]]
    outcomes: tuple[NoTradeForwardOutcome, ...]
    decision_state_digest: str
    feature_state_digest: str
    schema_version: int = NO_TRADE_FORWARD_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of_ms": self.as_of_ms,
            "min_group_rows": self.min_group_rows,
            "decision_records": self.decision_records,
            "no_trade_decisions": self.no_trade_decisions,
            "resolved_decisions": self.resolved_decisions,
            "missing_feature_snapshot_ids": self.missing_feature_snapshot_ids,
            "censored_by_horizon": self.censored_by_horizon,
            "missing_future_snapshot_by_horizon": (
                self.missing_future_snapshot_by_horizon
            ),
            "missing_forward_return_by_horizon": (
                self.missing_forward_return_by_horizon
            ),
            "horizon_summary": self.horizon_summary,
            "reason_summary": self.reason_summary,
            "marginal_summary": self.marginal_summary,
            "outcomes": tuple(item.to_dict() for item in self.outcomes),
            "decision_state_digest": self.decision_state_digest,
            "feature_state_digest": self.feature_state_digest,
            "forward_label": "future_trailing_candle_return",
            "hypothetical_pnl": False,
            "cost_complete": False,
            "diagnostic_only": True,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def _sign_bucket(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value > ZERO:
        return "positive"
    if value < ZERO:
        return "negative"
    return "flat"


def _favored_direction(value: Decimal) -> Direction:
    if value > ZERO:
        return Direction.LONG
    if value < ZERO:
        return Direction.SHORT
    return Direction.NO_TRADE


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _metrics(
    outcomes: tuple[NoTradeForwardOutcome, ...],
    *,
    min_group_rows: int,
) -> dict[str, object]:
    values = tuple(item.forward_mark_return for item in outcomes)
    mean = _mean(values)
    mean_abs = _mean(tuple(abs(value) for value in values))
    return {
        "outcomes": len(outcomes),
        "favored_long": sum(
            item.favored_direction is Direction.LONG for item in outcomes
        ),
        "favored_short": sum(
            item.favored_direction is Direction.SHORT for item in outcomes
        ),
        "flat": sum(
            item.favored_direction is Direction.NO_TRADE
            for item in outcomes
        ),
        "mean_forward_mark_return": None if mean is None else str(mean),
        "mean_absolute_forward_mark_return": (
            None if mean_abs is None else str(mean_abs)
        ),
        "sample_sufficient_for_diagnostics": (
            len(outcomes) >= min_group_rows
        ),
        "strategy_authority": False,
    }


def _marginal_value(
    item: NoTradeForwardOutcome,
    dimension: str,
) -> str:
    value = getattr(item, dimension)
    if not isinstance(value, str):
        raise NoTradeForwardOpportunityError(
            "NO_TRADE_FORWARD_CONTEXT_VALUE_INVALID"
        )
    return value


def _grouped_summary(
    outcomes: tuple[NoTradeForwardOutcome, ...],
    *,
    min_group_rows: int,
    key_name: str,
    key_values: tuple[tuple[str, NoTradeForwardOutcome], ...],
) -> tuple[dict[str, object], ...]:
    grouped: defaultdict[tuple[int, str], list[NoTradeForwardOutcome]]
    grouped = defaultdict(list)
    for value, item in key_values:
        grouped[(item.horizon_ms, value)].append(item)

    payload: list[dict[str, object]] = []
    for horizon_ms, value in sorted(grouped):
        cohort = tuple(grouped[(horizon_ms, value)])
        payload.append(
            {
                "horizon_ms": horizon_ms,
                key_name: value,
                **_metrics(cohort, min_group_rows=min_group_rows),
            }
        )
    return tuple(payload)


def _reason_summary(
    outcomes: tuple[NoTradeForwardOutcome, ...],
    *,
    min_group_rows: int,
) -> dict[str, tuple[dict[str, object], ...]]:
    values: list[tuple[str, NoTradeForwardOutcome]] = []
    for item in outcomes:
        reasons = item.reason_codes or ("none",)
        values.extend((reason, item) for reason in reasons)
    return {
        "reason_code": _grouped_summary(
            outcomes,
            min_group_rows=min_group_rows,
            key_name="reason_code",
            key_values=tuple(values),
        )
    }


def _marginal_summary(
    outcomes: tuple[NoTradeForwardOutcome, ...],
    *,
    min_group_rows: int,
) -> dict[str, tuple[dict[str, object], ...]]:
    payload: dict[str, tuple[dict[str, object], ...]] = {}
    for dimension in MARGINAL_CONTEXT_DIMENSIONS:
        key_values = tuple(
            (_marginal_value(item, dimension), item)
            for item in outcomes
        )
        payload[dimension] = _grouped_summary(
            outcomes,
            min_group_rows=min_group_rows,
            key_name="value",
            key_values=key_values,
        )
    return payload


def _horizon_summary(
    outcomes: tuple[NoTradeForwardOutcome, ...],
    *,
    min_group_rows: int,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for horizon_ms in sorted(FORWARD_HORIZON_FIELDS):
        cohort = tuple(
            item for item in outcomes if item.horizon_ms == horizon_ms
        )
        payload[str(horizon_ms)] = _metrics(
            cohort,
            min_group_rows=min_group_rows,
        )
    return payload


def build_no_trade_forward_opportunity_report(
    decisions: ContinuousPaperDecisionFactStore,
    features: LearningFeatureSnapshotStore,
    *,
    as_of_ms: int,
    min_group_rows: int = 20,
) -> NoTradeForwardOpportunityReport:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if min_group_rows <= 0:
        raise ValueError("min_group_rows must be positive")

    verified_decisions = decisions.iter_verified()
    no_trade = tuple(
        item.fact
        for item in verified_decisions
        if item.fact.direction is Direction.NO_TRADE
        and item.fact.timestamp_ms <= as_of_ms
    )

    verified_features = features.iter_verified()
    future_index: dict[tuple[str, int], FeatureSnapshot] = {}
    for verified in verified_features:
        snapshot = verified.snapshot
        key = (snapshot.market.canonical, snapshot.as_of_ms)
        if key in future_index:
            raise NoTradeForwardOpportunityError(
                "NO_TRADE_FORWARD_DUPLICATE_MARKET_TIMESTAMP"
            )
        future_index[key] = snapshot

    resolved: list[_ResolvedDecision] = []
    missing_features: list[str] = []
    for fact in no_trade:
        verified = features.load(fact.feature_snapshot_id)
        if verified is None:
            missing_features.append(fact.feature_snapshot_id)
            continue
        feature = verified.snapshot
        if feature.market != fact.market:
            raise NoTradeForwardOpportunityError(
                "NO_TRADE_FORWARD_FEATURE_MARKET_MISMATCH"
            )
        if feature.as_of_ms > fact.timestamp_ms:
            raise NoTradeForwardOpportunityError(
                "NO_TRADE_FORWARD_FEATURE_AFTER_DECISION"
            )
        if feature.source_received_at_ms > fact.timestamp_ms:
            raise NoTradeForwardOpportunityError(
                "NO_TRADE_FORWARD_FEATURE_SOURCE_AFTER_DECISION"
            )
        resolved.append(_ResolvedDecision(fact=fact, feature=feature))

    censored = {
        str(horizon_ms): 0 for horizon_ms in FORWARD_HORIZON_FIELDS
    }
    missing_future = {
        str(horizon_ms): 0 for horizon_ms in FORWARD_HORIZON_FIELDS
    }
    missing_return = {
        str(horizon_ms): 0 for horizon_ms in FORWARD_HORIZON_FIELDS
    }
    outcomes: list[NoTradeForwardOutcome] = []

    for row in resolved:
        for horizon_ms, field in FORWARD_HORIZON_FIELDS.items():
            target_as_of_ms = row.feature.as_of_ms + horizon_ms
            if target_as_of_ms > as_of_ms:
                censored[str(horizon_ms)] += 1
                continue
            future = future_index.get(
                (row.fact.market.canonical, target_as_of_ms)
            )
            if future is None:
                missing_future[str(horizon_ms)] += 1
                continue
            if future.source_received_at_ms > as_of_ms:
                censored[str(horizon_ms)] += 1
                continue
            raw_return = getattr(future, field)
            if not isinstance(raw_return, Decimal):
                missing_return[str(horizon_ms)] += 1
                continue
            outcomes.append(
                NoTradeForwardOutcome(
                    decision_fact_id=row.fact.fact_id,
                    strategy_decision_id=row.fact.strategy_decision_id,
                    market=row.fact.market.canonical,
                    decision_timestamp_ms=row.fact.timestamp_ms,
                    feature_snapshot_id=row.fact.feature_snapshot_id,
                    feature_as_of_ms=row.feature.as_of_ms,
                    horizon_ms=horizon_ms,
                    target_as_of_ms=target_as_of_ms,
                    forward_mark_return=raw_return,
                    favored_direction=_favored_direction(raw_return),
                    reason_codes=row.fact.reason_codes,
                    trend_regime=row.feature.trend_regime.value,
                    volatility_regime=row.feature.volatility_regime.value,
                    return_15m_sign=_sign_bucket(
                        row.feature.return_15m
                    ),
                    return_1h_sign=_sign_bucket(row.feature.return_1h),
                    funding_sign=_sign_bucket(row.feature.funding),
                    book_imbalance_sign=_sign_bucket(
                        row.feature.book_imbalance
                    ),
                )
            )

    ordered_outcomes = tuple(
        sorted(
            outcomes,
            key=lambda item: (
                item.decision_timestamp_ms,
                item.market,
                item.horizon_ms,
                item.decision_fact_id,
            ),
        )
    )
    return NoTradeForwardOpportunityReport(
        as_of_ms=as_of_ms,
        min_group_rows=min_group_rows,
        decision_records=len(verified_decisions),
        no_trade_decisions=len(no_trade),
        resolved_decisions=len(resolved),
        missing_feature_snapshot_ids=tuple(sorted(set(missing_features))),
        censored_by_horizon=censored,
        missing_future_snapshot_by_horizon=missing_future,
        missing_forward_return_by_horizon=missing_return,
        horizon_summary=_horizon_summary(
            ordered_outcomes,
            min_group_rows=min_group_rows,
        ),
        reason_summary=_reason_summary(
            ordered_outcomes,
            min_group_rows=min_group_rows,
        ),
        marginal_summary=_marginal_summary(
            ordered_outcomes,
            min_group_rows=min_group_rows,
        ),
        outcomes=ordered_outcomes,
        decision_state_digest=decisions.state_digest,
        feature_state_digest=features.state_digest,
    )
