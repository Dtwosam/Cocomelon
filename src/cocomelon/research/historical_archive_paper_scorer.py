from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_archive_model_artifact import (
    HistoricalArchiveCandidateModelArtifact,
    predict_archive_candidate_model,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.historical_features import HistoricalFeatureRow

ZERO = Decimal("0")
STATE_SCHEMA_VERSION = 1
SIGNAL_SCHEMA_VERSION = 1


class HistoricalArchivePaperScorerError(RuntimeError):
    pass


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise HistoricalArchivePaperScorerError(f"{field} must be a sequence")
    return tuple(value)


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchivePaperScorerError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchivePaperScorerError(f"{field} must be an integer")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchivePaperScorerError(
            f"{field} must be a non-empty string"
        )
    return value


def _horizon_payload(
    artifact: HistoricalArchiveCandidateModelArtifact,
    horizon_ms: int,
) -> dict[str, object]:
    for raw in _sequence(
        artifact.model_payload.get("horizons"),
        "model horizons",
    ):
        item = _mapping(raw, "model horizon")
        if _integer(item.get("horizon_ms"), "model horizon_ms") == horizon_ms:
            return item
    raise HistoricalArchivePaperScorerError("MODEL_HORIZON_MISSING")


def _sample_count(
    artifact: HistoricalArchiveCandidateModelArtifact,
    horizon_ms: int,
) -> int:
    value = _integer(
        _horizon_payload(artifact, horizon_ms).get("sample_count"),
        "model sample_count",
    )
    if value <= 0:
        raise HistoricalArchivePaperScorerError(
            "MODEL_SAMPLE_COUNT_NOT_POSITIVE"
        )
    return value


def _estimate_source(
    artifact: HistoricalArchiveCandidateModelArtifact,
    feature: HistoricalFeatureRow,
    horizon_ms: int,
) -> str:
    payload = _horizon_payload(artifact, horizon_ms)
    market_names = tuple(
        _string(value, "model market")
        for value in _sequence(payload.get("market_names"), "model markets")
    )
    use_market = (
        artifact.allow_coin_calibration
        and feature.market.canonical in market_names
    )
    family = "tree" if artifact.model_family == "stable_tree" else "ridge"
    return f"{'market' if use_market else 'shared'}_{family}"


def _cost_fraction(
    spec: HistoricalArchiveCleanValidationSpec,
    horizon_ms: int,
) -> Decimal:
    fees = Decimal(spec.costs["round_trip_fee_fraction"])
    slippage = Decimal(spec.costs["round_trip_slippage_fraction"])
    funding = Decimal(spec.costs["funding_reserve_fraction_per_hour"])
    hours = Decimal(horizon_ms) / Decimal(3_600_000)
    value = fees + slippage + funding * hours
    if not value.is_finite() or value < ZERO:
        raise HistoricalArchivePaperScorerError("COST_FRACTION_INVALID")
    return value


def _threshold(
    spec: HistoricalArchiveCleanValidationSpec,
    horizon_ms: int,
) -> Decimal | None:
    for candidate_horizon, threshold in spec.horizon_thresholds:
        if candidate_horizon == horizon_ms:
            return threshold
    raise HistoricalArchivePaperScorerError("SPEC_HORIZON_MISSING")


def _validate_lineage(
    artifact: HistoricalArchiveCandidateModelArtifact,
    spec: HistoricalArchiveCleanValidationSpec,
) -> None:
    if (
        spec.model_artifact_id != artifact.artifact_id
        or spec.model_payload_sha256 != artifact.model_payload_sha256
        or spec.candidate_id != artifact.candidate_id
        or spec.training_plan_id != artifact.training_plan_id
        or spec.calibration_id != artifact.calibration_id
        or spec.model_family != artifact.model_family
        or spec.calibration_variant != artifact.calibration_variant
        or spec.model_format != artifact.model_format
        or spec.horizon_thresholds != artifact.selected_horizon_thresholds
        or spec.allow_coin_calibration != artifact.allow_coin_calibration
        or spec.min_sample_count != artifact.min_sample_count
        or spec.execution_policy != artifact.execution_policy
        or spec.max_concurrent_positions != artifact.max_concurrent_positions
        or spec.costs != artifact.costs
    ):
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_ARTIFACT_SPEC_MISMATCH"
        )
    if not spec.paper_only or spec.execution_ready:
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_SPEC_NOT_PAPER_ONLY"
        )


