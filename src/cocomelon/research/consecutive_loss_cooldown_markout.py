from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)
from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPath,
)

ZERO: Final = Decimal("0")
COOLDOWN_REASON: Final = "consecutive_loss_cooldown"
DEFAULT_HORIZONS_MS: Final = (
    300_000,
    900_000,
    3_600_000,
    21_600_000,
)
MAX_MARK_LAG_MS: Final = 120_000


class ConsecutiveLossCooldownMarkoutError(RuntimeError):
    pass


@dataclass(slots=True)
class _Aggregate:
    horizon_ms: int
    opportunities: int = 0
    settled: int = 0
    pending: int = 0
    stale: int = 0
    missing_path: int = 0
    stops_available: int = 0
    stop_hits: int = 0
    stop_survivors: int = 0
    survivor_positive_after_fee: int = 0
    survivor_negative_after_fee: int = 0
    survivor_flat_after_fee: int = 0
    directional_return_sum: Decimal = ZERO
    fee_adjusted_return_sum: Decimal = ZERO
    survivor_fee_adjusted_return_sum: Decimal = ZERO

    def payload(self) -> dict[str, object]:
        settled = Decimal(self.settled)
        survivors = Decimal(self.stop_survivors)
        return {
            "horizon_ms": self.horizon_ms,
            "opportunities": self.opportunities,
            "settled": self.settled,
            "pending": self.pending,
            "stale": self.stale,
            "missing_path": self.missing_path,
            "stops_available": self.stops_available,
            "stop_hits": self.stop_hits,
            "stop_survivors": self.stop_survivors,
            "survivor_positive_after_fee": (
                self.survivor_positive_after_fee
            ),
            "survivor_negative_after_fee": (
                self.survivor_negative_after_fee
            ),
            "survivor_flat_after_fee": self.survivor_flat_after_fee,
            "mean_directional_return_fraction": (
                None
                if self.settled == 0
                else str(self.directional_return_sum / settled)
            ),
            "mean_fee_adjusted_return_fraction": (
                None
                if self.settled == 0
                else str(self.fee_adjusted_return_sum / settled)
            ),
            "mean_stop_survivor_fee_adjusted_return_fraction": (
                None
                if self.stop_survivors == 0
                else str(
                    self.survivor_fee_adjusted_return_sum
                    / survivors
                )
            ),
        }


