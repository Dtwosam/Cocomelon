from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import (
    ExecutionResult,
    PaperExecutionConfig,
    PositionAction,
    PositionActionType,
)
from cocomelon.execution.accounting import PaperPosition, PositionSide
from cocomelon.execution.ioc import simulate_ioc
from cocomelon.execution.planner import (
    PlanningRejection,
    plan_reduce_only_order,
)
from cocomelon.research.continuous_paper_opening_opportunity_exit_books import (
    ContinuousPaperOpeningOpportunityExitBookStore,
    OpeningOpportunityExitBookEvidence,
)
from cocomelon.research.prospective_capacity_reflow_forward_markout import (
    DEFAULT_FORWARD_MARKOUT_HORIZONS_MS,
)

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")


class ProspectiveCapacityReflowExitFillError(RuntimeError):
    pass


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveCapacityReflowExitFillError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveCapacityReflowExitFillError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(
    value: object,
    field: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ProspectiveCapacityReflowExitFillError(
            f"{field} must be a decimal"
        ) from exc
    if not result.is_finite():
        raise ProspectiveCapacityReflowExitFillError(
            f"{field} must be finite"
        )
    if positive and result <= ZERO:
        raise ProspectiveCapacityReflowExitFillError(
            f"{field} must be positive"
        )
    if nonnegative and result < ZERO:
        raise ProspectiveCapacityReflowExitFillError(
            f"{field} must be non-negative"
        )
    return result


def _validate_config(
    fill_feasibility: dict[str, object],
    config: PaperExecutionConfig,
) -> None:
    raw = fill_feasibility.get("execution_config")
    if not isinstance(raw, dict):
        raise ProspectiveCapacityReflowExitFillError(
            "replacement entry execution config is missing"
        )
    expected = {
        "config_version": config.config_version,
        "latency_ms": config.latency_ms,
        "max_book_age_ms": config.max_book_age_ms,
        "max_ioc_slippage_bps": str(config.max_ioc_slippage_bps),
        "taker_fee_rate": str(config.taker_fee_rate),
        "fee_schedule_id": config.fee_schedule_id,
    }
    if raw != expected:
        raise ProspectiveCapacityReflowExitFillError(
            "replacement exit execution config drift"
        )


def _fillable_options(
    fill_feasibility: dict[str, object],
) -> tuple[dict[str, object], ...]:
    if fill_feasibility.get("replacement_entry_fills_modeled") is not True:
        raise ProspectiveCapacityReflowExitFillError(
            "replacement entry fills are not modeled"
        )
    raw_ids = fill_feasibility.get("fillable_option_ids")
    raw_options = fill_feasibility.get("option_results")
    if not isinstance(raw_ids, list) or not all(
        isinstance(value, str) for value in raw_ids
    ):
        raise ProspectiveCapacityReflowExitFillError(
            "fillable option ids are invalid"
        )
    if not isinstance(raw_options, list):
        raise ProspectiveCapacityReflowExitFillError(
            "replacement option results are invalid"
        )
    wanted = set(raw_ids)
    output: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_options:
        if not isinstance(raw, dict):
            raise ProspectiveCapacityReflowExitFillError(
                "replacement option result is invalid"
            )
        option_id = _text(raw.get("option_id"), "option_id")
        if option_id not in wanted:
            continue
        if option_id in seen:
            raise ProspectiveCapacityReflowExitFillError(
                "duplicate fillable replacement option"
            )
        seen.add(option_id)
        if raw.get("execution_result") not in {"full", "partial"}:
            raise ProspectiveCapacityReflowExitFillError(
                "fillable replacement option has invalid execution result"
            )
        if raw.get("planning_approved") is not True:
            raise ProspectiveCapacityReflowExitFillError(
                "fillable replacement option was not planned"
            )
        output.append(raw)
    if seen != wanted:
        raise ProspectiveCapacityReflowExitFillError(
            "fillable replacement option is missing"
        )
    output.sort(key=lambda item: str(item["option_id"]))
    return tuple(output)


def _book_index(
    records: tuple[OpeningOpportunityExitBookEvidence, ...],
) -> dict[tuple[str, int], OpeningOpportunityExitBookEvidence]:
    output: dict[
        tuple[str, int],
        OpeningOpportunityExitBookEvidence,
    ] = {}
    for record in records:
        key = (record.opportunity_id, record.horizon_ms)
        if key in output:
            raise ProspectiveCapacityReflowExitFillError(
                "duplicate replacement exit book"
            )
        output[key] = record
    return output


def _best_reference(
    evidence: OpeningOpportunityExitBookEvidence,
    side: PositionSide,
) -> Decimal:
    raw = (
        evidence.book_event.payload.get("bids")
        if side is PositionSide.LONG
        else evidence.book_event.payload.get("asks")
    )
    if not isinstance(raw, (tuple, list)) or not raw:
        raise ProspectiveCapacityReflowExitFillError(
            "replacement exit book side is empty"
        )
    prices: list[Decimal] = []
    for row in raw:
        if not isinstance(row, dict):
            raise ProspectiveCapacityReflowExitFillError(
                "replacement exit book level is invalid"
            )
        prices.append(_decimal(row.get("px"), "exit book price", positive=True))
    return max(prices) if side is PositionSide.LONG else min(prices)


def _gross_pnl(
    *,
    side: PositionSide,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if side is PositionSide.LONG:
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def prospective_capacity_reflow_exit_fill_summary(
    fill_feasibility: dict[str, object],
    exit_books: tuple[OpeningOpportunityExitBookEvidence, ...],
    config: PaperExecutionConfig,
    *,
    horizons_ms: tuple[int, ...] = DEFAULT_FORWARD_MARKOUT_HORIZONS_MS,
) -> dict[str, object]:
    _validate_config(fill_feasibility, config)
    if (
        not horizons_ms
        or tuple(sorted(set(horizons_ms))) != horizons_ms
        or any(value <= 0 for value in horizons_ms)
    ):
        raise ValueError("horizons_ms must be positive and strictly increasing")

    options = _fillable_options(fill_feasibility)
    books = _book_index(exit_books)
    by_horizon = {
        str(horizon_ms): {
            "horizon_ms": horizon_ms,
            "fillable_options": len(options),
            "captured_exit_books": 0,
            "missing_exit_books": 0,
            "full_exit_fills": 0,
            "partial_exit_fills": 0,
            "no_exit_fills": 0,
            "rejected_exit_attempts": 0,
            "gross_realized_pnl": ZERO,
            "allocated_entry_fee": ZERO,
            "exit_fee": ZERO,
            "entry_exit_fee_adjusted_pnl": ZERO,
            "unclosed_quantity": ZERO,
        }
        for horizon_ms in horizons_ms
    }

    option_exits: list[dict[str, object]] = []
    by_result: Counter[str] = Counter()
    total_gross = ZERO
    total_entry_fee = ZERO
    total_exit_fee = ZERO
    total_net = ZERO
    total_unclosed = ZERO

    for option in options:
        option_id = _text(option.get("option_id"), "option_id")
        opportunity_id = _text(
            option.get("opportunity_id"),
            "opportunity_id",
        )
        market = _text(
            option.get("opportunity_market"),
            "opportunity_market",
        )
        direction = _text(
            option.get("opportunity_direction"),
            "opportunity_direction",
        )
        if direction not in {"long", "short"}:
            raise ProspectiveCapacityReflowExitFillError(
                "replacement direction is invalid"
            )
        side = (
            PositionSide.LONG
            if direction == "long"
            else PositionSide.SHORT
        )
        opportunity_timestamp_ms = _integer(
            option.get("opportunity_timestamp_ms"),
            "opportunity_timestamp_ms",
        )
        entry_attempt_ms = _integer(
            option.get("entry_attempt_timestamp_ms"),
            "entry_attempt_timestamp_ms",
        )
        entry_price = _decimal(
            option.get("average_fill_price"),
            "average_fill_price",
            positive=True,
        )
        entry_quantity = _decimal(
            option.get("filled_quantity"),
            "filled_quantity",
            positive=True,
        )
        entry_notional = _decimal(
            option.get("gross_fill_notional"),
            "gross_fill_notional",
            positive=True,
        )
        if entry_price * entry_quantity != entry_notional:
            raise ProspectiveCapacityReflowExitFillError(
                "replacement entry economics do not reconcile"
            )
        entry_fee = _decimal(
            option.get("taker_fee"),
            "taker_fee",
            nonnegative=True,
        )
        opening_plan_id = _text(
            option.get("opening_plan_id"),
            "opening_plan_id",
        )
        opening_risk_id = _text(
            option.get("opening_risk_decision_id"),
            "opening_risk_decision_id",
        )
        opening_strategy_id = _text(
            option.get("opening_strategy_decision_id"),
            "opening_strategy_decision_id",
        )
        stop_price = _decimal(
            option.get("opening_stop_price"),
            "opening_stop_price",
            positive=True,
        )
        correlation_bucket = _text(
            option.get("correlation_bucket"),
            "correlation_bucket",
        )
        venue_max_leverage = _decimal(
            option.get("venue_max_leverage"),
            "venue_max_leverage",
            positive=True,
        )

        exits: dict[str, object] = {}
        for horizon_ms in horizons_ms:
            horizon_key = str(horizon_ms)
            aggregate = by_horizon[horizon_key]
            evidence = books.get((opportunity_id, horizon_ms))
            if evidence is None:
                aggregate["missing_exit_books"] += 1
                exits[horizon_key] = {
                    "status": "missing_exit_book",
                    "horizon_ms": horizon_ms,
                }
                continue
            aggregate["captured_exit_books"] += 1
            if (
                evidence.market != market
                or evidence.direction != direction
                or evidence.opportunity_timestamp_ms
                != opportunity_timestamp_ms
            ):
                raise ProspectiveCapacityReflowExitFillError(
                    "replacement exit book lineage mismatch"
                )
            if evidence.instrument.venue_max_leverage != venue_max_leverage:
                raise ProspectiveCapacityReflowExitFillError(
                    "replacement exit instrument leverage drift"
                )

            position = PaperPosition(
                market=evidence.instrument.market,
                side=side,
                quantity=entry_quantity,
                average_entry_price=entry_price,
                stop_price=stop_price,
                opening_plan_id=opening_plan_id,
                opened_at_ms=entry_attempt_ms,
                updated_at_ms=entry_attempt_ms,
                initial_risk_decision_id=opening_risk_id,
                correlation_bucket=correlation_bucket,
                cumulative_fees=entry_fee,
                venue_max_leverage=venue_max_leverage,
                latest_mark=entry_price,
            )
            reference_price = _best_reference(evidence, side)
            action = PositionAction(
                action_type=PositionActionType.EXIT_THESIS,
                market=position.market,
                quantity=position.quantity,
                new_stop_price=None,
                reason_codes=("replacement_fixed_horizon_exit",),
                timestamp_ms=evidence.observed_at_ms,
            )
            plan = plan_reduce_only_order(
                position,
                action,
                evidence.instrument,
                config,
                originating_risk_decision_id=opening_risk_id,
                originating_strategy_decision_id=opening_strategy_id,
                reference_price=reference_price,
                created_at_ms=evidence.observed_at_ms,
            )
            if isinstance(plan, PlanningRejection):
                aggregate["rejected_exit_attempts"] += 1
                by_result["planning_rejected"] += 1
                exits[horizon_key] = {
                    "status": "planning_rejected",
                    "horizon_ms": horizon_ms,
                    "reason": plan.reason,
                }
                continue

            attempt_ms = evidence.observed_at_ms + config.latency_ms
            simulation = simulate_ioc(
                plan,
                evidence.book_event,
                evidence.instrument,
                config,
                attempt_timestamp_ms=attempt_ms,
            )
            attempt = simulation.attempt
            by_result[attempt.result.value] += 1
            if attempt.result is ExecutionResult.FULL:
                aggregate["full_exit_fills"] += 1
            elif attempt.result is ExecutionResult.PARTIAL:
                aggregate["partial_exit_fills"] += 1
            elif attempt.result is ExecutionResult.NO_FILL:
                aggregate["no_exit_fills"] += 1
            else:
                aggregate["rejected_exit_attempts"] += 1

            gross = sum(
                (
                    _gross_pnl(
                        side=side,
                        entry_price=entry_price,
                        exit_price=fill.price,
                        quantity=fill.quantity,
                    )
                    for fill in simulation.fills
                ),
                ZERO,
            )
            allocated_entry_fee = (
                ZERO
                if attempt.filled_quantity == ZERO
                else entry_fee
                * attempt.filled_quantity
                / entry_quantity
            )
            net = gross - allocated_entry_fee - attempt.fee
            unclosed = entry_quantity - attempt.filled_quantity

            aggregate["gross_realized_pnl"] += gross
            aggregate["allocated_entry_fee"] += allocated_entry_fee
            aggregate["exit_fee"] += attempt.fee
            aggregate["entry_exit_fee_adjusted_pnl"] += net
            aggregate["unclosed_quantity"] += unclosed
            total_gross += gross
            total_entry_fee += allocated_entry_fee
            total_exit_fee += attempt.fee
            total_net += net
            total_unclosed += unclosed

            exits[horizon_key] = {
                "status": "simulated",
                "horizon_ms": horizon_ms,
                "target_at_ms": evidence.target_at_ms,
                "observed_at_ms": evidence.observed_at_ms,
                "observation_lag_ms": evidence.observation_lag_ms,
                "attempt_timestamp_ms": attempt.attempt_timestamp_ms,
                "execution_result": attempt.result.value,
                "reason_codes": list(attempt.reason_codes),
                "requested_quantity": str(attempt.requested_quantity),
                "filled_quantity": str(attempt.filled_quantity),
                "unfilled_quantity": str(attempt.unfilled_quantity),
                "average_exit_price": (
                    None
                    if attempt.average_fill_price is None
                    else str(attempt.average_fill_price)
                ),
                "gross_exit_notional": str(attempt.gross_fill_notional),
                "gross_realized_pnl": str(gross),
                "allocated_entry_fee": str(allocated_entry_fee),
                "exit_fee": str(attempt.fee),
                "entry_exit_fee_adjusted_pnl": str(net),
                "funding_pnl": None,
                "complete_close": (
                    attempt.result is ExecutionResult.FULL
                ),
            }

        option_exits.append(
            {
                "option_id": option_id,
                "opportunity_id": opportunity_id,
                "opportunity_timestamp_ms": opportunity_timestamp_ms,
                "opportunity_market": market,
                "opportunity_direction": direction,
                "opening_plan_id": opening_plan_id,
                "entry_attempt_timestamp_ms": entry_attempt_ms,
                "entry_price": str(entry_price),
                "entry_quantity": str(entry_quantity),
                "entry_fee": str(entry_fee),
                "exits": exits,
            }
        )

    by_horizon_payload: dict[str, object] = {}
    for horizon_ms in horizons_ms:
        key = str(horizon_ms)
        raw = by_horizon[key]
        by_horizon_payload[key] = {
            **raw,
            "gross_realized_pnl": str(raw["gross_realized_pnl"]),
            "allocated_entry_fee": str(raw["allocated_entry_fee"]),
            "exit_fee": str(raw["exit_fee"]),
            "entry_exit_fee_adjusted_pnl": str(
                raw["entry_exit_fee_adjusted_pnl"]
            ),
            "unclosed_quantity": str(raw["unclosed_quantity"]),
        }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "candidate_caused_replacement_real_l2_fixed_horizon_exit_fill"
        ),
        "fillable_options": len(options),
        "exit_book_records": len(exit_books),
        "horizons_ms": list(horizons_ms),
        "option_exits": option_exits,
        "by_horizon": by_horizon_payload,
        "by_execution_result": dict(sorted(by_result.items())),
        "gross_realized_pnl": str(total_gross),
        "allocated_entry_fee": str(total_entry_fee),
        "exit_fee": str(total_exit_fee),
        "entry_exit_fee_adjusted_pnl": str(total_net),
        "unclosed_quantity": str(total_unclosed),
        "replacement_entry_fills_modeled": True,
        "replacement_exit_fills_modeled": True,
        "funding_modeled": False,
        "replacement_trade_pnl_complete": False,
        "realized_pnl_claimed": False,
    }


def evaluate_prospective_capacity_reflow_exit_fill(
    fill_feasibility: dict[str, object],
    exit_book_store: ContinuousPaperOpeningOpportunityExitBookStore,
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return prospective_capacity_reflow_exit_fill_summary(
        fill_feasibility,
        exit_book_store.iter_records(),
        config,
        horizons_ms=exit_book_store.horizons_ms,
    )