def _validate_feature(
    feature: HistoricalFeatureRow,
    spec: HistoricalArchiveCleanValidationSpec,
) -> None:
    if feature.market.canonical not in spec.markets:
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_MARKET_NOT_IN_SPEC"
        )
    if (
        feature.anchor_end_ms < spec.first_expected_anchor_ms
        or feature.anchor_end_ms >= spec.validation_end_ms
    ):
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_ANCHOR_OUTSIDE_VALIDATION_WINDOW"
        )
    if (
        feature.anchor_end_ms % spec.anchor_interval_ms
        != spec.anchor_end_offset_ms
    ):
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_ANCHOR_NOT_ALIGNED"
        )


@dataclass(frozen=True, slots=True)
class ArchivePaperSignal:
    candidate_id: str
    validation_spec_id: str
    model_artifact_id: str
    market: str
    anchor_end_ms: int
    horizon_ms: int
    target_end_ms: int
    direction: Direction
    expected_long_gross_return: Decimal
    expected_short_gross_return: Decimal
    expected_long_net_return: Decimal
    expected_short_net_return: Decimal
    expected_net_edge: Decimal
    cost_fraction: Decimal
    threshold: Decimal | None
    sample_count: int
    estimate_source: str
    reason_codes: tuple[str, ...]
    paper_only: bool = True
    schema_version: int = SIGNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        for field in ("validation_spec_id", "model_artifact_id"):
            value = getattr(self, field)
            if len(value) != 64:
                raise ValueError(f"{field} must be SHA-256")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.anchor_end_ms < 0 or self.horizon_ms <= 0:
            raise ValueError("invalid signal timing")
        if self.target_end_ms != self.anchor_end_ms + self.horizon_ms:
            raise ValueError("target_end_ms must match horizon")
        for field in (
            "expected_long_gross_return",
            "expected_short_gross_return",
            "expected_long_net_return",
            "expected_short_net_return",
            "expected_net_edge",
            "cost_fraction",
        ):
            value = getattr(self, field)
            if not value.is_finite():
                raise ValueError(f"{field} must be finite")
        if self.expected_short_gross_return != -self.expected_long_gross_return:
            raise ValueError("gross directional predictions must be symmetric")
        if self.cost_fraction < ZERO:
            raise ValueError("cost_fraction must be non-negative")
        if self.threshold is not None and (
            not self.threshold.is_finite() or self.threshold < ZERO
        ):
            raise ValueError("threshold must be non-negative finite")
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        if not self.estimate_source.strip():
            raise ValueError("estimate_source must not be empty")
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        expected_edge = max(
            self.expected_long_net_return,
            self.expected_short_net_return,
        )
        if self.expected_net_edge != expected_edge:
            raise ValueError("expected_net_edge must be best directional edge")
        if not self.paper_only:
            raise ValueError("archive signal must remain paper-only")
        if self.schema_version != SIGNAL_SCHEMA_VERSION:
            raise ValueError("unsupported archive signal schema")

    @property
    def is_trade(self) -> bool:
        return self.direction in {Direction.LONG, Direction.SHORT}


@dataclass(frozen=True, slots=True)
class ArchivePaperPosition:
    market: str
    opened_at_ms: int
    hold_until_ms: int
    horizon_ms: int
    direction: Direction
    expected_net_edge: Decimal

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.opened_at_ms < 0 or self.hold_until_ms <= self.opened_at_ms:
            raise ValueError("invalid position timing")
        if self.horizon_ms != self.hold_until_ms - self.opened_at_ms:
            raise ValueError("position horizon must match timing")
        if self.direction not in {Direction.LONG, Direction.SHORT}:
            raise ValueError("paper position must be directional")
        if not self.expected_net_edge.is_finite():
            raise ValueError("expected_net_edge must be finite")


