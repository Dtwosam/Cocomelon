from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from itertools import combinations
from typing import Final, cast

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
BPS: Final = Decimal("10000")
NO_TRADE_CONTEXT_STABILITY_SCHEMA_VERSION = 3
DEFAULT_MATERIAL_THRESHOLDS_BPS: Final = (50, 100, 200)
DEFAULT_VALIDATION_BLOCK_COUNT = 3
DEFAULT_MIN_VALIDATION_BLOCK_ROWS = 5
DEFAULT_MIN_VALIDATION_BLOCK_DIRECTION_SHARE = Decimal("0.50")
DEFAULT_REQUIRED_VALIDATION_BLOCKS = 3
ELIGIBLE_DECISION_STAGES: Final = ("strategy_abstained",)
KNOWN_DECISION_STAGES: Final = frozenset(
    {"strategy_abstained", "eligibility_blocked", "other"}
)
DEFAULT_CONTEXT_DIMENSIONS: Final = (
    "market",
    "reason_code",
    "trend_regime",
    "volatility_regime",
    "return_15m_sign",
    "return_1h_sign",
    "funding_sign",
    "book_imbalance_sign",
)


class NoTradeContextStabilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _Outcome:
    decision_timestamp_ms: int
    horizon_ms: int
    forward_return: Decimal
    market: str
    reason_codes: tuple[str, ...]
    decision_stage: str
    context: dict[str, str]

    @property
    def direction(self) -> str:
        if self.forward_return > ZERO:
            return "long"
        if self.forward_return < ZERO:
            return "short"
        return "no_trade"


@dataclass(frozen=True, slots=True)
class ContextStabilityCandidate:
    horizon_ms: int
    threshold_bps: int
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    dominant_direction: str
    discovery_material_outcomes: int
    discovery_direction_share: Decimal
    validation_material_outcomes: int
    validation_same_direction_share: Decimal | None
    validation_baseline_direction_share: Decimal | None
    validation_lift_vs_baseline: Decimal | None
    validation_block_outcomes: tuple[int, ...]
    validation_block_direction_shares: tuple[Decimal | None, ...]
    validation_blocks_meeting_row_floor: int
    validation_blocks_directionally_consistent: int
    stable_across_validation_blocks: bool
    stable_on_validation: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon_ms": self.horizon_ms,
            "threshold_bps": self.threshold_bps,
            "dimensions": self.dimensions,
            "values": self.values,
            "dominant_direction": self.dominant_direction,
            "discovery_material_outcomes": self.discovery_material_outcomes,
            "discovery_direction_share": str(self.discovery_direction_share),
            "validation_material_outcomes": self.validation_material_outcomes,
            "validation_same_direction_share": (
                None
                if self.validation_same_direction_share is None
                else str(self.validation_same_direction_share)
            ),
            "validation_baseline_direction_share": (
                None
                if self.validation_baseline_direction_share is None
                else str(self.validation_baseline_direction_share)
            ),
            "validation_lift_vs_baseline": (
                None
                if self.validation_lift_vs_baseline is None
                else str(self.validation_lift_vs_baseline)
            ),
            "validation_block_outcomes": self.validation_block_outcomes,
            "validation_block_direction_shares": tuple(
                None if value is None else str(value)
                for value in self.validation_block_direction_shares
            ),
            "validation_blocks_meeting_row_floor": (
                self.validation_blocks_meeting_row_floor
            ),
            "validation_blocks_directionally_consistent": (
                self.validation_blocks_directionally_consistent
            ),
            "stable_across_validation_blocks": (
                self.stable_across_validation_blocks
            ),
            "stable_on_validation": self.stable_on_validation,
            "strategy_authority": False,
        }


@dataclass(frozen=True, slots=True)
class ContextStabilityAnalysis:
    horizon_ms: int
    threshold_bps: int
    split_timestamp_ms: int
    labeled_outcomes: int
    discovery_material_outcomes: int
    validation_material_outcomes: int
    discovered_candidate_count: int
    validated_candidate_count: int
    candidates: tuple[ContextStabilityCandidate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "horizon_ms": self.horizon_ms,
            "threshold_bps": self.threshold_bps,
            "split_timestamp_ms": self.split_timestamp_ms,
            "labeled_outcomes": self.labeled_outcomes,
            "discovery_material_outcomes": self.discovery_material_outcomes,
            "validation_material_outcomes": self.validation_material_outcomes,
            "discovered_candidate_count": self.discovered_candidate_count,
            "validated_candidate_count": self.validated_candidate_count,
            "candidates": tuple(item.to_dict() for item in self.candidates),
        }


