from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.execution.funding import FUNDING_INTERVAL_MS

ZERO: Final = Decimal("0")


class ProspectiveCapacityReflowRealizedPnlError(RuntimeError):
    pass


@dataclass(slots=True)
class _HorizonSummary:
    horizon_ms: int
    options: int = 0
    simulated_exits: int = 0
    complete_closes: int = 0
    zero_funding_boundary_closes: int = 0
    funding_evidence_required_closes: int = 0
    incomplete_or_missing_exits: int = 0
    exact_realized_pnl_options: int = 0
    exact_realized_pnl: Decimal = ZERO

    def payload(self) -> dict[str, object]:
        return {
            "horizon_ms": self.horizon_ms,
            "options": self.options,
            "simulated_exits": self.simulated_exits,
            "complete_closes": self.complete_closes,
            "zero_funding_boundary_closes": (
                self.zero_funding_boundary_closes
            ),
            "funding_evidence_required_closes": (
                self.funding_evidence_required_closes
            ),
            "incomplete_or_missing_exits": (
                self.incomplete_or_missing_exits
            ),
            "exact_realized_pnl_options": (
                self.exact_realized_pnl_options
            ),
            "exact_realized_pnl": str(self.exact_realized_pnl),
        }


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveCapacityReflowRealizedPnlError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ProspectiveCapacityReflowRealizedPnlError(
            f"{field} must be a decimal"
        ) from exc
    if not result.is_finite():
        raise ProspectiveCapacityReflowRealizedPnlError(
            f"{field} must be finite"
        )
    return result


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveCapacityReflowRealizedPnlError(
            f"{field} must be a non-empty string"
        )
    return value


