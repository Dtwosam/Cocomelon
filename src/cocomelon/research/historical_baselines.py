from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from cocomelon.domain.features import TrendRegime
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    HistoricalTrainingRow,
)

ZERO = Decimal("0")


class HistoricalBaselineError(RuntimeError):
    pass


def _row_order(row: HistoricalTrainingRow) -> tuple[int, str, int, str]:
    return (
        row.anchor_end_ms,
        row.market.canonical,
        row.horizon_ms,
        row.training_row_id,
    )


@dataclass(frozen=True, slots=True)
class TemporalSplit:
    train: tuple[HistoricalTrainingRow, ...]
    validation: tuple[HistoricalTrainingRow, ...]
    test: tuple[HistoricalTrainingRow, ...]

    def __post_init__(self) -> None:
        for partition in (self.train, self.validation, self.test):
            if tuple(sorted(partition, key=_row_order)) != partition:
                raise ValueError("temporal split partitions must use canonical chronological order")

        train_anchors = {row.anchor_end_ms for row in self.train}
        validation_anchors = {row.anchor_end_ms for row in self.validation}
        test_anchors = {row.anchor_end_ms for row in self.test}
        if train_anchors & validation_anchors:
            raise ValueError("train and validation anchors must be disjoint")
        if train_anchors & test_anchors:
            raise ValueError("train and test anchors must be disjoint")
        if validation_anchors & test_anchors:
            raise ValueError("validation and test anchors must be disjoint")

        if self.train and self.validation:
            if max(train_anchors) >= min(validation_anchors):
                raise ValueError("train must precede validation")
        if self.validation and self.test:
            if max(validation_anchors) >= min(test_anchors):
                raise ValueError("validation must precede test")


def chronological_split(
    rows: Sequence[HistoricalTrainingRow],
    *,
    train_end_ms: int,
    validation_end_ms: int,
    embargo_ms: int = 0,
) -> TemporalSplit:
    if train_end_ms < 0:
        raise ValueError("train_end_ms must be non-negative")
    if validation_end_ms <= train_end_ms:
        raise ValueError("validation_end_ms must be after train_end_ms")
    if embargo_ms < 0:
        raise ValueError("embargo_ms must be non-negative")

    ordered = tuple(sorted(rows, key=_row_order))
    train = tuple(row for row in ordered if row.anchor_end_ms <= train_end_ms)
    validation = tuple(
        row
        for row in ordered
        if row.anchor_end_ms > train_end_ms + embargo_ms
        and row.anchor_end_ms <= validation_end_ms
    )
    test = tuple(
        row
        for row in ordered
        if row.anchor_end_ms > validation_end_ms + embargo_ms
    )
    return TemporalSplit(train=train, validation=validation, test=test)


def walk_forward_splits(
    rows: Sequence[HistoricalTrainingRow],
    *,
    min_train_anchors: int,
    validation_anchors: int,
    test_anchors: int,
    step_anchors: int,
    embargo_anchors: int = 0,
) -> tuple[TemporalSplit, ...]:
    for field, value in (
        ("min_train_anchors", min_train_anchors),
        ("validation_anchors", validation_anchors),
        ("test_anchors", test_anchors),
        ("step_anchors", step_anchors),
    ):
        if value <= 0:
            raise ValueError(f"{field} must be positive")
    if embargo_anchors < 0:
        raise ValueError("embargo_anchors must be non-negative")

    ordered = tuple(sorted(rows, key=_row_order))
    anchors = tuple(sorted({row.anchor_end_ms for row in ordered}))
    folds: list[TemporalSplit] = []
    train_count = min_train_anchors

    while True:
        validation_start = train_count + embargo_anchors
        validation_end = validation_start + validation_anchors
        test_start = validation_end + embargo_anchors
        test_end = test_start + test_anchors
        if test_end > len(anchors):
            break

        train_set = set(anchors[:train_count])
        validation_set = set(anchors[validation_start:validation_end])
        test_set = set(anchors[test_start:test_end])

        folds.append(
            TemporalSplit(
                train=tuple(row for row in ordered if row.anchor_end_ms in train_set),
                validation=tuple(
                    row for row in ordered if row.anchor_end_ms in validation_set
                ),
                test=tuple(row for row in ordered if row.anchor_end_ms in test_set),
            )
        )
        train_count += step_anchors

    return tuple(folds)


