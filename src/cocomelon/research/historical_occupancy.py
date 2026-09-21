from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.historical_baselines import (
    DecisionAction,
    DirectionalDecision,
    ExecutionCostAssumptions,
    HistoricalDecisionPolicy,
    HistoricalDirectionalModel,
    PredictedTrainingRow,
    predict_training_rows,
)
from cocomelon.research.historical_features import HistoricalTrainingRow

ZERO = Decimal("0")


class HistoricalOccupancyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalExecutedTrade:
    row: HistoricalTrainingRow
    decision: DirectionalDecision
    expected_net_edge: Decimal
    realized_net_return: Decimal

    def __post_init__(self) -> None:
        if self.decision.action is DecisionAction.NO_TRADE:
            raise ValueError("executed trades cannot use NO_TRADE")
        if not self.expected_net_edge.is_finite():
            raise ValueError("expected_net_edge must be finite")
        if not self.realized_net_return.is_finite():
            raise ValueError("realized_net_return must be finite")

    @property
    def market(self) -> str:
        return self.row.market.canonical

    @property
    def anchor_end_ms(self) -> int:
        return self.row.anchor_end_ms

    @property
    def target_end_ms(self) -> int:
        return self.row.outcome.target_end_ms

    @property
    def horizon_ms(self) -> int:
        return self.row.horizon_ms


@dataclass(frozen=True, slots=True)
class HistoricalOccupancyTradeSummary:
    trade_count: int
    long_count: int
    short_count: int
    total_realized_net_return: Decimal
    mean_realized_net_return: Decimal | None

    def __post_init__(self) -> None:
        for field in ("trade_count", "long_count", "short_count"):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.long_count + self.short_count != self.trade_count:
            raise ValueError("long_count + short_count must equal trade_count")
        if not self.total_realized_net_return.is_finite():
            raise ValueError("total_realized_net_return must be finite")
        if self.mean_realized_net_return is None:
            if self.trade_count != 0:
                raise ValueError("mean return is required when trades exist")
        elif not self.mean_realized_net_return.is_finite():
            raise ValueError("mean_realized_net_return must be finite")


@dataclass(frozen=True, slots=True)
class HistoricalOccupancyBreakdownEntry:
    dimension: str
    value: str
    summary: HistoricalOccupancyTradeSummary

    def __post_init__(self) -> None:
        if self.dimension not in {
            "market",
            "horizon_ms",
            "action",
            "trend_regime",
            "estimate_source",
        }:
            raise ValueError("unsupported occupancy breakdown dimension")
        if not self.value.strip():
            raise ValueError("breakdown value must not be empty")


