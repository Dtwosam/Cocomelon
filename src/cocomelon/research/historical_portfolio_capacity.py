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
from cocomelon.research.historical_occupancy import (
    HistoricalExecutedTrade,
    HistoricalOccupancyBreakdownEntry,
    HistoricalOccupancyTradeSummary,
    summarize_occupancy_trades,
)

ZERO = Decimal("0")


class HistoricalPortfolioCapacityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HistoricalPortfolioCapacityEvaluation:
    prediction_row_count: int
    opportunity_count: int
    trade_count: int
    long_count: int
    short_count: int
    no_trade_count: int
    occupied_skip_count: int
    capacity_skip_count: int
    max_concurrent_positions: int
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
            "capacity_skip_count",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.max_concurrent_positions <= 0:
            raise ValueError("max_concurrent_positions must be positive")
        if self.long_count + self.short_count != self.trade_count:
            raise ValueError("long_count + short_count must equal trade_count")
        if (
            self.trade_count
            + self.no_trade_count
            + self.occupied_skip_count
            + self.capacity_skip_count
            != self.opportunity_count
        ):
            raise ValueError(
                "trade/no_trade/occupied_skip/capacity_skip counts "
                "must equal opportunities"
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


def _validated_predictions(
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
            raise HistoricalPortfolioCapacityError(
                "DUPLICATE_MARKET_ANCHOR_HORIZON"
            )
        seen.add(key)
    return ordered


def evaluate_predicted_portfolio_capacity_policy(
    predicted_rows: Sequence[PredictedTrainingRow],
    *,
    policy: HistoricalDecisionPolicy,
    costs: ExecutionCostAssumptions,
    max_concurrent_positions: int,
) -> HistoricalPortfolioCapacityEvaluation:
    if max_concurrent_positions <= 0:
        raise ValueError("max_concurrent_positions must be positive")

    ordered = _validated_predictions(predicted_rows)
    by_anchor: dict[int, dict[str, list[PredictedTrainingRow]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in ordered:
        by_anchor[item.row.anchor_end_ms][item.row.market.canonical].append(item)

    occupied_until_by_market: dict[str, int] = {}
    trades: list[HistoricalExecutedTrade] = []
    no_trade_count = 0
    occupied_skip_count = 0
    capacity_skip_count = 0

    for anchor_end_ms in sorted(by_anchor):
        occupied_until_by_market = {
            market: target_end_ms
            for market, target_end_ms in occupied_until_by_market.items()
            if anchor_end_ms < target_end_ms
        }
        active_market_count = len(occupied_until_by_market)
        if active_market_count > max_concurrent_positions:
            raise HistoricalPortfolioCapacityError("ACTIVE_POSITION_CAPACITY_EXCEEDED")

        executable: list[
            tuple[
                Decimal,
                int,
                str,
                str,
                PredictedTrainingRow,
                DirectionalDecision,
            ]
        ] = []
        markets_at_anchor = by_anchor[anchor_end_ms]
        for market in sorted(markets_at_anchor):
            group = markets_at_anchor[market]
            if market in occupied_until_by_market:
                occupied_skip_count += 1
                continue

            candidates: list[
                tuple[
                    Decimal,
                    int,
                    str,
                    PredictedTrainingRow,
                    DirectionalDecision,
                ]
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

            edge, horizon_ms, row_id, selected, decision = sorted(
                candidates,
                key=lambda item: (-item[0], item[1], item[2]),
            )[0]
            executable.append(
                (
                    edge,
                    horizon_ms,
                    market,
                    row_id,
                    selected,
                    decision,
                )
            )

        available_slots = max_concurrent_positions - active_market_count
        ranked = tuple(
            sorted(
                executable,
                key=lambda item: (-item[0], item[1], item[2], item[3]),
            )
        )
        selected_candidates = ranked[:available_slots]
        capacity_skip_count += len(ranked) - len(selected_candidates)

        for edge, _horizon, market, _row_id, selected, decision in selected_candidates:
            realized = _realized_net_return(selected.row, decision)
            trades.append(
                HistoricalExecutedTrade(
                    row=selected.row,
                    decision=decision,
                    expected_net_edge=edge,
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
    opportunities = {
        (item.row.anchor_end_ms, item.row.market.canonical)
        for item in ordered
    }

    return HistoricalPortfolioCapacityEvaluation(
        prediction_row_count=len(ordered),
        opportunity_count=len(opportunities),
        trade_count=len(trades),
        long_count=long_count,
        short_count=short_count,
        no_trade_count=no_trade_count,
        occupied_skip_count=occupied_skip_count,
        capacity_skip_count=capacity_skip_count,
        max_concurrent_positions=max_concurrent_positions,
        total_realized_net_return=total,
        mean_realized_net_return=mean,
        trades=tuple(trades),
    )


def evaluate_portfolio_capacity_policy(
    model: HistoricalDirectionalModel,
    rows: Sequence[HistoricalTrainingRow],
    *,
    policy: HistoricalDecisionPolicy,
    costs: ExecutionCostAssumptions,
    allow_coin_calibration: bool,
    max_concurrent_positions: int,
) -> HistoricalPortfolioCapacityEvaluation:
    return evaluate_predicted_portfolio_capacity_policy(
        predict_training_rows(
            model,
            rows,
            allow_coin_calibration=allow_coin_calibration,
        ),
        policy=policy,
        costs=costs,
        max_concurrent_positions=max_concurrent_positions,
    )


def portfolio_capacity_trade_breakdowns(
    evaluation: HistoricalPortfolioCapacityEvaluation,
) -> tuple[HistoricalOccupancyBreakdownEntry, ...]:
    dimensions = (
        ("market", lambda item: item.market),
        ("horizon_ms", lambda item: str(item.horizon_ms)),
        ("action", lambda item: item.decision.action.value),
        ("trend_regime", lambda item: item.row.feature.trend_regime.value),
        ("estimate_source", lambda item: item.decision.estimate_source),
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


def summarize_portfolio_capacity_trades(
    trades: Sequence[HistoricalExecutedTrade],
) -> HistoricalOccupancyTradeSummary:
    return summarize_occupancy_trades(trades)