def _sign_bucket(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value > ZERO:
        return "positive"
    if value < ZERO:
        return "negative"
    return "flat"


@dataclass(frozen=True, slots=True, order=True)
class SharedStateKey:
    horizon_ms: int
    trend_regime: TrendRegime
    momentum_5m: str
    funding_sign: str

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        valid = {"positive", "negative", "flat", "missing"}
        if self.momentum_5m not in valid:
            raise ValueError("invalid momentum_5m bucket")
        if self.funding_sign not in valid:
            raise ValueError("invalid funding_sign bucket")


@dataclass(frozen=True, slots=True, order=True)
class CoinStateKey:
    market: str
    shared: SharedStateKey

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty")


@dataclass(frozen=True, slots=True)
class DirectionalStats:
    sample_count: int
    expected_long_return: Decimal
    expected_short_return: Decimal
    long_positive_rate: Decimal
    short_positive_rate: Decimal

    def __post_init__(self) -> None:
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        for field in (
            "expected_long_return",
            "expected_short_return",
            "long_positive_rate",
            "short_positive_rate",
        ):
            value = getattr(self, field)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{field} must be a finite Decimal")
        if not ZERO <= self.long_positive_rate <= 1:
            raise ValueError("long_positive_rate must be between 0 and 1")
        if not ZERO <= self.short_positive_rate <= 1:
            raise ValueError("short_positive_rate must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class DirectionalEstimate:
    sample_count: int
    expected_long_return: Decimal
    expected_short_return: Decimal
    long_positive_rate: Decimal
    short_positive_rate: Decimal
    source: str
    state_key: SharedStateKey

    def __post_init__(self) -> None:
        if self.source not in {"coin_state", "shared_state", "shared_horizon"}:
            raise ValueError("unsupported estimate source")
        DirectionalStats(
            sample_count=self.sample_count,
            expected_long_return=self.expected_long_return,
            expected_short_return=self.expected_short_return,
            long_positive_rate=self.long_positive_rate,
            short_positive_rate=self.short_positive_rate,
        )


def _shared_state(feature: HistoricalFeatureRow, horizon_ms: int) -> SharedStateKey:
    return SharedStateKey(
        horizon_ms=horizon_ms,
        trend_regime=feature.trend_regime,
        momentum_5m=_sign_bucket(feature.return_5m),
        funding_sign=_sign_bucket(feature.funding_rate),
    )


def _stats(rows: Sequence[HistoricalTrainingRow]) -> DirectionalStats:
    if not rows:
        raise HistoricalBaselineError("cannot calculate stats from empty rows")
    count = len(rows)
    denominator = Decimal(count)
    long_sum = sum((row.long_gross_return for row in rows), ZERO)
    short_sum = sum((row.short_gross_return for row in rows), ZERO)
    long_positive = sum(1 for row in rows if row.long_gross_return > ZERO)
    short_positive = sum(1 for row in rows if row.short_gross_return > ZERO)
    return DirectionalStats(
        sample_count=count,
        expected_long_return=long_sum / denominator,
        expected_short_return=short_sum / denominator,
        long_positive_rate=Decimal(long_positive) / denominator,
        short_positive_rate=Decimal(short_positive) / denominator,
    )


@dataclass(frozen=True, slots=True)
class ConditionalBaselineModel:
    min_state_samples: int
    min_coin_samples: int
    shared_states: Mapping[SharedStateKey, DirectionalStats]
    coin_states: Mapping[CoinStateKey, DirectionalStats]
    shared_horizons: Mapping[int, DirectionalStats]

    def __post_init__(self) -> None:
        if self.min_state_samples <= 0:
            raise ValueError("min_state_samples must be positive")
        if self.min_coin_samples <= 0:
            raise ValueError("min_coin_samples must be positive")
        if not self.shared_horizons:
            raise ValueError("shared_horizons must not be empty")

    def predict(
        self,
        feature: HistoricalFeatureRow,
        *,
        horizon_ms: int,
        allow_coin_calibration: bool = True,
    ) -> DirectionalEstimate:
        state = _shared_state(feature, horizon_ms)
        coin_key = CoinStateKey(market=feature.market.canonical, shared=state)
        coin_stats = self.coin_states.get(coin_key)
        if (
            allow_coin_calibration
            and coin_stats is not None
            and coin_stats.sample_count >= self.min_coin_samples
        ):
            return DirectionalEstimate(
                sample_count=coin_stats.sample_count,
                expected_long_return=coin_stats.expected_long_return,
                expected_short_return=coin_stats.expected_short_return,
                long_positive_rate=coin_stats.long_positive_rate,
                short_positive_rate=coin_stats.short_positive_rate,
                source="coin_state",
                state_key=state,
            )

        shared_stats = self.shared_states.get(state)
        if shared_stats is not None and shared_stats.sample_count >= self.min_state_samples:
            return DirectionalEstimate(
                sample_count=shared_stats.sample_count,
                expected_long_return=shared_stats.expected_long_return,
                expected_short_return=shared_stats.expected_short_return,
                long_positive_rate=shared_stats.long_positive_rate,
                short_positive_rate=shared_stats.short_positive_rate,
                source="shared_state",
                state_key=state,
            )

        horizon_stats = self.shared_horizons.get(horizon_ms)
        if horizon_stats is None:
            raise HistoricalBaselineError(
                f"no fitted baseline data for horizon {horizon_ms}"
            )
        return DirectionalEstimate(
            sample_count=horizon_stats.sample_count,
            expected_long_return=horizon_stats.expected_long_return,
            expected_short_return=horizon_stats.expected_short_return,
            long_positive_rate=horizon_stats.long_positive_rate,
            short_positive_rate=horizon_stats.short_positive_rate,
            source="shared_horizon",
            state_key=state,
        )


def fit_conditional_baseline(
    rows: Sequence[HistoricalTrainingRow],
    *,
    min_state_samples: int = 20,
    min_coin_samples: int = 50,
) -> ConditionalBaselineModel:
    if not rows:
        raise HistoricalBaselineError("rows must not be empty")
    if min_state_samples <= 0:
        raise ValueError("min_state_samples must be positive")
    if min_coin_samples <= 0:
        raise ValueError("min_coin_samples must be positive")

    shared_groups: dict[SharedStateKey, list[HistoricalTrainingRow]] = defaultdict(list)
    coin_groups: dict[CoinStateKey, list[HistoricalTrainingRow]] = defaultdict(list)
    horizon_groups: dict[int, list[HistoricalTrainingRow]] = defaultdict(list)

    for row in sorted(rows, key=_row_order):
        state = _shared_state(row.feature, row.horizon_ms)
        shared_groups[state].append(row)
        coin_groups[CoinStateKey(row.market.canonical, state)].append(row)
        horizon_groups[row.horizon_ms].append(row)

    return ConditionalBaselineModel(
        min_state_samples=min_state_samples,
        min_coin_samples=min_coin_samples,
        shared_states={key: _stats(value) for key, value in shared_groups.items()},
        coin_states={key: _stats(value) for key, value in coin_groups.items()},
        shared_horizons={key: _stats(value) for key, value in horizon_groups.items()},
    )



@dataclass(frozen=True, slots=True)
class ExecutionCostAssumptions:
    round_trip_fee_fraction: Decimal
    round_trip_slippage_fraction: Decimal
    funding_reserve_fraction_per_hour: Decimal

    def __post_init__(self) -> None:
        for field in (
            "round_trip_fee_fraction",
            "round_trip_slippage_fraction",
            "funding_reserve_fraction_per_hour",
        ):
            value = getattr(self, field)
            if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
                raise ValueError(f"{field} must be a non-negative finite Decimal")

    def total_cost_fraction(self, horizon_ms: int) -> Decimal:
        if horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        hours = Decimal(horizon_ms) / Decimal(3_600_000)
        return (
            self.round_trip_fee_fraction
            + self.round_trip_slippage_fraction
            + self.funding_reserve_fraction_per_hour * hours
        )


class DecisionAction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NO_TRADE = "no_trade"


@dataclass(frozen=True, slots=True)
class DirectionalDecision:
    action: DecisionAction
    expected_long_net_return: Decimal
    expected_short_net_return: Decimal
    cost_fraction: Decimal
    min_expected_net_edge: Decimal
    sample_count: int
    estimate_source: str

    def __post_init__(self) -> None:
        if self.sample_count <= 0:
            raise ValueError("sample_count must be positive")
        for field in (
            "expected_long_net_return",
            "expected_short_net_return",
            "cost_fraction",
            "min_expected_net_edge",
        ):
            value = getattr(self, field)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{field} must be a finite Decimal")
        if self.cost_fraction < ZERO:
            raise ValueError("cost_fraction must be non-negative")
        if self.min_expected_net_edge < ZERO:
            raise ValueError("min_expected_net_edge must be non-negative")
        if not self.estimate_source.strip():
            raise ValueError("estimate_source must not be empty")


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    min_expected_net_edge: Decimal
    min_sample_count: int

    def __post_init__(self) -> None:
        if (
            not self.min_expected_net_edge.is_finite()
            or self.min_expected_net_edge < ZERO
        ):
            raise ValueError("min_expected_net_edge must be a non-negative finite Decimal")
        if self.min_sample_count <= 0:
            raise ValueError("min_sample_count must be positive")

    def decide(
        self,
        estimate: DirectionalEstimate,
        *,
        costs: ExecutionCostAssumptions,
    ) -> DirectionalDecision:
        cost_fraction = costs.total_cost_fraction(estimate.state_key.horizon_ms)
        long_net = estimate.expected_long_return - cost_fraction
        short_net = estimate.expected_short_return - cost_fraction

        action = DecisionAction.NO_TRADE
        if estimate.sample_count >= self.min_sample_count:
            best_edge = max(long_net, short_net)
            if best_edge > self.min_expected_net_edge:
                if long_net > short_net:
                    action = DecisionAction.LONG
                elif short_net > long_net:
                    action = DecisionAction.SHORT

        return DirectionalDecision(
            action=action,
            expected_long_net_return=long_net,
            expected_short_net_return=short_net,
            cost_fraction=cost_fraction,
            min_expected_net_edge=self.min_expected_net_edge,
            sample_count=estimate.sample_count,
            estimate_source=estimate.source,
        )


@dataclass(frozen=True, slots=True)
class ThresholdCandidateResult:
    threshold: Decimal
    trade_count: int
    total_realized_net_return: Decimal
    mean_realized_net_return: Decimal | None

    def __post_init__(self) -> None:
        if not self.threshold.is_finite() or self.threshold < ZERO:
            raise ValueError("threshold must be a non-negative finite Decimal")
        if self.trade_count < 0:
            raise ValueError("trade_count must be non-negative")
        if not self.total_realized_net_return.is_finite():
            raise ValueError("total_realized_net_return must be finite")
        if self.mean_realized_net_return is not None:
            if not self.mean_realized_net_return.is_finite():
                raise ValueError("mean_realized_net_return must be finite")
            if self.trade_count == 0:
                raise ValueError("mean_realized_net_return requires trades")


@dataclass(frozen=True, slots=True)
class ThresholdCalibration:
    selected_threshold: Decimal
    candidates: tuple[ThresholdCandidateResult, ...]
    min_sample_count: int
    min_validation_trades: int

    def __post_init__(self) -> None:
        if self.selected_threshold not in {item.threshold for item in self.candidates}:
            raise ValueError("selected_threshold must come from candidates")
        if self.min_sample_count <= 0:
            raise ValueError("min_sample_count must be positive")
        if self.min_validation_trades <= 0:
            raise ValueError("min_validation_trades must be positive")


def _realized_net_return(
    row: HistoricalTrainingRow,
    decision: DirectionalDecision,
) -> Decimal | None:
    if decision.action is DecisionAction.NO_TRADE:
        return None
    if decision.action is DecisionAction.LONG:
        return row.long_gross_return - decision.cost_fraction
    return row.short_gross_return - decision.cost_fraction


def calibrate_no_trade_threshold(
    model: ConditionalBaselineModel,
    validation_rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    candidate_thresholds: Sequence[Decimal],
    min_sample_count: int,
    min_validation_trades: int,
    allow_coin_calibration: bool = True,
) -> ThresholdCalibration:
    if not validation_rows:
        raise HistoricalBaselineError("validation_rows must not be empty")
    if min_sample_count <= 0:
        raise ValueError("min_sample_count must be positive")
    if min_validation_trades <= 0:
        raise ValueError("min_validation_trades must be positive")

    thresholds = tuple(sorted(set(candidate_thresholds)))
    if not thresholds:
        raise ValueError("candidate_thresholds must not be empty")
    if any(not value.is_finite() or value < ZERO for value in thresholds):
        raise ValueError("candidate_thresholds must be non-negative finite Decimals")

    ordered = tuple(sorted(validation_rows, key=_row_order))
    results: list[ThresholdCandidateResult] = []
    for threshold in thresholds:
        policy = DecisionPolicy(
            min_expected_net_edge=threshold,
            min_sample_count=min_sample_count,
        )
        realized: list[Decimal] = []
        for row in ordered:
            estimate = model.predict(
                row.feature,
                horizon_ms=row.horizon_ms,
                allow_coin_calibration=allow_coin_calibration,
            )
            decision = policy.decide(estimate, costs=costs)
            net_return = _realized_net_return(row, decision)
            if net_return is not None:
                realized.append(net_return)

        total = sum(realized, ZERO)
        mean = None if not realized else total / Decimal(len(realized))
        results.append(
            ThresholdCandidateResult(
                threshold=threshold,
                trade_count=len(realized),
                total_realized_net_return=total,
                mean_realized_net_return=mean,
            )
        )

    eligible = tuple(
        result
        for result in results
        if result.trade_count >= min_validation_trades
        and result.mean_realized_net_return is not None
    )
    if not eligible:
        raise HistoricalBaselineError(
            "no threshold met the minimum validation trade count"
        )

    selected = max(
        eligible,
        key=lambda item: (
            item.mean_realized_net_return,
            item.total_realized_net_return,
            item.trade_count,
            -item.threshold,
        ),
    )
    return ThresholdCalibration(
        selected_threshold=selected.threshold,
        candidates=tuple(results),
        min_sample_count=min_sample_count,
        min_validation_trades=min_validation_trades,
    )