@dataclass(frozen=True, slots=True)
class HistoricalOccupancyEvaluation:
    prediction_row_count: int
    opportunity_count: int
    trade_count: int
    long_count: int
    short_count: int
    no_trade_count: int
    occupied_skip_count: int
    total_realized_net_return: Decimal
    mean_realized_net_return: Decimal | None
    trades: tuple[HistoricalExecutedTrade, ...]

    def __post_init__(self) -> None:
        for field in (
            "prediction_row_count",
            "opportunity_count",
            "trade_count",
            "long_count",
            "short_count",
            "no_trade_count",
            "occupied_skip_count",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.long_count + self.short_count != self.trade_count:
            raise ValueError("long_count + short_count must equal trade_count")
        if (
            self.trade_count + self.no_trade_count + self.occupied_skip_count
            != self.opportunity_count
        ):
            raise ValueError(
                "trade/no_trade/occupied_skip counts must equal opportunities"
            )
        if len(self.trades) != self.trade_count:
            raise ValueError("trades length must equal trade_count")
        if not self.total_realized_net_return.is_finite():
            raise ValueError("total_realized_net_return must be finite")
        if self.mean_realized_net_return is None:
            if self.trade_count != 0:
                raise ValueError("mean return is required when trades exist")
        elif not self.mean_realized_net_return.is_finite():
            raise ValueError("mean_realized_net_return must be finite")


def _decision_edge(decision: DirectionalDecision) -> Decimal:
    if decision.action is DecisionAction.LONG:
        return decision.expected_long_net_return
    if decision.action is DecisionAction.SHORT:
        return decision.expected_short_net_return
    raise ValueError("NO_TRADE has no executable edge")


def _realized_net_return(
    row: HistoricalTrainingRow,
    decision: DirectionalDecision,
) -> Decimal:
    if decision.action is DecisionAction.LONG:
        return row.long_gross_return - decision.cost_fraction
    if decision.action is DecisionAction.SHORT:
        return row.short_gross_return - decision.cost_fraction
    raise ValueError("NO_TRADE has no realized trade return")


def _validate_predictions(
    predicted_rows: Sequence[PredictedTrainingRow],
) -> tuple[PredictedTrainingRow, ...]:
    ordered = tuple(
        sorted(
            predicted_rows,
            key=lambda item: (
                item.row.anchor_end_ms,
                item.row.market.canonical,
                item.row.horizon_ms,
                item.row.training_row_id,
            ),
        )
    )
    seen: set[tuple[str, int, int]] = set()
    for item in ordered:
        key = (
            item.row.market.canonical,
            item.row.anchor_end_ms,
            item.row.horizon_ms,
        )
        if key in seen:
            raise HistoricalOccupancyError("DUPLICATE_MARKET_ANCHOR_HORIZON")
        seen.add(key)
    return ordered


def evaluate_predicted_occupancy_policy(
    predicted_rows: Sequence[PredictedTrainingRow],
    *,
    policy: HistoricalDecisionPolicy,
    costs: ExecutionCostAssumptions,
) -> HistoricalOccupancyEvaluation:
    ordered = _validate_predictions(predicted_rows)
    grouped: dict[tuple[int, str], list[PredictedTrainingRow]] = defaultdict(list)
    for item in ordered:
        grouped[(item.row.anchor_end_ms, item.row.market.canonical)].append(item)

    occupied_until_by_market: dict[str, int] = {}
    trades: list[HistoricalExecutedTrade] = []
    no_trade_count = 0
    occupied_skip_count = 0

    for (anchor_end_ms, market), group in sorted(grouped.items()):
        occupied_until = occupied_until_by_market.get(market)
        if occupied_until is not None and anchor_end_ms < occupied_until:
            occupied_skip_count += 1
            continue

        candidates: list[
            tuple[Decimal, int, str, PredictedTrainingRow, DirectionalDecision]
        ] = []
        for item in group:
            decision = policy.decide(item.estimate, costs=costs)
            if decision.action is DecisionAction.NO_TRADE:
                continue
            candidates.append(
                (
                    _decision_edge(decision),
                    item.row.horizon_ms,
                    item.row.training_row_id,
                    item,
                    decision,
                )
            )

        if not candidates:
            no_trade_count += 1
            continue

        _edge, _horizon, _row_id, selected, decision = sorted(
            candidates,
            key=lambda item: (-item[0], item[1], item[2]),
        )[0]
        realized = _realized_net_return(selected.row, decision)
        trades.append(
            HistoricalExecutedTrade(
                row=selected.row,
                decision=decision,
                expected_net_edge=_decision_edge(decision),
                realized_net_return=realized,
            )
        )
        occupied_until_by_market[market] = selected.row.outcome.target_end_ms

    realized_returns = tuple(item.realized_net_return for item in trades)
    total = sum(realized_returns, ZERO)
    mean = None if not realized_returns else total / Decimal(len(realized_returns))
    long_count = sum(
        1 for item in trades if item.decision.action is DecisionAction.LONG
    )
    short_count = sum(
        1 for item in trades if item.decision.action is DecisionAction.SHORT
    )

    return HistoricalOccupancyEvaluation(
        prediction_row_count=len(ordered),
        opportunity_count=len(grouped),
        trade_count=len(trades),
        long_count=long_count,
        short_count=short_count,
        no_trade_count=no_trade_count,
        occupied_skip_count=occupied_skip_count,
        total_realized_net_return=total,
        mean_realized_net_return=mean,
        trades=tuple(trades),
    )


def evaluate_occupancy_policy(
    model: HistoricalDirectionalModel,
    rows: Sequence[HistoricalTrainingRow],
    *,
    policy: HistoricalDecisionPolicy,
    costs: ExecutionCostAssumptions,
    allow_coin_calibration: bool,
) -> HistoricalOccupancyEvaluation:
    return evaluate_predicted_occupancy_policy(
        predict_training_rows(
            model,
            rows,
            allow_coin_calibration=allow_coin_calibration,
        ),
        policy=policy,
        costs=costs,
    )


def summarize_occupancy_trades(
    trades: Sequence[HistoricalExecutedTrade],
) -> HistoricalOccupancyTradeSummary:
    realized = tuple(item.realized_net_return for item in trades)
    total = sum(realized, ZERO)
    mean = None if not realized else total / Decimal(len(realized))
    long_count = sum(
        1 for item in trades if item.decision.action is DecisionAction.LONG
    )
    short_count = sum(
        1 for item in trades if item.decision.action is DecisionAction.SHORT
    )
    return HistoricalOccupancyTradeSummary(
        trade_count=len(trades),
        long_count=long_count,
        short_count=short_count,
        total_realized_net_return=total,
        mean_realized_net_return=mean,
    )


def occupancy_trade_breakdowns(
    evaluation: HistoricalOccupancyEvaluation,
) -> tuple[HistoricalOccupancyBreakdownEntry, ...]:
    dimensions = (
        (
            "market",
            lambda item: item.market,
        ),
        (
            "horizon_ms",
            lambda item: str(item.horizon_ms),
        ),
        (
            "action",
            lambda item: item.decision.action.value,
        ),
        (
            "trend_regime",
            lambda item: item.row.feature.trend_regime.value,
        ),
        (
            "estimate_source",
            lambda item: item.decision.estimate_source,
        ),
    )
    entries: list[HistoricalOccupancyBreakdownEntry] = []
    for dimension, key_fn in dimensions:
        grouped: dict[str, list[HistoricalExecutedTrade]] = defaultdict(list)
        for trade in evaluation.trades:
            grouped[key_fn(trade)].append(trade)
        for value in sorted(grouped):
            entries.append(
                HistoricalOccupancyBreakdownEntry(
                    dimension=dimension,
                    value=value,
                    summary=summarize_occupancy_trades(grouped[value]),
                )
            )
    return tuple(entries)
