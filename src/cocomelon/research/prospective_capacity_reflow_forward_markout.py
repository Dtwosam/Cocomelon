from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathStore,
)

ZERO: Final = Decimal("0")
DEFAULT_FORWARD_MARKOUT_HORIZONS_MS: Final = (
    300_000,
    900_000,
    3_600_000,
    21_600_000,
)
MAX_FORWARD_MARKOUT_LAG_MS: Final = 120_000
FILL_RESULTS: Final = frozenset({"full", "partial"})


class ProspectiveCapacityReflowForwardMarkoutError(RuntimeError):
    pass


@dataclass(slots=True)
class _HorizonAggregate:
    horizon_ms: int
    fillable_options: int
    settled_options: int = 0
    pending_options: int = 0
    stale_options: int = 0
    missing_path_options: int = 0
    positive_options: int = 0
    negative_options: int = 0
    flat_options: int = 0
    gross_mark_to_market_pnl: Decimal = ZERO
    entry_fee_adjusted_mark_to_market_pnl: Decimal = ZERO
    return_sum: Decimal = ZERO

    def payload(self) -> dict[str, object]:
        return {
            "horizon_ms": self.horizon_ms,
            "fillable_options": self.fillable_options,
            "settled_options": self.settled_options,
            "pending_options": self.pending_options,
            "stale_options": self.stale_options,
            "missing_path_options": self.missing_path_options,
            "positive_options": self.positive_options,
            "negative_options": self.negative_options,
            "flat_options": self.flat_options,
            "gross_mark_to_market_pnl": str(
                self.gross_mark_to_market_pnl
            ),
            "entry_fee_adjusted_mark_to_market_pnl": str(
                self.entry_fee_adjusted_mark_to_market_pnl
            ),
            "mean_directional_return_fraction": (
                None
                if self.settled_options == 0
                else str(
                    self.return_sum
                    / Decimal(self.settled_options)
                )
            ),
        }


def _require_text(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ProspectiveCapacityReflowForwardMarkoutError(
            f"{field} must be a non-empty string"
        )
    return raw


def _require_int(raw: object, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            f"{field} must be a non-negative integer"
        )
    return raw


def _require_decimal(
    raw: object,
    field: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            f"{field} must be a decimal"
        ) from exc
    if not value.is_finite():
        raise ProspectiveCapacityReflowForwardMarkoutError(
            f"{field} must be finite"
        )
    if positive and value <= ZERO:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            f"{field} must be positive"
        )
    if nonnegative and value < ZERO:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            f"{field} must be non-negative"
        )
    return value


def _validated_horizons(
    horizons_ms: tuple[int, ...],
) -> tuple[int, ...]:
    if not horizons_ms:
        raise ValueError("horizons_ms must not be empty")
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        for value in horizons_ms
    ):
        raise ValueError("horizons_ms must contain positive integers")
    if tuple(sorted(set(horizons_ms))) != horizons_ms:
        raise ValueError(
            "horizons_ms must be unique and strictly increasing"
        )
    return horizons_ms


def _fillable_option_records(
    fill_feasibility: dict[str, object],
) -> tuple[dict[str, object], ...]:
    if fill_feasibility.get("replacement_entry_fills_modeled") is not True:
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement entry fill evidence is not enabled"
        )
    raw_results = fill_feasibility.get("option_results")
    if not isinstance(raw_results, list):
        raise ProspectiveCapacityReflowForwardMarkoutError(
            "replacement fill option results are missing"
        )

    output: list[dict[str, object]] = []
    seen_option_ids: set[str] = set()
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise ProspectiveCapacityReflowForwardMarkoutError(
                "replacement fill option result must be an object"
            )
        result = raw.get("execution_result")
        if result not in FILL_RESULTS:
            continue

        option_id = _require_text(raw.get("option_id"), "option_id")
        if option_id in seen_option_ids:
            raise ProspectiveCapacityReflowForwardMarkoutError(
                "duplicate replacement fill option id"
            )
        seen_option_ids.add(option_id)

        direction = _require_text(
            raw.get("opportunity_direction"),
            "opportunity_direction",
        )
        if direction not in {"long", "short"}:
            raise ProspectiveCapacityReflowForwardMarkoutError(
                "opportunity_direction must be long or short"
            )
        filled_quantity = _require_decimal(
            raw.get("filled_quantity"),
            "filled_quantity",
            positive=True,
        )
        entry_price = _require_decimal(
            raw.get("average_fill_price"),
            "average_fill_price",
            positive=True,
        )
        gross_fill_notional = _require_decimal(
            raw.get("gross_fill_notional"),
            "gross_fill_notional",
            positive=True,
        )
        entry_fee = _require_decimal(
            raw.get("taker_fee"),
            "taker_fee",
            nonnegative=True,
        )
        if entry_price * filled_quantity != gross_fill_notional:
            raise ProspectiveCapacityReflowForwardMarkoutError(
                "replacement fill economics do not reconcile"
            )

        output.append(
            {
                "option_id": option_id,
                "opportunity_id": _require_text(
                    raw.get("opportunity_id"),
                    "opportunity_id",
                ),
                "opportunity_timestamp_ms": _require_int(
                    raw.get("opportunity_timestamp_ms"),
                    "opportunity_timestamp_ms",
                ),
                "opportunity_market": _require_text(
                    raw.get("opportunity_market"),
                    "opportunity_market",
                ),
                "opportunity_direction": direction,
                "release_market": _require_text(
                    raw.get("release_market"),
                    "release_market",
                ),
                "release_opening_plan_id": _require_text(
                    raw.get("release_opening_plan_id"),
                    "release_opening_plan_id",
                ),
                "attempt_id": _require_text(
                    raw.get("attempt_id"),
                    "attempt_id",
                ),
                "filled_quantity": filled_quantity,
                "entry_price": entry_price,
                "gross_fill_notional": gross_fill_notional,
                "entry_fee": entry_fee,
            }
        )
    output.sort(key=lambda item: str(item["option_id"]))
    return tuple(output)