@dataclass(frozen=True, slots=True)
class ArchivePaperState:
    positions: tuple[ArchivePaperPosition, ...] = ()
    schema_version: int = STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        markets = tuple(item.market for item in self.positions)
        if markets != tuple(sorted(set(markets))):
            raise ValueError("paper positions must be sorted unique by market")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported paper state schema")

    def active_at(self, anchor_end_ms: int) -> ArchivePaperState:
        return ArchivePaperState(
            positions=tuple(
                item
                for item in self.positions
                if anchor_end_ms < item.hold_until_ms
            )
        )


@dataclass(frozen=True, slots=True)
class ArchivePaperAnchorResult:
    anchor_end_ms: int
    raw_signals: tuple[ArchivePaperSignal, ...]
    accepted_signals: tuple[ArchivePaperSignal, ...]
    no_trade_markets: tuple[str, ...]
    occupied_skip_markets: tuple[str, ...]
    capacity_skip_markets: tuple[str, ...]
    next_state: ArchivePaperState
    paper_only: bool = True

    def __post_init__(self) -> None:
        if self.anchor_end_ms < 0:
            raise ValueError("anchor_end_ms must be non-negative")
        if any(item.anchor_end_ms != self.anchor_end_ms for item in self.raw_signals):
            raise ValueError("raw signal anchor mismatch")
        raw_keys = {
            (item.market, item.horizon_ms)
            for item in self.raw_signals
        }
        accepted_keys = {
            (item.market, item.horizon_ms)
            for item in self.accepted_signals
        }
        if not accepted_keys.issubset(raw_keys):
            raise ValueError("accepted signals must come from raw signals")
        for field in (
            "no_trade_markets",
            "occupied_skip_markets",
            "capacity_skip_markets",
        ):
            values = getattr(self, field)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"{field} must be sorted unique")
        if not self.paper_only:
            raise ValueError("anchor result must remain paper-only")


def score_archive_candidate_feature(
    artifact: HistoricalArchiveCandidateModelArtifact,
    spec: HistoricalArchiveCleanValidationSpec,
    feature: HistoricalFeatureRow,
    *,
    horizon_ms: int,
) -> ArchivePaperSignal:
    _validate_lineage(artifact, spec)
    _validate_feature(feature, spec)
    threshold = _threshold(spec, horizon_ms)
    gross = predict_archive_candidate_model(
        artifact,
        feature,
        horizon_ms=horizon_ms,
    )
    sample_count = _sample_count(artifact, horizon_ms)
    cost = _cost_fraction(spec, horizon_ms)
    long_net = gross - cost
    short_net = -gross - cost
    edge = max(long_net, short_net)
    direction = Direction.NO_TRADE
    reasons: list[str] = []

    if threshold is None:
        reasons.append("horizon_abstained")
    elif sample_count < spec.min_sample_count:
        reasons.append("insufficient_model_samples")
    elif edge <= threshold:
        reasons.append("edge_not_above_threshold")
    elif long_net > short_net:
        direction = Direction.LONG
        reasons.append("long_edge_selected")
    elif short_net > long_net:
        direction = Direction.SHORT
        reasons.append("short_edge_selected")
    else:
        reasons.append("direction_tie")

    return ArchivePaperSignal(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        model_artifact_id=artifact.artifact_id,
        market=feature.market.canonical,
        anchor_end_ms=feature.anchor_end_ms,
        horizon_ms=horizon_ms,
        target_end_ms=feature.anchor_end_ms + horizon_ms,
        direction=direction,
        expected_long_gross_return=gross,
        expected_short_gross_return=-gross,
        expected_long_net_return=long_net,
        expected_short_net_return=short_net,
        expected_net_edge=edge,
        cost_fraction=cost,
        threshold=threshold,
        sample_count=sample_count,
        estimate_source=_estimate_source(artifact, feature, horizon_ms),
        reason_codes=tuple(reasons),
    )


def _best_market_signal(
    signals: tuple[ArchivePaperSignal, ...],
) -> ArchivePaperSignal | None:
    executable = tuple(item for item in signals if item.is_trade)
    if not executable:
        return None
    return sorted(
        executable,
        key=lambda item: (
            -item.expected_net_edge,
            item.horizon_ms,
            item.market,
        ),
    )[0]