def _funding_boundaries(
    *,
    opened_at_ms: int,
    closed_at_ms: int,
) -> tuple[int, ...]:
    if opened_at_ms < 0 or closed_at_ms < 0:
        raise ValueError("funding interval timestamps must be non-negative")
    if closed_at_ms < opened_at_ms:
        raise ProspectiveCapacityReflowRealizedPnlError(
            "replacement exit precedes entry"
        )
    first = (
        (opened_at_ms // FUNDING_INTERVAL_MS) + 1
    ) * FUNDING_INTERVAL_MS
    if first > closed_at_ms:
        return ()
    return tuple(
        range(
            first,
            closed_at_ms + 1,
            FUNDING_INTERVAL_MS,
        )
    )


def prospective_capacity_reflow_realized_pnl_summary(
    exit_fill: dict[str, object],
) -> dict[str, object]:
    if exit_fill.get("replacement_entry_fills_modeled") is not True:
        raise ProspectiveCapacityReflowRealizedPnlError(
            "replacement entry fills are not modeled"
        )
    if exit_fill.get("replacement_exit_fills_modeled") is not True:
        raise ProspectiveCapacityReflowRealizedPnlError(
            "replacement exit fills are not modeled"
        )
    if exit_fill.get("cross_horizon_economics_aggregated") is not False:
        raise ProspectiveCapacityReflowRealizedPnlError(
            "replacement exit horizons must remain economically separate"
        )

    raw_horizons = exit_fill.get("horizons_ms")
    if not isinstance(raw_horizons, list) or not raw_horizons:
        raise ProspectiveCapacityReflowRealizedPnlError(
            "replacement exit horizons are invalid"
        )
    horizons = tuple(
        _integer(value, "horizon_ms")
        for value in raw_horizons
    )
    if (
        any(value <= 0 for value in horizons)
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise ProspectiveCapacityReflowRealizedPnlError(
            "replacement exit horizons must be positive and ordered"
        )

    raw_options = exit_fill.get("option_exits")
    if not isinstance(raw_options, list):
        raise ProspectiveCapacityReflowRealizedPnlError(
            "replacement exit option results are invalid"
        )

    by_horizon = {
        str(horizon_ms): _HorizonSummary(horizon_ms=horizon_ms)
        for horizon_ms in horizons
    }
    option_results: list[dict[str, object]] = []
    exact_option_horizons = 0

    for raw_option in raw_options:
        if not isinstance(raw_option, dict):
            raise ProspectiveCapacityReflowRealizedPnlError(
                "replacement exit option is invalid"
            )
        option_id = _text(raw_option.get("option_id"), "option_id")
        opportunity_id = _text(
            raw_option.get("opportunity_id"),
            "opportunity_id",
        )
        entry_ms = _integer(
            raw_option.get("entry_attempt_timestamp_ms"),
            "entry_attempt_timestamp_ms",
        )
        raw_exits = raw_option.get("exits")
        if not isinstance(raw_exits, dict):
            raise ProspectiveCapacityReflowRealizedPnlError(
                "replacement option exits are invalid"
            )

        classified_exits: dict[str, object] = {}
        for horizon_ms in horizons:
            key = str(horizon_ms)
            summary = by_horizon[key]
            summary.options += 1
            raw_exit = raw_exits.get(key)
            if not isinstance(raw_exit, dict):
                summary.incomplete_or_missing_exits += 1
                classified_exits[key] = {
                    "horizon_ms": horizon_ms,
                    "status": "missing_exit_result",
                    "funding_boundary_count": None,
                    "funding_boundaries_ms": [],
                    "exact_realized_pnl": None,
                    "incomplete_reason": "missing_exit_result",
                }
                continue

            status = raw_exit.get("status")
            if status != "simulated":
                summary.incomplete_or_missing_exits += 1
                classified_exits[key] = {
                    "horizon_ms": horizon_ms,
                    "status": status,
                    "funding_boundary_count": None,
                    "funding_boundaries_ms": [],
                    "exact_realized_pnl": None,
                    "incomplete_reason": str(status),
                }
                continue

            summary.simulated_exits += 1
            close_ms = _integer(
                raw_exit.get("attempt_timestamp_ms"),
                "attempt_timestamp_ms",
            )
            boundaries = _funding_boundaries(
                opened_at_ms=entry_ms,
                closed_at_ms=close_ms,
            )
            complete_close = raw_exit.get("complete_close")
            if not isinstance(complete_close, bool):
                raise ProspectiveCapacityReflowRealizedPnlError(
                    "replacement complete-close flag is invalid"
                )
            fee_adjusted_pnl = _decimal(
                raw_exit.get("entry_exit_fee_adjusted_pnl"),
                "entry_exit_fee_adjusted_pnl",
            )

            incomplete_reason: str | None = None
            exact_realized_pnl: str | None = None
            if not complete_close:
                summary.incomplete_or_missing_exits += 1
                incomplete_reason = "position_not_fully_closed"
            else:
                summary.complete_closes += 1
                if boundaries:
                    summary.funding_evidence_required_closes += 1
                    incomplete_reason = "funding_evidence_required"
                else:
                    summary.zero_funding_boundary_closes += 1
                    summary.exact_realized_pnl_options += 1
                    summary.exact_realized_pnl += fee_adjusted_pnl
                    exact_option_horizons += 1
                    exact_realized_pnl = str(fee_adjusted_pnl)

            classified_exits[key] = {
                "horizon_ms": horizon_ms,
                "status": status,
                "funding_boundary_count": len(boundaries),
                "funding_boundaries_ms": list(boundaries),
                "exact_realized_pnl": exact_realized_pnl,
                "incomplete_reason": incomplete_reason,
                "complete_close": complete_close,
            }

        option_results.append(
            {
                "option_id": option_id,
                "opportunity_id": opportunity_id,
                "entry_attempt_timestamp_ms": entry_ms,
                "exits": classified_exits,
            }
        )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "fully_closed_replacement_exit_with_zero_hourly_"
            "funding_boundaries"
        ),
        "funding_interval_ms": FUNDING_INTERVAL_MS,
        "options": len(raw_options),
        "horizons_ms": list(horizons),
        "option_results": option_results,
        "by_horizon": {
            key: value.payload()
            for key, value in by_horizon.items()
        },
        "exact_realized_pnl_option_horizons": exact_option_horizons,
        "exact_realized_pnl_available": exact_option_horizons > 0,
        "funding_evidence_modeled": False,
        "zero_funding_boundary_is_exact_zero_funding": True,
        "cross_horizon_economics_aggregated": False,
        "portfolio_counterfactual_complete": False,
        "strategy_level_realized_pnl_claimed": False,
    }


def evaluate_prospective_capacity_reflow_realized_pnl(
    exit_fill: dict[str, object],
) -> dict[str, object]:
    return prospective_capacity_reflow_realized_pnl_summary(exit_fill)
