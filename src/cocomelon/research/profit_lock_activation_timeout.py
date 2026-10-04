from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.research.profit_lock_execution_shadow import (
    EXECUTION_SHADOW_STATE_SCHEMA_VERSION,
    ProfitLockExecutionOutcome,
)
from cocomelon.research.prospective_breakeven_profit_lock import RULE_ID

TIMEOUT_HORIZONS_MS: Final = (
    5 * 60 * 1_000,
    15 * 60 * 1_000,
    30 * 60 * 1_000,
    60 * 60 * 1_000,
)
MAX_PROXY_MARK_LAG_MS: Final = 120_000
ZERO: Final = Decimal("0")


class ProfitLockActivationTimeoutError(RuntimeError):
    pass


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProfitLockActivationTimeoutError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ProfitLockActivationTimeoutError(
            f"{field} must be finite"
        )
    return resolved


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfitLockActivationTimeoutError(
            f"{field} must be an integer"
        )
    if value < 0:
        raise ProfitLockActivationTimeoutError(
            f"{field} must be non-negative"
        )
    return value


def _path_index(
    payloads: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    by_trade: dict[str, Mapping[str, object]] = {}
    for raw in payloads:
        trade_id = raw.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id:
            raise ProfitLockActivationTimeoutError(
                "trade path is missing trade_id"
            )
        if trade_id in by_trade:
            raise ProfitLockActivationTimeoutError(
                "trade paths contain duplicate trade_id"
            )
        by_trade[trade_id] = raw
    return by_trade


def _outcome_index(
    execution_shadow_state: object,
) -> dict[str, ProfitLockExecutionOutcome]:
    if not isinstance(execution_shadow_state, Mapping):
        raise ProfitLockActivationTimeoutError(
            "execution shadow state must be an object"
        )
    if execution_shadow_state.get("schema_version") != (
        EXECUTION_SHADOW_STATE_SCHEMA_VERSION
    ):
        raise ProfitLockActivationTimeoutError(
            "execution shadow state schema mismatch"
        )
    raw_outcomes = execution_shadow_state.get("outcomes")
    if not isinstance(raw_outcomes, Sequence) or isinstance(
        raw_outcomes,
        (str, bytes),
    ):
        raise ProfitLockActivationTimeoutError(
            "execution shadow outcomes must be an array"
        )
    selected = tuple(
        outcome
        for outcome in (
            ProfitLockExecutionOutcome.from_payload(raw)
            for raw in raw_outcomes
        )
        if outcome.rule_id == RULE_ID
    )
    by_trade: dict[str, ProfitLockExecutionOutcome] = {}
    for outcome in selected:
        if outcome.trade_id in by_trade:
            raise ProfitLockActivationTimeoutError(
                "breakeven outcomes contain duplicate trade_id"
            )
        by_trade[outcome.trade_id] = outcome
    return by_trade


def _gap_overlaps(
    raw_gaps: object,
    *,
    start_ms: int,
    end_ms: int,
) -> bool:
    if not isinstance(raw_gaps, Sequence) or isinstance(
        raw_gaps,
        (str, bytes),
    ):
        raise ProfitLockActivationTimeoutError(
            "known_gap_intervals must be an array"
        )
    for raw in raw_gaps:
        if (
            not isinstance(raw, Sequence)
            or isinstance(raw, (str, bytes))
            or len(raw) != 2
        ):
            raise ProfitLockActivationTimeoutError(
                "known gap interval is invalid"
            )
        started_ms = _integer(raw[0], "gap started_ms")
        raw_end = raw[1]
        if raw_end is None:
            ended_ms = None
        else:
            ended_ms = _integer(raw_end, "gap ended_ms")
            if ended_ms < started_ms:
                raise ProfitLockActivationTimeoutError(
                    "gap end precedes gap start"
                )
        if started_ms <= end_ms and (
            ended_ms is None or ended_ms >= start_ms
        ):
            return True
    return False


def _proxy_mark(
    path: Mapping[str, object],
    *,
    target_ms: int,
    max_lag_ms: int,
) -> tuple[int, Decimal] | None:
    raw_marks = path.get("marks")
    if not isinstance(raw_marks, Sequence) or isinstance(
        raw_marks,
        (str, bytes),
    ):
        raise ProfitLockActivationTimeoutError(
            "trade path marks must be an array"
        )
    candidate: tuple[int, Decimal] | None = None
    for raw in raw_marks:
        if not isinstance(raw, Mapping):
            raise ProfitLockActivationTimeoutError(
                "trade path mark must be an object"
            )
        available_at_ms = _integer(
            raw.get("available_at_ms"),
            "mark available_at_ms",
        )
        if available_at_ms < target_ms:
            continue
        if available_at_ms - target_ms > max_lag_ms:
            break
        mark_px = _decimal(raw.get("mark_px"), "mark_px")
        if mark_px <= ZERO:
            raise ProfitLockActivationTimeoutError(
                "mark_px must be positive"
            )
        candidate = (available_at_ms, mark_px)
        break
    return candidate


def _candidate_gross_pnl(
    trade: TradeJournalEntry,
    mark_px: Decimal,
) -> Decimal:
    if trade.direction.value == "long":
        return (
            mark_px - trade.entry_price
        ) * trade.filled_quantity
    return (
        trade.entry_price - mark_px
    ) * trade.filled_quantity


def _robustness(
    rows: Sequence[dict[str, object]],
) -> dict[str, object]:
    evaluated = tuple(
        row
        for row in rows
        if row.get("status") in {"intervened", "no_action"}
    )
    deltas = tuple(
        _decimal(row["delta_gross_pnl"], "delta_gross_pnl")
        for row in evaluated
    )
    delta_rs = tuple(
        _decimal(row["delta_gross_r"], "delta_gross_r")
        for row in evaluated
    )
    total_delta = sum(deltas, ZERO)
    total_delta_r = sum(delta_rs, ZERO)
    leave_trade = tuple(total_delta - value for value in deltas)
    leave_trade_r = tuple(
        total_delta_r - value for value in delta_rs
    )
    market_delta: dict[str, Decimal] = {}
    market_delta_r: dict[str, Decimal] = {}
    for row, delta, delta_r in zip(
        evaluated,
        deltas,
        delta_rs,
        strict=True,
    ):
        market = row.get("market")
        if not isinstance(market, str):
            raise ProfitLockActivationTimeoutError(
                "row market must be a string"
            )
        market_delta[market] = market_delta.get(
            market,
            ZERO,
        ) + delta
        market_delta_r[market] = market_delta_r.get(
            market,
            ZERO,
        ) + delta_r
    leave_market = tuple(
        total_delta - value for value in market_delta.values()
    )
    leave_market_r = tuple(
        total_delta_r - value
        for value in market_delta_r.values()
    )
    return {
        "evaluated_trades": len(evaluated),
        "market_count": len(market_delta),
        "delta_gross_pnl": str(total_delta),
        "delta_gross_r": str(total_delta_r),
        "leave_one_trade_out_min_delta_gross_pnl": str(
            min(leave_trade, default=ZERO)
        ),
        "leave_one_trade_out_min_delta_gross_r": str(
            min(leave_trade_r, default=ZERO)
        ),
        "positive_after_removing_any_one_trade": (
            len(evaluated) >= 2
            and min(leave_trade, default=ZERO) > ZERO
            and min(leave_trade_r, default=ZERO) > ZERO
        ),
        "leave_one_market_out_min_delta_gross_pnl": str(
            min(leave_market, default=ZERO)
        ),
        "leave_one_market_out_min_delta_gross_r": str(
            min(leave_market_r, default=ZERO)
        ),
        "positive_after_removing_any_one_market": (
            len(market_delta) >= 2
            and min(leave_market, default=ZERO) > ZERO
            and min(leave_market_r, default=ZERO) > ZERO
        ),
    }


def _horizon_summary(
    trades: Sequence[TradeJournalEntry],
    outcomes: Mapping[str, ProfitLockExecutionOutcome],
    paths: Mapping[str, Mapping[str, object]],
    *,
    horizon_ms: int,
    max_proxy_mark_lag_ms: int,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    exclusions: Counter[str] = Counter()
    interventions = 0
    for trade in trades:
        outcome = outcomes.get(trade.trade_id)
        if outcome is None:
            exclusions["missing_breakeven_outcome"] += 1
            rows.append(
                {
                    "trade_id": trade.trade_id,
                    "market": trade.market.canonical,
                    "direction": trade.direction.value,
                    "status": "excluded",
                    "reason": "missing_breakeven_outcome",
                }
            )
            continue
        if (
            outcome.opening_plan_id != trade.opening_plan_id
            or outcome.market != trade.market.canonical
            or outcome.direction != trade.direction.value
            or outcome.actual_net_pnl != trade.net_pnl
            or outcome.actual_net_r != trade.net_r
        ):
            raise ProfitLockActivationTimeoutError(
                "breakeven outcome journal lineage mismatch"
            )

        target_ms = trade.opened_at_ms + horizon_ms
        activation_ms = outcome.activation_timestamp_ms
        candidate_gross = trade.gross_realized_pnl
        status = "no_action"
        reason = "actual_close_before_timeout"
        proxy_available_at_ms: int | None = None
        proxy_mark_px: Decimal | None = None

        if trade.closed_at_ms > target_ms:
            if activation_ms is not None and activation_ms <= target_ms:
                reason = "activated_before_timeout"
            else:
                path = paths.get(trade.trade_id)
                if path is None:
                    exclusions["missing_trade_path"] += 1
                    rows.append(
                        {
                            "trade_id": trade.trade_id,
                            "market": trade.market.canonical,
                            "direction": trade.direction.value,
                            "status": "excluded",
                            "reason": "missing_trade_path",
                        }
                    )
                    continue
                if (
                    path.get("market") != trade.market.canonical
                    or path.get("direction") != trade.direction.value
                    or path.get("opened_at_ms") != trade.opened_at_ms
                    or path.get("closed_at_ms") != trade.closed_at_ms
                    or _decimal(path.get("entry_price"), "path entry_price")
                    != trade.entry_price
                    or _decimal(
                        path.get("filled_quantity"),
                        "path filled_quantity",
                    )
                    != trade.filled_quantity
                ):
                    raise ProfitLockActivationTimeoutError(
                        "trade path journal lineage mismatch"
                    )
                proxy = _proxy_mark(
                    path,
                    target_ms=target_ms,
                    max_lag_ms=max_proxy_mark_lag_ms,
                )
                if proxy is None:
                    exclusions["missing_proxy_mark"] += 1
                    rows.append(
                        {
                            "trade_id": trade.trade_id,
                            "market": trade.market.canonical,
                            "direction": trade.direction.value,
                            "status": "excluded",
                            "reason": "missing_proxy_mark",
                        }
                    )
                    continue
                proxy_available_at_ms, proxy_mark_px = proxy
                if _gap_overlaps(
                    path.get("known_gap_intervals"),
                    start_ms=target_ms,
                    end_ms=proxy_available_at_ms,
                ):
                    exclusions["gap_overlaps_proxy_window"] += 1
                    rows.append(
                        {
                            "trade_id": trade.trade_id,
                            "market": trade.market.canonical,
                            "direction": trade.direction.value,
                            "status": "excluded",
                            "reason": "gap_overlaps_proxy_window",
                        }
                    )
                    continue
                if (
                    activation_ms is not None
                    and activation_ms <= proxy_available_at_ms
                ):
                    exclusions["activation_during_proxy_lag"] += 1
                    rows.append(
                        {
                            "trade_id": trade.trade_id,
                            "market": trade.market.canonical,
                            "direction": trade.direction.value,
                            "status": "excluded",
                            "reason": "activation_during_proxy_lag",
                        }
                    )
                    continue
                candidate_gross = _candidate_gross_pnl(
                    trade,
                    proxy_mark_px,
                )
                status = "intervened"
                reason = "not_activated_by_timeout"
                interventions += 1

        actual_gross_r = (
            trade.gross_realized_pnl / trade.initial_risk_amount
        )
        candidate_gross_r = (
            candidate_gross / trade.initial_risk_amount
        )
        rows.append(
            {
                "trade_id": trade.trade_id,
                "market": trade.market.canonical,
                "direction": trade.direction.value,
                "status": status,
                "reason": reason,
                "opened_at_ms": trade.opened_at_ms,
                "closed_at_ms": trade.closed_at_ms,
                "target_ms": target_ms,
                "activation_timestamp_ms": activation_ms,
                "proxy_available_at_ms": proxy_available_at_ms,
                "proxy_mark_px": (
                    None
                    if proxy_mark_px is None
                    else str(proxy_mark_px)
                ),
                "actual_gross_pnl": str(trade.gross_realized_pnl),
                "candidate_gross_pnl": str(candidate_gross),
                "delta_gross_pnl": str(
                    candidate_gross - trade.gross_realized_pnl
                ),
                "actual_gross_r": str(actual_gross_r),
                "candidate_gross_r": str(candidate_gross_r),
                "delta_gross_r": str(
                    candidate_gross_r - actual_gross_r
                ),
            }
        )

    evaluated = tuple(
        row
        for row in rows
        if row.get("status") in {"intervened", "no_action"}
    )
    actual_gross = sum(
        (
            _decimal(row["actual_gross_pnl"], "actual_gross_pnl")
            for row in evaluated
        ),
        ZERO,
    )
    candidate_gross = sum(
        (
            _decimal(
                row["candidate_gross_pnl"],
                "candidate_gross_pnl",
            )
            for row in evaluated
        ),
        ZERO,
    )
    actual_r = sum(
        (
            _decimal(row["actual_gross_r"], "actual_gross_r")
            for row in evaluated
        ),
        ZERO,
    )
    candidate_r = sum(
        (
            _decimal(
                row["candidate_gross_r"],
                "candidate_gross_r",
            )
            for row in evaluated
        ),
        ZERO,
    )
    direction_interventions = Counter(
        str(row["direction"])
        for row in evaluated
        if row["status"] == "intervened"
    )
    robustness = _robustness(rows)
    return {
        "horizon_ms": horizon_ms,
        "evaluated_trades": len(evaluated),
        "excluded_trades": len(rows) - len(evaluated),
        "interventions": interventions,
        "interventions_by_direction": dict(
            sorted(direction_interventions.items())
        ),
        "exclusion_reason_counts": dict(sorted(exclusions.items())),
        "actual_gross_pnl": str(actual_gross),
        "candidate_gross_pnl": str(candidate_gross),
        "delta_gross_pnl": str(candidate_gross - actual_gross),
        "actual_gross_r": str(actual_r),
        "candidate_gross_r": str(candidate_r),
        "delta_gross_r": str(candidate_r - actual_r),
        "candidate_gross_profitable": (
            candidate_gross > ZERO and candidate_r > ZERO
        ),
        "delta_positive": (
            candidate_gross - actual_gross > ZERO
            and candidate_r - actual_r > ZERO
        ),
        "robustness": robustness,
        "rows": rows,
    }


def profit_lock_activation_timeout_summary(
    trades: Sequence[TradeJournalEntry],
    execution_shadow_state: object,
    trade_path_payloads: Sequence[Mapping[str, object]],
    *,
    horizons_ms: Sequence[int] = TIMEOUT_HORIZONS_MS,
    max_proxy_mark_lag_ms: int = MAX_PROXY_MARK_LAG_MS,
) -> dict[str, object]:
    if max_proxy_mark_lag_ms <= 0:
        raise ValueError("max_proxy_mark_lag_ms must be positive")
    horizons = tuple(horizons_ms)
    if (
        not horizons
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in horizons
        )
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise ValueError(
            "horizons_ms must be positive sorted unique integers"
        )
    outcomes = _outcome_index(execution_shadow_state)
    paths = _path_index(trade_path_payloads)
    matched_trades = tuple(
        trade for trade in trades if trade.trade_id in outcomes
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "descriptive_only": True,
        "changes_execution": False,
        "changes_risk_limits": False,
        "changes_candidate_readiness": False,
        "candidate_family": "breakeven_activation_timeout",
        "source_rule_id": RULE_ID,
        "activation_target_r": "0.5",
        "proxy_semantics": (
            "first_observed_mark_at_or_after_timeout_with_strict_lag_and_gap_exclusions"
        ),
        "max_proxy_mark_lag_ms": max_proxy_mark_lag_ms,
        "matched_breakeven_trades": len(matched_trades),
        "trade_path_records": len(paths),
        "horizons": {
            str(horizon_ms): _horizon_summary(
                matched_trades,
                outcomes,
                paths,
                horizon_ms=horizon_ms,
                max_proxy_mark_lag_ms=max_proxy_mark_lag_ms,
            )
            for horizon_ms in horizons
        },
    }
