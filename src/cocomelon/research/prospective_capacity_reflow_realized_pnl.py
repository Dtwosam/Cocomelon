from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.execution.funding import (
    FUNDING_INTERVAL_MS,
    funding_cash_delta,
)
from cocomelon.research.continuous_paper_replacement_funding import (
    ContinuousPaperReplacementFundingStore,
    ReplacementFundingBoundaryEvidence,
)

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
    funding_evidence_complete_closes: int = 0
    funding_evidence_missing_closes: int = 0
    incomplete_or_missing_exits: int = 0
    exact_realized_pnl_options: int = 0
    funding_cash_pnl: Decimal = ZERO
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
            "funding_evidence_complete_closes": (
                self.funding_evidence_complete_closes
            ),
            "funding_evidence_missing_closes": (
                self.funding_evidence_missing_closes
            ),
            "incomplete_or_missing_exits": (
                self.incomplete_or_missing_exits
            ),
            "exact_realized_pnl_options": (
                self.exact_realized_pnl_options
            ),
            "funding_cash_pnl": str(self.funding_cash_pnl),
            "exact_realized_pnl": str(self.exact_realized_pnl),
        }


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProspectiveCapacityReflowRealizedPnlError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(
    value: object,
    field: str,
    *,
    positive: bool = False,
) -> Decimal:
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
    if positive and result <= ZERO:
        raise ProspectiveCapacityReflowRealizedPnlError(
            f"{field} must be positive"
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


def _funding_index(
    records: tuple[ReplacementFundingBoundaryEvidence, ...],
) -> dict[tuple[str, int], ReplacementFundingBoundaryEvidence]:
    output: dict[
        tuple[str, int],
        ReplacementFundingBoundaryEvidence,
    ] = {}
    for record in records:
        key = (record.market, record.boundary_ms)
        if key in output:
            raise ProspectiveCapacityReflowRealizedPnlError(
                "duplicate replacement funding evidence"
            )
        output[key] = record
    return output


def prospective_capacity_reflow_realized_pnl_summary(
    exit_fill: dict[str, object],
    funding_records: tuple[
        ReplacementFundingBoundaryEvidence,
        ...,
    ] = (),
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

    funding = _funding_index(funding_records)
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
        market = _text(
            raw_option.get("opportunity_market"),
            "opportunity_market",
        )
        direction = _text(
            raw_option.get("opportunity_direction"),
            "opportunity_direction",
        )
        if direction not in {"long", "short"}:
            raise ProspectiveCapacityReflowRealizedPnlError(
                "replacement direction is invalid"
            )
        entry_quantity = _decimal(
            raw_option.get("entry_quantity"),
            "entry_quantity",
            positive=True,
        )
        signed_quantity = (
            entry_quantity
            if direction == "long"
            else -entry_quantity
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
                    "funding_evidence_count": 0,
                    "missing_funding_boundaries_ms": [],
                    "funding_cash_pnl": None,
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
                    "funding_evidence_count": 0,
                    "missing_funding_boundaries_ms": [],
                    "funding_cash_pnl": None,
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

            funding_cash = ZERO
            funding_evidence_count = 0
            missing_boundaries: list[int] = []
            incomplete_reason: str | None = None
            exact_realized_pnl: str | None = None
            funding_pnl: str | None = None

            if not complete_close:
                summary.incomplete_or_missing_exits += 1
                incomplete_reason = "position_not_fully_closed"
            else:
                summary.complete_closes += 1
                if not boundaries:
                    summary.zero_funding_boundary_closes += 1
                    summary.exact_realized_pnl_options += 1
                    summary.exact_realized_pnl += fee_adjusted_pnl
                    exact_option_horizons += 1
                    funding_pnl = str(ZERO)
                    exact_realized_pnl = str(fee_adjusted_pnl)
                else:
                    summary.funding_evidence_required_closes += 1
                    for boundary_ms in boundaries:
                        evidence = funding.get((market, boundary_ms))
                        if evidence is None:
                            missing_boundaries.append(boundary_ms)
                            continue
                        funding_evidence_count += 1
                        funding_cash += funding_cash_delta(
                            signed_quantity,
                            evidence.oracle_px,
                            evidence.funding_rate,
                        )

                    if missing_boundaries:
                        summary.funding_evidence_missing_closes += 1
                        incomplete_reason = "funding_evidence_required"
                    else:
                        summary.funding_evidence_complete_closes += 1
                        summary.exact_realized_pnl_options += 1
                        summary.funding_cash_pnl += funding_cash
                        total = fee_adjusted_pnl + funding_cash
                        summary.exact_realized_pnl += total
                        exact_option_horizons += 1
                        funding_pnl = str(funding_cash)
                        exact_realized_pnl = str(total)

            classified_exits[key] = {
                "horizon_ms": horizon_ms,
                "status": status,
                "funding_boundary_count": len(boundaries),
                "funding_boundaries_ms": list(boundaries),
                "funding_evidence_count": funding_evidence_count,
                "missing_funding_boundaries_ms": missing_boundaries,
                "funding_cash_pnl": funding_pnl,
                "exact_realized_pnl": exact_realized_pnl,
                "incomplete_reason": incomplete_reason,
                "complete_close": complete_close,
            }

        option_results.append(
            {
                "option_id": option_id,
                "opportunity_id": opportunity_id,
                "opportunity_market": market,
                "opportunity_direction": direction,
                "entry_quantity": str(entry_quantity),
                "entry_attempt_timestamp_ms": entry_ms,
                "exits": classified_exits,
            }
        )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "fully_closed_replacement_exit_with_complete_hourly_"
            "funding_evidence"
        ),
        "funding_interval_ms": FUNDING_INTERVAL_MS,
        "funding_evidence_records": len(funding_records),
        "options": len(raw_options),
        "horizons_ms": list(horizons),
        "option_results": option_results,
        "by_horizon": {
            key: value.payload()
            for key, value in by_horizon.items()
        },
        "exact_realized_pnl_option_horizons": exact_option_horizons,
        "exact_realized_pnl_available": exact_option_horizons > 0,
        "funding_evidence_modeled": True,
        "zero_funding_boundary_is_exact_zero_funding": True,
        "cross_horizon_economics_aggregated": False,
        "portfolio_counterfactual_complete": False,
        "strategy_level_realized_pnl_claimed": False,
    }


def evaluate_prospective_capacity_reflow_realized_pnl(
    exit_fill: dict[str, object],
    funding_store: ContinuousPaperReplacementFundingStore,
) -> dict[str, object]:
    return prospective_capacity_reflow_realized_pnl_summary(
        exit_fill,
        funding_store.iter_records(),
    )
