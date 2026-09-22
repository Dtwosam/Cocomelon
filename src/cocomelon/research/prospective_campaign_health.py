from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from enum import StrEnum

from cocomelon.research.prospective_context_report import (
    ProspectiveValidationReport,
    ProspectiveValidationStatus,
)

ZERO = Decimal("0")


class ProspectiveCampaignHealthStatus(StrEnum):
    PRE_VALIDATION = "pre_validation"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    IRRECOVERABLE = "irrecoverable"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ProspectiveBlockRecoverability:
    block_index: int
    settled_trade_count: int
    effective_trade_count: int
    remaining_expected_anchors: int
    maximum_possible_settled_trades: int
    required_settled_trades: int
    recoverable: bool

    def __post_init__(self) -> None:
        for field in (
            "block_index",
            "settled_trade_count",
            "effective_trade_count",
            "remaining_expected_anchors",
            "maximum_possible_settled_trades",
            "required_settled_trades",
        ):
            value = getattr(self, field)
            if value < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        if self.settled_trade_count > self.effective_trade_count:
            raise ValueError("settled trades cannot exceed effective trades")
        if self.maximum_possible_settled_trades != (
            self.effective_trade_count + self.remaining_expected_anchors
        ):
            raise ValueError("maximum block trade count must reconcile")
        if self.recoverable != (
            self.maximum_possible_settled_trades >= self.required_settled_trades
        ):
            raise ValueError("block recoverability must match possible trade count")

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "settled_trade_count": self.settled_trade_count,
            "effective_trade_count": self.effective_trade_count,
            "remaining_expected_anchors": self.remaining_expected_anchors,
            "maximum_possible_settled_trades": self.maximum_possible_settled_trades,
            "required_settled_trades": self.required_settled_trades,
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True, slots=True)
class ProspectiveCampaignHealth:
    validation_report_id: str
    plan_id: str
    as_of_ms: int
    status: ProspectiveCampaignHealthStatus
    expected_anchor_count: int
    expected_anchor_count_to_date: int
    observation_count_to_date: int
    remaining_expected_anchors: int
    required_final_observation_count: int
    missed_anchor_budget: int
    missed_anchor_count_to_date: int
    remaining_missed_anchor_budget: int
    maximum_final_observation_count: int
    maximum_final_capture_coverage: Decimal
    effective_trade_count: int
    settled_trade_count: int
    remaining_trade_opportunities_upper_bound: int
    maximum_possible_settled_trades: int
    required_settled_trades: int
    overdue_unsettled_count: int
    block_recoverability: tuple[ProspectiveBlockRecoverability, ...]
    irrecoverable_reasons: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if len(self.validation_report_id) != 64 or len(self.plan_id) != 64:
            raise ValueError("validation_report_id and plan_id must be SHA-256 identities")
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        for field in (
            "expected_anchor_count",
            "expected_anchor_count_to_date",
            "observation_count_to_date",
            "remaining_expected_anchors",
            "required_final_observation_count",
            "missed_anchor_budget",
            "missed_anchor_count_to_date",
            "maximum_final_observation_count",
            "effective_trade_count",
            "settled_trade_count",
            "remaining_trade_opportunities_upper_bound",
            "maximum_possible_settled_trades",
            "required_settled_trades",
            "overdue_unsettled_count",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.remaining_missed_anchor_budget != (
            self.missed_anchor_budget - self.missed_anchor_count_to_date
        ):
            raise ValueError("remaining missed-anchor budget must reconcile")
        if self.remaining_expected_anchors != (
            self.expected_anchor_count - self.expected_anchor_count_to_date
        ):
            raise ValueError("remaining expected anchors must reconcile")
        if self.maximum_final_observation_count != (
            self.observation_count_to_date + self.remaining_expected_anchors
        ):
            raise ValueError("maximum final observation count must reconcile")
        if self.maximum_possible_settled_trades != (
            self.effective_trade_count
            + self.remaining_trade_opportunities_upper_bound
        ):
            raise ValueError("maximum possible settled trades must reconcile")
        if (
            not self.maximum_final_capture_coverage.is_finite()
            or self.maximum_final_capture_coverage < ZERO
            or self.maximum_final_capture_coverage > Decimal("1")
        ):
            raise ValueError("maximum final capture coverage must be within [0, 1]")
        if len(self.block_recoverability) == 0:
            raise ValueError("block recoverability must not be empty")
        if self.schema_version != 1:
            raise ValueError("unsupported prospective campaign health schema")
        if self.status is ProspectiveCampaignHealthStatus.IRRECOVERABLE:
            if not self.irrecoverable_reasons:
                raise ValueError("irrecoverable health requires reasons")
        elif self.irrecoverable_reasons:
            raise ValueError("recoverable health cannot carry irrecoverable reasons")

    @property
    def irrecoverable(self) -> bool:
        return self.status is ProspectiveCampaignHealthStatus.IRRECOVERABLE

    def identity_payload(self) -> dict[str, object]:
        return {
            "validation_report_id": self.validation_report_id,
            "plan_id": self.plan_id,
            "as_of_ms": self.as_of_ms,
            "status": self.status.value,
            "expected_anchor_count": self.expected_anchor_count,
            "expected_anchor_count_to_date": self.expected_anchor_count_to_date,
            "observation_count_to_date": self.observation_count_to_date,
            "remaining_expected_anchors": self.remaining_expected_anchors,
            "required_final_observation_count": self.required_final_observation_count,
            "missed_anchor_budget": self.missed_anchor_budget,
            "missed_anchor_count_to_date": self.missed_anchor_count_to_date,
            "remaining_missed_anchor_budget": self.remaining_missed_anchor_budget,
            "maximum_final_observation_count": self.maximum_final_observation_count,
            "maximum_final_capture_coverage": str(
                self.maximum_final_capture_coverage
            ),
            "effective_trade_count": self.effective_trade_count,
            "settled_trade_count": self.settled_trade_count,
            "remaining_trade_opportunities_upper_bound": (
                self.remaining_trade_opportunities_upper_bound
            ),
            "maximum_possible_settled_trades": self.maximum_possible_settled_trades,
            "required_settled_trades": self.required_settled_trades,
            "overdue_unsettled_count": self.overdue_unsettled_count,
            "block_recoverability": tuple(
                item.to_dict() for item in self.block_recoverability
            ),
            "irrecoverable_reasons": self.irrecoverable_reasons,
            "schema_version": self.schema_version,
        }

    @property
    def health_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "health_id": self.health_id}