def score_archive_candidate_anchor(
    artifact: HistoricalArchiveCandidateModelArtifact,
    spec: HistoricalArchiveCleanValidationSpec,
    features: tuple[HistoricalFeatureRow, ...],
    *,
    state: ArchivePaperState = ArchivePaperState(),
) -> ArchivePaperAnchorResult:
    _validate_lineage(artifact, spec)
    if not features:
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_FEATURES_EMPTY"
        )
    anchors = {item.anchor_end_ms for item in features}
    if len(anchors) != 1:
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_MIXED_ANCHORS"
        )
    markets = tuple(item.market.canonical for item in features)
    if markets != tuple(sorted(set(markets))):
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_FEATURE_MARKETS_NOT_SORTED_UNIQUE"
        )
    anchor_end_ms = features[0].anchor_end_ms
    active_state = state.active_at(anchor_end_ms)

    raw_signals = tuple(
        score_archive_candidate_feature(
            artifact,
            spec,
            feature,
            horizon_ms=horizon_ms,
        )
        for feature in features
        for horizon_ms in spec.active_horizons
    )

    if spec.execution_policy == "independent_horizon":
        accepted = tuple(item for item in raw_signals if item.is_trade)
        no_trade_markets = tuple(
            sorted(
                {
                    feature.market.canonical
                    for feature in features
                    if not any(
                        item.market == feature.market.canonical
                        and item.is_trade
                        for item in raw_signals
                    )
                }
            )
        )
        return ArchivePaperAnchorResult(
            anchor_end_ms=anchor_end_ms,
            raw_signals=raw_signals,
            accepted_signals=accepted,
            no_trade_markets=no_trade_markets,
            occupied_skip_markets=(),
            capacity_skip_markets=(),
            next_state=active_state,
        )

    occupied = {item.market for item in active_state.positions}
    by_market: dict[str, tuple[ArchivePaperSignal, ...]] = {
        market: tuple(item for item in raw_signals if item.market == market)
        for market in markets
    }
    selected_by_market: dict[str, ArchivePaperSignal] = {}
    no_trade: list[str] = []
    occupied_skips: list[str] = []
    for market in markets:
        if market in occupied:
            occupied_skips.append(market)
            continue
        selected = _best_market_signal(by_market[market])
        if selected is None:
            no_trade.append(market)
        else:
            selected_by_market[market] = selected

    if spec.execution_policy == "single_position_occupancy":
        accepted = tuple(
            selected_by_market[market]
            for market in sorted(selected_by_market)
        )
        capacity_skips: tuple[str, ...] = ()
    elif spec.execution_policy == "portfolio_capacity":
        capacity = spec.max_concurrent_positions
        if capacity is None or capacity <= 0:
            raise HistoricalArchivePaperScorerError(
                "PAPER_SCORER_CAPACITY_INVALID"
            )
        available = capacity - len(active_state.positions)
        if available < 0:
            raise HistoricalArchivePaperScorerError(
                "PAPER_SCORER_ACTIVE_CAPACITY_EXCEEDED"
            )
        ranked = tuple(
            sorted(
                selected_by_market.values(),
                key=lambda item: (
                    -item.expected_net_edge,
                    item.horizon_ms,
                    item.market,
                ),
            )
        )
        accepted = ranked[:available]
        capacity_skips = tuple(
            sorted(item.market for item in ranked[available:])
        )
    else:
        raise HistoricalArchivePaperScorerError(
            "PAPER_SCORER_EXECUTION_POLICY_UNSUPPORTED"
        )

    new_positions = tuple(
        ArchivePaperPosition(
            market=item.market,
            opened_at_ms=item.anchor_end_ms,
            hold_until_ms=item.target_end_ms,
            horizon_ms=item.horizon_ms,
            direction=item.direction,
            expected_net_edge=item.expected_net_edge,
        )
        for item in accepted
    )
    next_positions = tuple(
        sorted(
            (*active_state.positions, *new_positions),
            key=lambda item: item.market,
        )
    )
    return ArchivePaperAnchorResult(
        anchor_end_ms=anchor_end_ms,
        raw_signals=raw_signals,
        accepted_signals=accepted,
        no_trade_markets=tuple(sorted(no_trade)),
        occupied_skip_markets=tuple(sorted(occupied_skips)),
        capacity_skip_markets=capacity_skips,
        next_state=ArchivePaperState(positions=next_positions),
    )
