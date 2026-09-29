from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
    ContinuousPaperOpeningOpportunityPathStore,
)

ZERO: Final = Decimal("0")


class ProspectiveCapacityReflowForwardExcursionError(RuntimeError):
    pass


def _text(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ProspectiveCapacityReflowForwardExcursionError(
            f"{field} must be a non-empty string"
        )
    return raw


def _integer(raw: object, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ProspectiveCapacityReflowForwardExcursionError(
            f"{field} must be a non-negative integer"
        )
    return raw


def _decimal(
    raw: object,
    field: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveCapacityReflowForwardExcursionError(
            f"{field} must be a decimal"
        ) from exc
    if not value.is_finite():
        raise ProspectiveCapacityReflowForwardExcursionError(
            f"{field} must be finite"
        )
    if positive and value <= ZERO:
        raise ProspectiveCapacityReflowForwardExcursionError(
            f"{field} must be positive"
        )
    if nonnegative and value < ZERO:
        raise ProspectiveCapacityReflowForwardExcursionError(
            f"{field} must be non-negative"
        )
    return value


@dataclass(slots=True)
class _Aggregate:
    horizon_ms: int
    fillable_options: int
    settled_options: int = 0
    pending_options: int = 0
    stale_options: int = 0
    missing_path_options: int = 0
    positive_peak_options: int = 0
    negative_end_options: int = 0
    positive_peak_to_negative_end_options: int = 0
    observed_mark_count: int = 0
    best_entry_fee_adjusted_mtm_pnl: Decimal = ZERO
    worst_entry_fee_adjusted_mtm_pnl: Decimal = ZERO
    ending_entry_fee_adjusted_mtm_pnl: Decimal = ZERO
    peak_to_end_giveback_pnl: Decimal = ZERO
    time_to_best_sum_ms: int = 0

    def payload(self) -> dict[str, object]:
        return {
            "horizon_ms": self.horizon_ms,
            "fillable_options": self.fillable_options,
            "settled_options": self.settled_options,
            "pending_options": self.pending_options,
            "stale_options": self.stale_options,
            "missing_path_options": self.missing_path_options,
            "positive_peak_options": self.positive_peak_options,
            "negative_end_options": self.negative_end_options,
            "positive_peak_to_negative_end_options": (
                self.positive_peak_to_negative_end_options
            ),
            "observed_mark_count": self.observed_mark_count,
            "best_entry_fee_adjusted_mtm_pnl": str(
                self.best_entry_fee_adjusted_mtm_pnl
            ),
            "worst_entry_fee_adjusted_mtm_pnl": str(
                self.worst_entry_fee_adjusted_mtm_pnl
            ),
            "ending_entry_fee_adjusted_mtm_pnl": str(
                self.ending_entry_fee_adjusted_mtm_pnl
            ),
            "peak_to_end_giveback_pnl": str(
                self.peak_to_end_giveback_pnl
            ),
            "mean_time_to_best_ms": (
                None
                if self.settled_options == 0
                else self.time_to_best_sum_ms
                // self.settled_options
            ),
        }


def _paths_by_id(
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    result: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        if path.opportunity_id in result:
            raise ProspectiveCapacityReflowForwardExcursionError(
                "duplicate forward excursion opportunity path"
            )
        result[path.opportunity_id] = path
    return result


def _validated_options(
    forward_markout: dict[str, object],
) -> tuple[dict[str, object], ...]:
    if (
        forward_markout.get("replacement_forward_markouts_modeled")
        is not True
    ):
        raise ProspectiveCapacityReflowForwardExcursionError(
            "replacement forward markouts are not enabled"
        )
    raw_options = forward_markout.get("option_markouts")
    if not isinstance(raw_options, list):
        raise ProspectiveCapacityReflowForwardExcursionError(
            "forward markout option records are missing"
        )
    seen: set[str] = set()
    output: list[dict[str, object]] = []
    for raw in raw_options:
        if not isinstance(raw, dict):
            raise ProspectiveCapacityReflowForwardExcursionError(
                "forward markout option must be an object"
            )
        option_id = _text(raw.get("option_id"), "option_id")
        if option_id in seen:
            raise ProspectiveCapacityReflowForwardExcursionError(
                "duplicate forward excursion option id"
            )
        seen.add(option_id)
        direction = _text(
            raw.get("opportunity_direction"),
            "opportunity_direction",
        )
        if direction not in {"long", "short"}:
            raise ProspectiveCapacityReflowForwardExcursionError(
                "opportunity_direction must be long or short"
            )
        markouts = raw.get("markouts")
        if not isinstance(markouts, dict):
            raise ProspectiveCapacityReflowForwardExcursionError(
                "forward markout horizons are missing"
            )
        output.append(
            {
                "option_id": option_id,
                "opportunity_id": _text(
                    raw.get("opportunity_id"),
                    "opportunity_id",
                ),
                "opportunity_timestamp_ms": _integer(
                    raw.get("opportunity_timestamp_ms"),
                    "opportunity_timestamp_ms",
                ),
                "opportunity_market": _text(
                    raw.get("opportunity_market"),
                    "opportunity_market",
                ),
                "opportunity_direction": direction,
                "release_market": _text(
                    raw.get("release_market"),
                    "release_market",
                ),
                "release_opening_plan_id": _text(
                    raw.get("release_opening_plan_id"),
                    "release_opening_plan_id",
                ),
                "attempt_id": _text(
                    raw.get("attempt_id"),
                    "attempt_id",
                ),
                "entry_price": _decimal(
                    raw.get("entry_price"),
                    "entry_price",
                    positive=True,
                ),
                "filled_quantity": _decimal(
                    raw.get("filled_quantity"),
                    "filled_quantity",
                    positive=True,
                ),
                "gross_fill_notional": _decimal(
                    raw.get("gross_fill_notional"),
                    "gross_fill_notional",
                    positive=True,
                ),
                "entry_fee": _decimal(
                    raw.get("entry_fee"),
                    "entry_fee",
                    nonnegative=True,
                ),
                "markouts": markouts,
            }
        )
    output.sort(key=lambda item: str(item["option_id"]))
    return tuple(output)


def _mtm(
    *,
    direction: str,
    entry_price: Decimal,
    quantity: Decimal,
    entry_fee: Decimal,
    mark_px: Decimal,
) -> Decimal:
    move = (
        mark_px - entry_price
        if direction == "long"
        else entry_price - mark_px
    )
    return move * quantity - entry_fee


def _empty_excursion(
    *,
    status: str,
    horizon_ms: int,
) -> dict[str, object]:
    return {
        "status": status,
        "horizon_ms": horizon_ms,
        "observed_marks": 0,
        "best_mark_px": None,
        "best_observed_at_ms": None,
        "time_to_best_ms": None,
        "worst_mark_px": None,
        "worst_observed_at_ms": None,
        "time_to_worst_ms": None,
        "best_entry_fee_adjusted_mtm_pnl": None,
        "worst_entry_fee_adjusted_mtm_pnl": None,
        "ending_entry_fee_adjusted_mtm_pnl": None,
        "peak_to_end_giveback_pnl": None,
        "positive_peak_to_negative_end": False,
    }


def prospective_capacity_reflow_forward_excursion_summary(
    forward_markout: dict[str, object],
    paths: tuple[ContinuousPaperOpeningOpportunityPath, ...],
) -> dict[str, object]:
    options = _validated_options(forward_markout)
    paths_by_id = _paths_by_id(paths)

    raw_horizons = forward_markout.get("horizons_ms")
    if (
        not isinstance(raw_horizons, list)
        or not raw_horizons
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in raw_horizons
        )
    ):
        raise ProspectiveCapacityReflowForwardExcursionError(
            "forward markout horizons are invalid"
        )
    horizons = tuple(raw_horizons)
    if tuple(sorted(set(horizons))) != horizons:
        raise ProspectiveCapacityReflowForwardExcursionError(
            "forward markout horizons must be strictly increasing"
        )

    by_horizon = {
        str(horizon_ms): _Aggregate(
            horizon_ms=horizon_ms,
            fillable_options=len(options),
        )
        for horizon_ms in horizons
    }
    paths_available = 0
    paths_missing = 0
    option_excursions: list[dict[str, object]] = []

    for option in options:
        opportunity_id = str(option["opportunity_id"])
        timestamp_ms = int(option["opportunity_timestamp_ms"])
        market = str(option["opportunity_market"])
        direction = str(option["opportunity_direction"])
        entry_price = Decimal(str(option["entry_price"]))
        quantity = Decimal(str(option["filled_quantity"]))
        gross_fill_notional = Decimal(
            str(option["gross_fill_notional"])
        )
        entry_fee = Decimal(str(option["entry_fee"]))
        if entry_price * quantity != gross_fill_notional:
            raise ProspectiveCapacityReflowForwardExcursionError(
                "forward excursion fill economics do not reconcile"
            )

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
                raise ProspectiveCapacityReflowForwardExcursionError(
                    "forward excursion path lineage mismatch"
                )

        raw_markouts = option["markouts"]
        assert isinstance(raw_markouts, dict)
        excursions: dict[str, dict[str, object]] = {}

        for horizon_ms in horizons:
            horizon_key = str(horizon_ms)
            aggregate = by_horizon[horizon_key]
            raw_markout = raw_markouts.get(horizon_key)
            if not isinstance(raw_markout, dict):
                raise ProspectiveCapacityReflowForwardExcursionError(
                    "forward excursion horizon lineage is missing"
                )
            status = raw_markout.get("status")
            if status == "missing_path":
                aggregate.missing_path_options += 1
                excursions[horizon_key] = _empty_excursion(
                    status="missing_path",
                    horizon_ms=horizon_ms,
                )
                continue
            if status == "pending":
                aggregate.pending_options += 1
                excursions[horizon_key] = _empty_excursion(
                    status="pending",
                    horizon_ms=horizon_ms,
                )
                continue
            if status == "stale":
                aggregate.stale_options += 1
                excursions[horizon_key] = _empty_excursion(
                    status="stale",
                    horizon_ms=horizon_ms,
                )
                continue
            if status != "settled":
                raise ProspectiveCapacityReflowForwardExcursionError(
                    "forward excursion markout status is invalid"
                )
            if path is None:
                raise ProspectiveCapacityReflowForwardExcursionError(
                    "settled forward markout is missing its path"
                )

            endpoint_ms = _integer(
                raw_markout.get("observed_at_ms"),
                "markout observed_at_ms",
            )
            if endpoint_ms < timestamp_ms:
                raise ProspectiveCapacityReflowForwardExcursionError(
                    "forward excursion endpoint precedes opportunity"
                )
            marks = tuple(
                mark
                for mark in path.marks
                if timestamp_ms <= mark.observed_at_ms <= endpoint_ms
            )
            if not marks or marks[-1].observed_at_ms != endpoint_ms:
                raise ProspectiveCapacityReflowForwardExcursionError(
                    "forward excursion endpoint is absent from path"
                )

            observations = tuple(
                (
                    mark,
                    _mtm(
                        direction=direction,
                        entry_price=entry_price,
                        quantity=quantity,
                        entry_fee=entry_fee,
                        mark_px=mark.mark_px,
                    ),
                )
                for mark in marks
            )
            best_mark, best_pnl = max(
                observations,
                key=lambda item: (
                    item[1],
                    -item[0].observed_at_ms,
                ),
            )
            worst_mark, worst_pnl = min(
                observations,
                key=lambda item: (
                    item[1],
                    item[0].observed_at_ms,
                ),
            )
            ending_pnl = observations[-1][1]
            giveback = best_pnl - ending_pnl
            reversal = best_pnl > ZERO and ending_pnl < ZERO
            excursion = {
                "status": "settled",
                "horizon_ms": horizon_ms,
                "observed_marks": len(marks),
                "best_mark_px": str(best_mark.mark_px),
                "best_observed_at_ms": best_mark.observed_at_ms,
                "time_to_best_ms": (
                    best_mark.observed_at_ms - timestamp_ms
                ),
                "worst_mark_px": str(worst_mark.mark_px),
                "worst_observed_at_ms": worst_mark.observed_at_ms,
                "time_to_worst_ms": (
                    worst_mark.observed_at_ms - timestamp_ms
                ),
                "best_entry_fee_adjusted_mtm_pnl": str(best_pnl),
                "worst_entry_fee_adjusted_mtm_pnl": str(worst_pnl),
                "ending_entry_fee_adjusted_mtm_pnl": str(
                    ending_pnl
                ),
                "peak_to_end_giveback_pnl": str(giveback),
                "positive_peak_to_negative_end": reversal,
            }
            excursions[horizon_key] = excursion

            aggregate.settled_options += 1
            aggregate.observed_mark_count += len(marks)
            aggregate.best_entry_fee_adjusted_mtm_pnl += best_pnl
            aggregate.worst_entry_fee_adjusted_mtm_pnl += worst_pnl
            aggregate.ending_entry_fee_adjusted_mtm_pnl += ending_pnl
            aggregate.peak_to_end_giveback_pnl += giveback
            aggregate.time_to_best_sum_ms += (
                best_mark.observed_at_ms - timestamp_ms
            )
            if best_pnl > ZERO:
                aggregate.positive_peak_options += 1
            if ending_pnl < ZERO:
                aggregate.negative_end_options += 1
            if reversal:
                (
                    aggregate
                    .positive_peak_to_negative_end_options
                ) += 1

        option_excursions.append(
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
                "gross_fill_notional": str(gross_fill_notional),
                "entry_fee": str(entry_fee),
                "excursions": excursions,
            }
        )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "candidate_caused_replacement_observed_path_excursion"
        ),
        "fillable_options": len(options),
        "paths_available": paths_available,
        "paths_missing": paths_missing,
        "horizons_ms": list(horizons),
        "option_excursions": option_excursions,
        "by_horizon": {
            str(horizon_ms): by_horizon[
                str(horizon_ms)
            ].payload()
            for horizon_ms in horizons
        },
        "positive_peak_definition": (
            "best_entry_fee_adjusted_mtm_pnl_gt_zero"
        ),
        "replacement_entry_fills_modeled": True,
        "replacement_forward_markouts_modeled": True,
        "replacement_forward_excursions_modeled": True,
        "replacement_exits_modeled": False,
        "replacement_trades_modeled": False,
        "realized_pnl_modeled": False,
    }


def evaluate_prospective_capacity_reflow_forward_excursion(
    forward_markout: dict[str, object],
    path_store: ContinuousPaperOpeningOpportunityPathStore,
) -> dict[str, object]:
    return prospective_capacity_reflow_forward_excursion_summary(
        forward_markout,
        path_store.iter_paths(),
    )