def _remaining_block_anchors(
    *,
    as_of_ms: int,
    first_anchor_ms: int,
    last_anchor_ms: int,
    interval_ms: int,
) -> int:
    if as_of_ms < first_anchor_ms:
        return ((last_anchor_ms - first_anchor_ms) // interval_ms) + 1
    if as_of_ms >= last_anchor_ms:
        return 0
    first_remaining = (
        first_anchor_ms
        + (((as_of_ms - first_anchor_ms) // interval_ms) + 1) * interval_ms
    )
    if first_remaining > last_anchor_ms:
        return 0
    return ((last_anchor_ms - first_remaining) // interval_ms) + 1


def build_prospective_campaign_health(
    report: ProspectiveValidationReport,
) -> ProspectiveCampaignHealth:
    plan = report.plan
    required_final_observation_count = int(
        (
            plan.min_capture_coverage * Decimal(report.expected_anchor_count)
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    missed_anchor_budget = (
        report.expected_anchor_count - required_final_observation_count
    )
    remaining_expected_anchors = (
        report.expected_anchor_count - report.expected_anchor_count_to_date
    )
    maximum_final_observation_count = (
        report.observation_count_to_date + remaining_expected_anchors
    )
    maximum_final_capture_coverage = (
        Decimal(maximum_final_observation_count)
        / Decimal(report.expected_anchor_count)
    )

    block_health = tuple(
        ProspectiveBlockRecoverability(
            block_index=block.block_index,
            settled_trade_count=block.settled_trade_count,
            effective_trade_count=block.effective_trade_count,
            remaining_expected_anchors=_remaining_block_anchors(
                as_of_ms=report.as_of_ms,
                first_anchor_ms=block.first_anchor_ms,
                last_anchor_ms=block.last_anchor_ms,
                interval_ms=plan.anchor_interval_ms,
            ),
            maximum_possible_settled_trades=(
                block.effective_trade_count
                + _remaining_block_anchors(
                    as_of_ms=report.as_of_ms,
                    first_anchor_ms=block.first_anchor_ms,
                    last_anchor_ms=block.last_anchor_ms,
                    interval_ms=plan.anchor_interval_ms,
                )
            ),
            required_settled_trades=plan.min_block_trades,
            recoverable=(
                block.effective_trade_count
                + _remaining_block_anchors(
                    as_of_ms=report.as_of_ms,
                    first_anchor_ms=block.first_anchor_ms,
                    last_anchor_ms=block.last_anchor_ms,
                    interval_ms=plan.anchor_interval_ms,
                )
                >= plan.min_block_trades
            ),
        )
        for block in report.blocks
    )

    maximum_possible_settled_trades = (
        report.effective_trade_count + remaining_expected_anchors
    )
    reasons: list[str] = []
    if maximum_final_observation_count < required_final_observation_count:
        reasons.append("capture_floor_unreachable")
    if maximum_possible_settled_trades < plan.min_settled_trades:
        reasons.append("minimum_settled_trade_count_unreachable")
    reasons.extend(
        f"block_{item.block_index}_minimum_trade_count_unreachable"
        for item in block_health
        if not item.recoverable
    )

    if reasons:
        status = ProspectiveCampaignHealthStatus.IRRECOVERABLE
    elif report.as_of_ms < plan.first_expected_anchor_ms:
        status = ProspectiveCampaignHealthStatus.PRE_VALIDATION
    elif report.missed_anchor_count_to_date > 0 or report.overdue_unsettled_count > 0:
        status = ProspectiveCampaignHealthStatus.DEGRADED
    else:
        status = ProspectiveCampaignHealthStatus.HEALTHY

    return ProspectiveCampaignHealth(
        validation_report_id=report.report_id,
        plan_id=plan.plan_id,
        as_of_ms=report.as_of_ms,
        status=status,
        expected_anchor_count=report.expected_anchor_count,
        expected_anchor_count_to_date=report.expected_anchor_count_to_date,
        observation_count_to_date=report.observation_count_to_date,
        remaining_expected_anchors=remaining_expected_anchors,
        required_final_observation_count=required_final_observation_count,
        missed_anchor_budget=missed_anchor_budget,
        missed_anchor_count_to_date=report.missed_anchor_count_to_date,
        remaining_missed_anchor_budget=(
            missed_anchor_budget - report.missed_anchor_count_to_date
        ),
        maximum_final_observation_count=maximum_final_observation_count,
        maximum_final_capture_coverage=maximum_final_capture_coverage,
        effective_trade_count=report.effective_trade_count,
        settled_trade_count=report.settled_trade_count,
        remaining_trade_opportunities_upper_bound=remaining_expected_anchors,
        maximum_possible_settled_trades=maximum_possible_settled_trades,
        required_settled_trades=plan.min_settled_trades,
        overdue_unsettled_count=report.overdue_unsettled_count,
        block_recoverability=block_health,
        irrecoverable_reasons=tuple(reasons),
    )