@dataclass(frozen=True, slots=True)
class NoTradeContextStabilityReport:
    source_decision_state_digest: str
    source_feature_state_digest: str
    split_fraction: Decimal
    min_discovery_rows: int
    min_validation_rows: int
    min_discovery_direction_share: Decimal
    min_validation_direction_share: Decimal
    min_validation_lift: Decimal
    validation_block_count: int
    min_validation_block_rows: int
    min_validation_block_direction_share: Decimal
    required_validation_blocks: int
    material_thresholds_bps: tuple[int, ...]
    source_outcome_count: int
    strategy_abstained_outcomes: int
    eligibility_blocked_outcomes: int
    other_outcomes: int
    eligible_decision_stages: tuple[str, ...]
    analyses: tuple[ContextStabilityAnalysis, ...]
    schema_version: int = NO_TRADE_CONTEXT_STABILITY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "source_decision_state_digest": self.source_decision_state_digest,
            "source_feature_state_digest": self.source_feature_state_digest,
            "split_fraction": str(self.split_fraction),
            "min_discovery_rows": self.min_discovery_rows,
            "min_validation_rows": self.min_validation_rows,
            "min_discovery_direction_share": str(
                self.min_discovery_direction_share
            ),
            "min_validation_direction_share": str(
                self.min_validation_direction_share
            ),
            "min_validation_lift": str(self.min_validation_lift),
            "validation_block_count": self.validation_block_count,
            "min_validation_block_rows": self.min_validation_block_rows,
            "min_validation_block_direction_share": str(
                self.min_validation_block_direction_share
            ),
            "required_validation_blocks": self.required_validation_blocks,
            "material_thresholds_bps": self.material_thresholds_bps,
            "source_outcome_count": self.source_outcome_count,
            "strategy_abstained_outcomes": self.strategy_abstained_outcomes,
            "eligibility_blocked_outcomes": self.eligibility_blocked_outcomes,
            "other_outcomes": self.other_outcomes,
            "eligible_decision_stages": self.eligible_decision_stages,
            "directional_candidate_source": "strategy_abstained_only",
            "analyses": tuple(item.to_dict() for item in self.analyses),
            "validated_candidate_count": sum(
                item.validated_candidate_count for item in self.analyses
            ),
            "chronological_holdout_required": True,
            "validation_block_consistency_required": True,
            "market_aware": True,
            "material_move_only": True,
            "exploratory_only": True,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise NoTradeContextStabilityError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise NoTradeContextStabilityError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise NoTradeContextStabilityError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NoTradeContextStabilityError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise NoTradeContextStabilityError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise NoTradeContextStabilityError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise NoTradeContextStabilityError(f"{field} must be finite")
    return result


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return Decimal(numerator) / Decimal(denominator)


def _parse_outcome(raw_value: object) -> _Outcome:
    raw = _mapping(raw_value, "outcome")
    reasons_raw = _sequence(raw.get("reason_codes"), "reason_codes")
    reasons = tuple(
        _string(value, "reason_codes item") for value in reasons_raw
    ) or ("none",)
    context = {
        field: _string(raw.get(field), field)
        for field in DEFAULT_CONTEXT_DIMENSIONS
        if field != "reason_code"
    }
    decision_stage = _string(raw.get("decision_stage"), "decision_stage")
    if decision_stage not in KNOWN_DECISION_STAGES:
        raise NoTradeContextStabilityError(
            "decision_stage is not recognized"
        )
    outcome = _Outcome(
        decision_timestamp_ms=_integer(
            raw.get("decision_timestamp_ms"),
            "decision_timestamp_ms",
        ),
        horizon_ms=_integer(raw.get("horizon_ms"), "horizon_ms"),
        forward_return=_decimal(
            raw.get("forward_mark_return"),
            "forward_mark_return",
        ),
        reason_codes=reasons,
        decision_stage=decision_stage,
        context=context,
    )
    favored = _string(raw.get("favored_direction"), "favored_direction")
    if favored != outcome.direction:
        raise NoTradeContextStabilityError(
            "favored_direction does not match forward return"
        )
    return outcome


def _context_keys(
    outcome: _Outcome,
    dimensions: tuple[str, str],
) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, ...]] = []
    for dimension in dimensions:
        if dimension == "reason_code":
            values.append(outcome.reason_codes)
        else:
            values.append((outcome.context[dimension],))
    return tuple(
        (left, right)
        for left in values[0]
        for right in values[1]
    )


def _material(
    outcome: _Outcome,
    *,
    threshold_bps: int,
) -> bool:
    threshold = Decimal(threshold_bps) / BPS
    return abs(outcome.forward_return) >= threshold