def _path_by_opportunity_id(
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    output: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        if path.opportunity_id in output:
            raise ProspectiveCapacityReflowForwardMarkoutError(
                "duplicate forward path opportunity id"
            )
        output[path.opportunity_id] = path
    return output


def _empty_markout(
    *,
    status: str,
    horizon_ms: int,
    target_at_ms: int,
    observed_at_ms: int | None = None,
    observation_lag_ms: int | None = None,
    mark_px: Decimal | None = None,
) -> dict[str, object]:
    return {
        "status": status,
        "horizon_ms": horizon_ms,
        "target_at_ms": target_at_ms,
        "observed_at_ms": observed_at_ms,
        "observation_lag_ms": observation_lag_ms,
        "mark_px": None if mark_px is None else str(mark_px),
        "directional_return_fraction": None,
        "gross_mark_to_market_pnl": None,
        "entry_fee_adjusted_mark_to_market_pnl": None,
    }


def prospective_capacity_reflow_forward_markout_summary(
    fill_feasibility: dict[str, object],
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
    *,
    horizons_ms: tuple[int, ...] = (
        DEFAULT_FORWARD_MARKOUT_HORIZONS_MS
    ),
    max_mark_lag_ms: int = MAX_FORWARD_MARKOUT_LAG_MS,
) -> dict[str, object]:
    horizons = _validated_horizons(horizons_ms)
    if (
        isinstance(max_mark_lag_ms, bool)
        or not isinstance(max_mark_lag_ms, int)
        or max_mark_lag_ms < 0
    ):
        raise ValueError("max_mark_lag_ms must be non-negative")

    options = _fillable_option_records(fill_feasibility)
    paths_by_id = _path_by_opportunity_id(paths)
    by_horizon = {
        str(horizon_ms): _HorizonAggregate(
            horizon_ms=horizon_ms,
            fillable_options=len(options),
        )
        for horizon_ms in horizons
    }

    paths_available = 0
    paths_missing = 0
    option_markouts: list[dict[str, object]] = []
    for option in options:
        opportunity_id = str(option["opportunity_id"])
        timestamp_ms = int(option["opportunity_timestamp_ms"])
        market = str(option["opportunity_market"])
        direction = str(option["opportunity_direction"])
        quantity = Decimal(str(option["filled_quantity"]))
        entry_price = Decimal(str(option["entry_price"]))
        entry_fee = Decimal(str(option["entry_fee"]))
        path = paths_by_id.get(opportunity_id)
        if path is None:
            paths_missing += 1
        else:
            paths_available += 1
            if (
                path.market != market
                or path.direction != direction
                or path.opportunity_timestamp_ms != timestamp_ms
            ):
                raise ProspectiveCapacityReflowForwardMarkoutError(
                    "forward path lineage mismatch"
                )
            if max(horizons) > path.max_path_age_ms:
                raise ProspectiveCapacityReflowForwardMarkoutError(
                    "forward markout horizon exceeds captured path"
                )

        markouts: dict[str, dict[str, object]] = {}
        for horizon_ms in horizons:
            horizon_key = str(horizon_ms)
            aggregate = by_horizon[horizon_key]
            target_at_ms = timestamp_ms + horizon_ms
            if path is None:
                markout = _empty_markout(
                    status="missing_path",
                    horizon_ms=horizon_ms,
                    target_at_ms=target_at_ms,
                )
                aggregate.missing_path_options += 1
                markouts[horizon_key] = markout
                continue

            mark = next(
                (
                    item
                    for item in path.marks
                    if item.observed_at_ms >= target_at_ms
                ),
                None,
            )
            if mark is None:
                markout = _empty_markout(
                    status="pending",
                    horizon_ms=horizon_ms,
                    target_at_ms=target_at_ms,
                )
                aggregate.pending_options += 1
                markouts[horizon_key] = markout
                continue

            lag_ms = mark.observed_at_ms - target_at_ms
            if lag_ms > max_mark_lag_ms:
                markout = _empty_markout(
                    status="stale",
                    horizon_ms=horizon_ms,
                    target_at_ms=target_at_ms,
                    observed_at_ms=mark.observed_at_ms,
                    observation_lag_ms=lag_ms,
                    mark_px=mark.mark_px,
                )
                aggregate.stale_options += 1
                markouts[horizon_key] = markout
                continue

            signed_move = (
                mark.mark_px - entry_price
                if direction == "long"
                else entry_price - mark.mark_px
            )
            directional_return = signed_move / entry_price
            gross_mtm = signed_move * quantity
            entry_fee_adjusted_mtm = gross_mtm - entry_fee
            markout = {
                "status": "settled",
                "horizon_ms": horizon_ms,
                "target_at_ms": target_at_ms,
                "observed_at_ms": mark.observed_at_ms,
                "observation_lag_ms": lag_ms,
                "mark_px": str(mark.mark_px),
                "directional_return_fraction": str(
                    directional_return
                ),
                "gross_mark_to_market_pnl": str(gross_mtm),
                "entry_fee_adjusted_mark_to_market_pnl": str(
                    entry_fee_adjusted_mtm
                ),
            }
            aggregate.settled_options += 1
            aggregate.gross_mark_to_market_pnl += gross_mtm
            aggregate.entry_fee_adjusted_mark_to_market_pnl += (
                entry_fee_adjusted_mtm
            )
            aggregate.return_sum += directional_return
            if entry_fee_adjusted_mtm > ZERO:
                aggregate.positive_options += 1
            elif entry_fee_adjusted_mtm < ZERO:
                aggregate.negative_options += 1
            else:
                aggregate.flat_options += 1
            markouts[horizon_key] = markout

        option_markouts.append(
            {
                "option_id": option["option_id"],
                "opportunity_id": opportunity_id,
                "opportunity_timestamp_ms": timestamp_ms,
                "opportunity_market": market,
                "opportunity_direction": direction,
                "release_market": option["release_market"],
                "release_opening_plan_id": (
                    option["release_opening_plan_id"]
                ),
                "attempt_id": option["attempt_id"],
                "entry_price": str(entry_price),
                "filled_quantity": str(quantity),
                "gross_fill_notional": str(
                    option["gross_fill_notional"]
                ),
                "entry_fee": str(entry_fee),
                "markouts": markouts,
            }
        )

    rendered_horizons = {
        str(horizon_ms): by_horizon[str(horizon_ms)].payload()
        for horizon_ms in horizons
    }

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "candidate_caused_replacement_entry_"
            "observed_forward_mark_to_market"
        ),
        "horizons_ms": list(horizons),
        "max_mark_lag_ms": max_mark_lag_ms,
        "fillable_options": len(options),
        "paths_available": paths_available,
        "paths_missing": paths_missing,
        "option_markouts": option_markouts,
        "by_horizon": rendered_horizons,
        "positive_definition": (
            "entry_fee_adjusted_mark_to_market_pnl_gt_zero"
        ),
        "replacement_entry_fills_modeled": True,
        "replacement_forward_markouts_modeled": True,
        "replacement_exits_modeled": False,
        "replacement_trades_modeled": False,
        "realized_pnl_modeled": False,
        "exit_fees_modeled": False,
    }


def evaluate_prospective_capacity_reflow_forward_markout(
    fill_feasibility: dict[str, object],
    path_store: ContinuousPaperOpeningOpportunityPathStore,
    *,
    horizons_ms: tuple[int, ...] = (
        DEFAULT_FORWARD_MARKOUT_HORIZONS_MS
    ),
    max_mark_lag_ms: int = MAX_FORWARD_MARKOUT_LAG_MS,
) -> dict[str, object]:
    return prospective_capacity_reflow_forward_markout_summary(
        fill_feasibility,
        path_store.iter_paths(),
        horizons_ms=horizons_ms,
        max_mark_lag_ms=max_mark_lag_ms,
    )