def _decimal(
    raw: object,
    *,
    field: str,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ConsecutiveLossCooldownMarkoutError(
            f"{field} must be a decimal"
        ) from exc
    if not value.is_finite():
        raise ConsecutiveLossCooldownMarkoutError(
            f"{field} must be finite"
        )
    if positive and value <= ZERO:
        raise ConsecutiveLossCooldownMarkoutError(
            f"{field} must be positive"
        )
    if nonnegative and value < ZERO:
        raise ConsecutiveLossCooldownMarkoutError(
            f"{field} must be non-negative"
        )
    return value


def _nested_dict(
    raw: object,
    *,
    field: str,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ConsecutiveLossCooldownMarkoutError(
            f"{field} must be an object"
        )
    return raw


def _economics(
    evidence: ContinuousPaperOpeningOpportunityEvidence,
) -> tuple[Decimal, Decimal | None, Decimal]:
    request = _nested_dict(
        evidence.risk_request,
        field="risk_request",
    )
    decision = _nested_dict(
        request.get("strategy_decision"),
        field="strategy_decision",
    )
    costs = _nested_dict(
        request.get("cost_estimate"),
        field="cost_estimate",
    )
    entry = _decimal(
        request.get("entry_reference_price"),
        field="entry_reference_price",
        positive=True,
    )
    raw_stop = decision.get("invalidation_price")
    stop = (
        None
        if raw_stop is None
        else _decimal(
            raw_stop,
            field="invalidation_price",
            positive=True,
        )
    )
    round_trip_fee = _decimal(
        costs.get("round_trip_fee_fraction"),
        field="round_trip_fee_fraction",
        nonnegative=True,
    )
    return entry, stop, round_trip_fee


def _path_map(
    paths: Sequence[ContinuousPaperOpeningOpportunityPath],
) -> dict[str, ContinuousPaperOpeningOpportunityPath]:
    output: dict[str, ContinuousPaperOpeningOpportunityPath] = {}
    for path in paths:
        if path.opportunity_id in output:
            raise ConsecutiveLossCooldownMarkoutError(
                "duplicate opening opportunity path"
            )
        output[path.opportunity_id] = path
    return output


def _directional_return(
    *,
    direction: str,
    entry: Decimal,
    mark: Decimal,
) -> Decimal:
    if direction == "long":
        return (mark - entry) / entry
    if direction == "short":
        return (entry - mark) / entry
    raise ConsecutiveLossCooldownMarkoutError(
        "opportunity direction must be long or short"
    )


def _stop_hit(
    path: ContinuousPaperOpeningOpportunityPath,
    *,
    direction: str,
    stop: Decimal,
    through_ms: int,
) -> bool:
    marks = tuple(
        mark
        for mark in path.marks
        if mark.observed_at_ms <= through_ms
    )
    if direction == "long":
        return any(mark.mark_px <= stop for mark in marks)
    if direction == "short":
        return any(mark.mark_px >= stop for mark in marks)
    raise ConsecutiveLossCooldownMarkoutError(
        "opportunity direction must be long or short"
    )


def consecutive_loss_cooldown_markout_summary(
    records: Sequence[ContinuousPaperOpeningOpportunityEvidence],
    paths: Sequence[ContinuousPaperOpeningOpportunityPath],
    *,
    horizons_ms: tuple[int, ...] = DEFAULT_HORIZONS_MS,
    max_mark_lag_ms: int = MAX_MARK_LAG_MS,
) -> dict[str, object]:
    if (
        not horizons_ms
        or tuple(sorted(set(horizons_ms))) != horizons_ms
        or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for value in horizons_ms
        )
    ):
        raise ValueError(
            "horizons_ms must contain unique increasing positive integers"
        )
    if (
        isinstance(max_mark_lag_ms, bool)
        or not isinstance(max_mark_lag_ms, int)
        or max_mark_lag_ms < 0
    ):
        raise ValueError("max_mark_lag_ms must be non-negative")

    all_records = tuple(records)
    rejected = tuple(
        record
        for record in all_records
        if not record.baseline_risk_approved
    )
    cooldown_only = tuple(
        record
        for record in rejected
        if record.baseline_risk_reason_codes
        == (COOLDOWN_REASON,)
    )
    path_by_id = _path_map(paths)

    aggregates = {
        str(horizon_ms): _Aggregate(
            horizon_ms=horizon_ms,
            opportunities=len(cooldown_only),
        )
        for horizon_ms in horizons_ms
    }
    by_direction = {
        direction: {
            str(horizon_ms): _Aggregate(
                horizon_ms=horizon_ms,
                opportunities=sum(
                    1
                    for record in cooldown_only
                    if record.direction == direction
                ),
            )
            for horizon_ms in horizons_ms
        }
        for direction in ("long", "short")
    }
    option_results: list[dict[str, object]] = []

    for record in cooldown_only:
        if record.direction not in {"long", "short"}:
            raise ConsecutiveLossCooldownMarkoutError(
                "cooldown opportunity direction is invalid"
            )
        entry, stop, round_trip_fee = _economics(record)
        path = path_by_id.get(record.opportunity_id)
        if path is not None and (
            path.market != record.market
            or path.direction != record.direction
            or path.opportunity_timestamp_ms
            != record.opportunity_timestamp_ms
        ):
            raise ConsecutiveLossCooldownMarkoutError(
                "cooldown opportunity path lineage mismatch"
            )

        markouts: dict[str, dict[str, object]] = {}
        for horizon_ms in horizons_ms:
            key = str(horizon_ms)
            aggregate = aggregates[key]
            side_aggregate = by_direction[record.direction][key]
            target_at_ms = (
                record.opportunity_timestamp_ms + horizon_ms
            )

            if path is None:
                aggregate.missing_path += 1
                side_aggregate.missing_path += 1
                markouts[key] = {
                    "status": "missing_path",
                    "target_at_ms": target_at_ms,
                }
                continue
            if horizon_ms > path.max_path_age_ms:
                raise ConsecutLossCooldownMarkoutError(
                    "cooldown horizon exceeds captured path"
                )

            mark = next(
                (
                    item
                    for item in path.marks
                    if item.observed_at_ms >= target_at_ms
                ),
                None,
            )
            if mark is None:
                aggregate.pending += 1
                side_aggregate.pending += 1
                markouts[key] = {
                    "status": "pending",
                    "target_at_ms": target_at_ms,
                }
                continue

            lag_ms = mark.observed_at_ms - target_at_ms
            if lag_ms > max_mark_lag_ms:
                aggregate.stale += 1
                side_aggregate.stale += 1
                markouts[key] = {
                    "status": "stale",
                    "target_at_ms": target_at_ms,
                    "observed_at_ms": mark.observed_at_ms,
                    "observation_lag_ms": lag_ms,
                    "mark_px": str(mark.mark_px),
                }
                continue

            directional_return = _directional_return(
                direction=record.direction,
                entry=entry,
                mark=mark.mark_px,
            )
            fee_adjusted = directional_return - round_trip_fee
            stop_hit: bool | None = None
            if stop is not None:
                stop_hit = _stop_hit(
                    path,
                    direction=record.direction,
                    stop=stop,
                    through_ms=target_at_ms,
                )

            for current in (aggregate, side_aggregate):
                current.settled += 1
                current.directional_return_sum += directional_return
                current.fee_adjusted_return_sum += fee_adjusted
                if stop is not None:
                    current.stops_available += 1
                    if stop_hit:
                        current.stop_hits += 1
                    else:
                        current.stop_survivors += 1
                        current.survivor_fee_adjusted_return_sum += (
                            fee_adjusted
                        )
                        if fee_adjusted > ZERO:
                            current.survivor_positive_after_fee += 1
                        elif fee_adjusted < ZERO:
                            current.survivor_negative_after_fee += 1
                        else:
                            current.survivor_flat_after_fee += 1

            markouts[key] = {
                "status": "settled",
                "target_at_ms": target_at_ms,
                "observed_at_ms": mark.observed_at_ms,
                "observation_lag_ms": lag_ms,
                "mark_px": str(mark.mark_px),
                "directional_return_fraction": str(
                    directional_return
                ),
                "round_trip_fee_fraction": str(round_trip_fee),
                "fee_adjusted_directional_return_fraction": str(
                    fee_adjusted
                ),
                "stop_price": (
                    None if stop is None else str(stop)
                ),
                "stop_hit_before_horizon": stop_hit,
            }

        option_results.append(
            {
                "opportunity_id": record.opportunity_id,
                "timestamp_ms": record.opportunity_timestamp_ms,
                "market": record.market,
                "direction": record.direction,
                "lead_strategy": record.lead_strategy,
                "entry_reference_price": str(entry),
                "stop_price": None if stop is None else str(stop),
                "round_trip_fee_fraction": str(round_trip_fee),
                "markouts": markouts,
            }
        )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "cooldown_only_risk_rejections_observed_forward_path"
        ),
        "cooldown_reason": COOLDOWN_REASON,
        "horizons_ms": list(horizons_ms),
        "max_mark_lag_ms": max_mark_lag_ms,
        "opening_opportunities": len(all_records),
        "risk_rejected_opportunities": len(rejected),
        "cooldown_only_opportunities": len(cooldown_only),
        "other_or_mixed_risk_rejections": (
            len(rejected) - len(cooldown_only)
        ),
        "by_horizon": {
            key: value.payload()
            for key, value in aggregates.items()
        },
        "by_direction": {
            direction: {
                key: value.payload()
                for key, value in horizons.items()
            }
            for direction, horizons in by_direction.items()
        },
        "option_results": option_results,
        "fills_modeled": False,
        "slippage_modeled": False,
        "realized_pnl_modeled": False,
        "replacement_trades_modeled": False,
        "exit_policy_modeled": False,
        "fee_proxy_modeled": True,
        "stop_crossing_observed": True,
        "positive_definition": (
            "original_stop_not_crossed_and_"
            "directional_return_minus_round_trip_fee_gt_zero"
        ),
    }