def _split_rows(
    rows: tuple[_Outcome, ...],
    *,
    split_fraction: Decimal,
) -> tuple[int, tuple[_Outcome, ...], tuple[_Outcome, ...]]:
    if not rows:
        raise NoTradeContextStabilityError(
            "context stability requires labeled outcomes"
        )
    ordered = tuple(
        sorted(
            rows,
            key=lambda item: (
                item.decision_timestamp_ms,
                item.forward_return,
            ),
        )
    )
    raw_index = int(Decimal(len(ordered)) * split_fraction)
    index = min(max(raw_index, 1), len(ordered) - 1)
    split_timestamp_ms = ordered[index - 1].decision_timestamp_ms
    discovery = tuple(
        item
        for item in ordered
        if item.decision_timestamp_ms <= split_timestamp_ms
    )
    validation = tuple(
        item
        for item in ordered
        if item.decision_timestamp_ms > split_timestamp_ms
    )
    if not discovery or not validation:
        raise NoTradeContextStabilityError(
            "chronological split must produce both discovery and validation rows"
        )
    return split_timestamp_ms, discovery, validation


def _direction_count(rows: tuple[_Outcome, ...], direction: str) -> int:
    return sum(item.direction == direction for item in rows)


def _analysis(
    rows: tuple[_Outcome, ...],
    *,
    horizon_ms: int,
    threshold_bps: int,
    split_fraction: Decimal,
    min_discovery_rows: int,
    min_validation_rows: int,
    min_discovery_direction_share: Decimal,
    min_validation_direction_share: Decimal,
    min_validation_lift: Decimal,
) -> ContextStabilityAnalysis:
    split_timestamp_ms, discovery_rows, validation_rows = _split_rows(
        rows,
        split_fraction=split_fraction,
    )
    discovery_material = tuple(
        item
        for item in discovery_rows
        if _material(item, threshold_bps=threshold_bps)
    )
    validation_material = tuple(
        item
        for item in validation_rows
        if _material(item, threshold_bps=threshold_bps)
    )

    candidates: list[ContextStabilityCandidate] = []
    for dimensions in combinations(DEFAULT_CONTEXT_DIMENSIONS, 2):
        discovery_groups: dict[tuple[str, str], list[_Outcome]] = {}
        validation_groups: dict[tuple[str, str], list[_Outcome]] = {}
        for item in discovery_material:
            for key in _context_keys(item, dimensions):
                discovery_groups.setdefault(key, []).append(item)
        for item in validation_material:
            for key in _context_keys(item, dimensions):
                validation_groups.setdefault(key, []).append(item)

        for values in sorted(discovery_groups):
            discovery_group = tuple(discovery_groups[values])
            if len(discovery_group) < min_discovery_rows:
                continue
            long_count = _direction_count(discovery_group, "long")
            short_count = _direction_count(discovery_group, "short")
            if long_count == short_count:
                continue
            dominant = "long" if long_count > short_count else "short"
            discovery_share = _ratio(
                max(long_count, short_count),
                len(discovery_group),
            )
            if discovery_share < min_discovery_direction_share:
                continue

            validation_group = tuple(
                validation_groups.get(values, ())
            )
            validation_share: Decimal | None = None
            baseline_share: Decimal | None = None
            lift: Decimal | None = None
            stable = False
            if validation_group:
                validation_share = _ratio(
                    _direction_count(validation_group, dominant),
                    len(validation_group),
                )
            if validation_material:
                baseline_share = _ratio(
                    _direction_count(validation_material, dominant),
                    len(validation_material),
                )
            if validation_share is not None and baseline_share is not None:
                lift = validation_share - baseline_share
                stable = (
                    len(validation_group) >= min_validation_rows
                    and validation_share >= min_validation_direction_share
                    and lift >= min_validation_lift
                )

            candidates.append(
                ContextStabilityCandidate(
                    horizon_ms=horizon_ms,
                    threshold_bps=threshold_bps,
                    dimensions=dimensions,
                    values=values,
                    dominant_direction=dominant,
                    discovery_material_outcomes=len(discovery_group),
                    discovery_direction_share=discovery_share,
                    validation_material_outcomes=len(validation_group),
                    validation_same_direction_share=validation_share,
                    validation_baseline_direction_share=baseline_share,
                    validation_lift_vs_baseline=lift,
                    stable_on_validation=stable,
                )
            )

    ordered_candidates = tuple(
        sorted(
            candidates,
            key=lambda item: (
                not item.stable_on_validation,
                -(
                    item.validation_lift_vs_baseline
                    if item.validation_lift_vs_baseline is not None
                    else Decimal("-1")
                ),
                -item.validation_material_outcomes,
                -item.discovery_material_outcomes,
                item.dimensions,
                item.values,
            ),
        )
    )
    return ContextStabilityAnalysis(
        horizon_ms=horizon_ms,
        threshold_bps=threshold_bps,
        split_timestamp_ms=split_timestamp_ms,
        labeled_outcomes=len(rows),
        discovery_material_outcomes=len(discovery_material),
        validation_material_outcomes=len(validation_material),
        discovered_candidate_count=len(ordered_candidates),
        validated_candidate_count=sum(
            item.stable_on_validation for item in ordered_candidates
        ),
        candidates=ordered_candidates,
    )


def build_no_trade_context_stability_report(
    forward_report: dict[str, object],
    *,
    split_fraction: Decimal = Decimal("0.70"),
    material_thresholds_bps: tuple[int, ...] = (
        DEFAULT_MATERIAL_THRESHOLDS_BPS
    ),
    min_discovery_rows: int = 40,
    min_validation_rows: int = 20,
    min_discovery_direction_share: Decimal = Decimal("0.60"),
    min_validation_direction_share: Decimal = Decimal("0.55"),
    min_validation_lift: Decimal = Decimal("0.05"),
) -> NoTradeContextStabilityReport:
    if not ZERO < split_fraction < ONE:
        raise ValueError("split_fraction must be between zero and one")
    if not material_thresholds_bps or any(
        value <= 0 for value in material_thresholds_bps
    ):
        raise ValueError("material thresholds must be positive")
    if len(set(material_thresholds_bps)) != len(material_thresholds_bps):
        raise ValueError("material thresholds must be unique")
    if min_discovery_rows <= 0 or min_validation_rows <= 0:
        raise ValueError("minimum sample sizes must be positive")
    for value, field in (
        (min_discovery_direction_share, "min_discovery_direction_share"),
        (min_validation_direction_share, "min_validation_direction_share"),
    ):
        if not Decimal("0.5") < value <= ONE:
            raise ValueError(f"{field} must be in (0.5, 1]")
    if not ZERO <= min_validation_lift <= Decimal("0.5"):
        raise ValueError("min_validation_lift must be in [0, 0.5]")

    if forward_report.get("diagnostic_only") is not True:
        raise NoTradeContextStabilityError(
            "source forward report must be diagnostic-only"
        )
    if forward_report.get("hypothetical_pnl") is not False:
        raise NoTradeContextStabilityError(
            "source forward report must not claim hypothetical PnL"
        )
    if forward_report.get("execution_authority") is not False:
        raise NoTradeContextStabilityError(
            "source forward report must have no execution authority"
        )

    outcomes = tuple(
        _parse_outcome(item)
        for item in _sequence(forward_report.get("outcomes"), "outcomes")
    )
    strategy_abstained = tuple(
        item
        for item in outcomes
        if item.decision_stage in ELIGIBLE_DECISION_STAGES
    )
    by_horizon: dict[int, list[_Outcome]] = {}
    for item in strategy_abstained:
        by_horizon.setdefault(item.horizon_ms, []).append(item)

    analyses: list[ContextStabilityAnalysis] = []
    for horizon_ms in sorted(by_horizon):
        rows = tuple(by_horizon[horizon_ms])
        if len(rows) < 2:
            continue
        for threshold_bps in sorted(material_thresholds_bps):
            analyses.append(
                _analysis(
                    rows,
                    horizon_ms=horizon_ms,
                    threshold_bps=threshold_bps,
                    split_fraction=split_fraction,
                    min_discovery_rows=min_discovery_rows,
                    min_validation_rows=min_validation_rows,
                    min_discovery_direction_share=(
                        min_discovery_direction_share
                    ),
                    min_validation_direction_share=(
                        min_validation_direction_share
                    ),
                    min_validation_lift=min_validation_lift,
                )
            )

    return NoTradeContextStabilityReport(
        source_decision_state_digest=_string(
            forward_report.get("decision_state_digest"),
            "decision_state_digest",
        ),
        source_feature_state_digest=_string(
            forward_report.get("feature_state_digest"),
            "feature_state_digest",
        ),
        split_fraction=split_fraction,
        min_discovery_rows=min_discovery_rows,
        min_validation_rows=min_validation_rows,
        min_discovery_direction_share=min_discovery_direction_share,
        min_validation_direction_share=min_validation_direction_share,
        min_validation_lift=min_validation_lift,
        material_thresholds_bps=tuple(sorted(material_thresholds_bps)),
        source_outcome_count=len(outcomes),
        strategy_abstained_outcomes=sum(
            item.decision_stage == "strategy_abstained" for item in outcomes
        ),
        eligibility_blocked_outcomes=sum(
            item.decision_stage == "eligibility_blocked" for item in outcomes
        ),
        other_outcomes=sum(
            item.decision_stage == "other" for item in outcomes
        ),
        eligible_decision_stages=ELIGIBLE_DECISION_STAGES,
        analyses=tuple(analyses),
    )
