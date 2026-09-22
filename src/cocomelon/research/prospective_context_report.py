from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
    ProspectiveEvidenceStore,
    ProspectiveObservation,
    ProspectiveOutcome,
)

ZERO = Decimal("0")
HOUR_MS = 3_600_000
DAY_MS = 86_400_000


class ProspectiveValidationError(RuntimeError):
    pass


class ProspectiveValidationStatus(StrEnum):
    COLLECTING = "collecting"
    DATA_INCOMPLETE = "data_incomplete"
    NOT_QUALIFIED = "not_qualified"
    ELIGIBLE_FOR_CANDIDATE_REVIEW = "eligible_for_candidate_review"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ProspectiveValidationPlan:
    candidate_spec_id: str
    validation_start_ms: int
    validation_end_ms: int
    horizon_ms: int
    anchor_interval_ms: int
    anchor_end_offset_ms: int
    min_capture_coverage: Decimal
    min_settled_trades: int
    stability_blocks: int
    min_block_trades: int
    min_mean_net_return: Decimal = ZERO
    min_block_mean_net_return: Decimal = ZERO
    promotion_eligible: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if len(self.candidate_spec_id) != 64:
            raise ValueError("candidate_spec_id must be a SHA-256 identity")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must be after validation_start_ms")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.anchor_interval_ms <= 0:
            raise ValueError("anchor_interval_ms must be positive")
        if not 0 <= self.anchor_end_offset_ms < self.anchor_interval_ms:
            raise ValueError("anchor_end_offset_ms must fit within anchor interval")
        if (
            not self.min_capture_coverage.is_finite()
            or self.min_capture_coverage <= ZERO
            or self.min_capture_coverage > Decimal("1")
        ):
            raise ValueError("min_capture_coverage must be within (0, 1]")
        if self.min_settled_trades <= 0:
            raise ValueError("min_settled_trades must be positive")
        if self.stability_blocks <= 1:
            raise ValueError("stability_blocks must be greater than one")
        if self.min_block_trades <= 0:
            raise ValueError("min_block_trades must be positive")
        if not self.min_mean_net_return.is_finite():
            raise ValueError("min_mean_net_return must be finite")
        if not self.min_block_mean_net_return.is_finite():
            raise ValueError("min_block_mean_net_return must be finite")
        if self.promotion_eligible:
            raise ValueError("prospective discovery validation is not promotion eligible")
        if self.schema_version != 1:
            raise ValueError("unsupported prospective validation plan schema")

        expected = self.expected_anchor_count
        if expected <= 0:
            raise ValueError("validation window must contain expected anchors")
        if expected % self.stability_blocks != 0:
            raise ValueError("expected anchors must divide evenly into stability blocks")

    @property
    def finalization_not_before_ms(self) -> int:
        return self.validation_end_ms + self.horizon_ms

    @property
    def first_expected_anchor_ms(self) -> int:
        base = self.validation_start_ms - (
            self.validation_start_ms % self.anchor_interval_ms
        )
        candidate = base + self.anchor_end_offset_ms
        if candidate < self.validation_start_ms:
            candidate += self.anchor_interval_ms
        return candidate

    @property
    def expected_anchor_count(self) -> int:
        first = self.first_expected_anchor_ms
        if first >= self.validation_end_ms:
            return 0
        return (
            (self.validation_end_ms - 1 - first) // self.anchor_interval_ms
        ) + 1

    def expected_anchor_count_as_of(self, as_of_ms: int) -> int:
        if as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        first = self.first_expected_anchor_ms
        if as_of_ms < first:
            return 0
        capped = min(as_of_ms, self.validation_end_ms - 1)
        return min(
            self.expected_anchor_count,
            ((capped - first) // self.anchor_interval_ms) + 1,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_spec_id": self.candidate_spec_id,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "horizon_ms": self.horizon_ms,
            "anchor_interval_ms": self.anchor_interval_ms,
            "anchor_end_offset_ms": self.anchor_end_offset_ms,
            "min_capture_coverage": str(self.min_capture_coverage),
            "min_settled_trades": self.min_settled_trades,
            "stability_blocks": self.stability_blocks,
            "min_block_trades": self.min_block_trades,
            "min_mean_net_return": str(self.min_mean_net_return),
            "min_block_mean_net_return": str(self.min_block_mean_net_return),
            "promotion_eligible": self.promotion_eligible,
            "schema_version": self.schema_version,
        }

    @property
    def plan_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()


HYPE_PROSPECTIVE_VALIDATION_V1 = ProspectiveValidationPlan(
    candidate_spec_id=HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.spec_id,
    validation_start_ms=HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.validation_not_before_ms,
    validation_end_ms=(
        HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.validation_not_before_ms
        + 45 * DAY_MS
    ),
    horizon_ms=HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1.horizon_ms,
    anchor_interval_ms=HOUR_MS,
    anchor_end_offset_ms=HOUR_MS - 1,
    min_capture_coverage=Decimal("0.90"),
    min_settled_trades=80,
    stability_blocks=4,
    min_block_trades=15,
)


@dataclass(frozen=True, slots=True)
class ProspectiveValidationBlock:
    block_index: int
    first_anchor_ms: int
    last_anchor_ms: int
    observation_count: int
    effective_trade_count: int
    settled_trade_count: int
    total_net_return: Decimal
    mean_net_return: Decimal | None

    def __post_init__(self) -> None:
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        if self.last_anchor_ms < self.first_anchor_ms:
            raise ValueError("block anchor bounds are invalid")
        for field in ("observation_count", "effective_trade_count", "settled_trade_count"):
            if cast(int, getattr(self, field)) < 0:
                raise ValueError(f"{field} must be non-negative")
        if not self.total_net_return.is_finite():
            raise ValueError("total_net_return must be finite")
        if self.mean_net_return is not None and not self.mean_net_return.is_finite():
            raise ValueError("mean_net_return must be finite when present")

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "first_anchor_ms": self.first_anchor_ms,
            "last_anchor_ms": self.last_anchor_ms,
            "observation_count": self.observation_count,
            "effective_trade_count": self.effective_trade_count,
            "settled_trade_count": self.settled_trade_count,
            "total_net_return": str(self.total_net_return),
            "mean_net_return": (
                None if self.mean_net_return is None else str(self.mean_net_return)
            ),
        }


@dataclass(frozen=True, slots=True)
class ProspectiveValidationReport:
    plan: ProspectiveValidationPlan
    as_of_ms: int
    campaign_id: str
    evidence_digest: str
    expected_anchor_count: int
    expected_anchor_count_to_date: int
    observation_count: int
    observation_count_to_date: int
    missed_anchor_count_to_date: int
    capture_coverage: Decimal
    capture_coverage_to_date: Decimal | None
    raw_match_count: int
    effective_trade_count: int
    occupancy_blocked_count: int
    settled_trade_count: int
    overdue_unsettled_count: int
    total_net_return: Decimal
    mean_net_return: Decimal | None
    positive_net_count: int
    non_positive_net_count: int
    blocks: tuple[ProspectiveValidationBlock, ...]
    status: ProspectiveValidationStatus
    evidence_class: str = PROSPECTIVE_EVIDENCE_CLASS
    promotion_eligible: bool = False
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if len(self.campaign_id) != 64 or len(self.evidence_digest) != 64:
            raise ValueError("campaign_id and evidence_digest must be SHA-256 identities")
        if self.expected_anchor_count <= 0:
            raise ValueError("expected_anchor_count must be positive")
        if self.expected_anchor_count_to_date < 0:
            raise ValueError("expected_anchor_count_to_date must be non-negative")
        if self.expected_anchor_count_to_date > self.expected_anchor_count:
            raise ValueError("expected_anchor_count_to_date cannot exceed full window")
        if self.observation_count < 0 or self.observation_count > self.expected_anchor_count:
            raise ValueError("observation_count must fit expected anchors")
        if (
            self.observation_count_to_date < 0
            or self.observation_count_to_date > self.expected_anchor_count_to_date
        ):
            raise ValueError("observation_count_to_date must fit expected anchors to date")
        if self.missed_anchor_count_to_date != (
            self.expected_anchor_count_to_date - self.observation_count_to_date
        ):
            raise ValueError("missed_anchor_count_to_date must reconcile")
        if (
            not self.capture_coverage.is_finite()
            or self.capture_coverage < ZERO
            or self.capture_coverage > Decimal("1")
        ):
            raise ValueError("capture_coverage must be within [0, 1]")
        if self.expected_anchor_count_to_date == 0:
            if self.capture_coverage_to_date is not None:
                raise ValueError(
                    "capture_coverage_to_date must be None before first expected anchor"
                )
        else:
            if (
                self.capture_coverage_to_date is None
                or not self.capture_coverage_to_date.is_finite()
                or self.capture_coverage_to_date < ZERO
                or self.capture_coverage_to_date > Decimal("1")
            ):
                raise ValueError("capture_coverage_to_date must be within [0, 1]")
            expected_to_date = (
                Decimal(self.observation_count_to_date)
                / Decimal(self.expected_anchor_count_to_date)
            )
            if self.capture_coverage_to_date != expected_to_date:
                raise ValueError("capture_coverage_to_date must match to-date counts")
        for field in (
            "raw_match_count",
            "effective_trade_count",
            "occupancy_blocked_count",
            "settled_trade_count",
            "overdue_unsettled_count",
            "positive_net_count",
            "non_positive_net_count",
        ):
            if cast(int, getattr(self, field)) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.capture_coverage != (
            Decimal(self.observation_count) / Decimal(self.expected_anchor_count)
        ):
            raise ValueError("capture_coverage must match observation count")
        if self.settled_trade_count > self.effective_trade_count:
            raise ValueError("settled_trade_count cannot exceed effective_trade_count")
        if self.positive_net_count + self.non_positive_net_count != self.settled_trade_count:
            raise ValueError("settled return counts must reconcile")
        if not self.total_net_return.is_finite():
            raise ValueError("total_net_return must be finite")
        if self.mean_net_return is not None and not self.mean_net_return.is_finite():
            raise ValueError("mean_net_return must be finite when present")
        if len(self.blocks) != self.plan.stability_blocks:
            raise ValueError("report blocks must match validation plan")
        if self.evidence_class != PROSPECTIVE_EVIDENCE_CLASS:
            raise ValueError("prospective report evidence class is fixed")
        if self.promotion_eligible:
            raise ValueError("prospective report must remain promotion ineligible")
        if self.schema_version != 2:
            raise ValueError("unsupported prospective report schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "plan": self.plan.identity_payload(),
            "plan_id": self.plan.plan_id,
            "as_of_ms": self.as_of_ms,
            "campaign_id": self.campaign_id,
            "evidence_digest": self.evidence_digest,
            "expected_anchor_count": self.expected_anchor_count,
            "expected_anchor_count_to_date": self.expected_anchor_count_to_date,
            "observation_count": self.observation_count,
            "observation_count_to_date": self.observation_count_to_date,
            "missed_anchor_count_to_date": self.missed_anchor_count_to_date,
            "capture_coverage": str(self.capture_coverage),
            "capture_coverage_to_date": (
                None
                if self.capture_coverage_to_date is None
                else str(self.capture_coverage_to_date)
            ),
            "raw_match_count": self.raw_match_count,
            "effective_trade_count": self.effective_trade_count,
            "occupancy_blocked_count": self.occupancy_blocked_count,
            "settled_trade_count": self.settled_trade_count,
            "overdue_unsettled_count": self.overdue_unsettled_count,
            "total_net_return": str(self.total_net_return),
            "mean_net_return": (
                None if self.mean_net_return is None else str(self.mean_net_return)
            ),
            "positive_net_count": self.positive_net_count,
            "non_positive_net_count": self.non_positive_net_count,
            "blocks": tuple(item.to_dict() for item in self.blocks),
            "status": self.status.value,
            "evidence_class": self.evidence_class,
            "promotion_eligible": self.promotion_eligible,
            "schema_version": self.schema_version,
        }

    @property
    def report_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "report_id": self.report_id}


def _validate_anchor(
    observation: ProspectiveObservation,
    plan: ProspectiveValidationPlan,
) -> None:
    if observation.candidate_spec_id != plan.candidate_spec_id:
        raise ProspectiveValidationError("prospective observation candidate mismatch")
    if not plan.validation_start_ms <= observation.anchor_end_ms < plan.validation_end_ms:
        raise ProspectiveValidationError("prospective observation outside fixed window")
    if observation.anchor_end_ms % plan.anchor_interval_ms != plan.anchor_end_offset_ms:
        raise ProspectiveValidationError("prospective observation anchor phase mismatch")


def _window_evidence_digest(
    observations: tuple[ProspectiveObservation, ...],
    outcomes: tuple[ProspectiveOutcome, ...],
    *,
    campaign_id: str,
) -> str:
    payload = {
        "campaign_id": campaign_id,
        "observations": tuple(item.identity_payload() for item in observations),
        "outcomes": tuple(item.identity_payload() for item in outcomes),
    }
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _build_blocks(
    observations: tuple[ProspectiveObservation, ...],
    outcomes_by_observation: dict[str, ProspectiveOutcome],
    *,
    plan: ProspectiveValidationPlan,
) -> tuple[ProspectiveValidationBlock, ...]:
    anchors_per_block = plan.expected_anchor_count // plan.stability_blocks
    first = plan.first_expected_anchor_ms
    blocks: list[ProspectiveValidationBlock] = []

    for block_index in range(plan.stability_blocks):
        first_anchor = first + block_index * anchors_per_block * plan.anchor_interval_ms
        last_anchor = (
            first_anchor
            + (anchors_per_block - 1) * plan.anchor_interval_ms
        )
        block_observations = tuple(
            item
            for item in observations
            if first_anchor <= item.anchor_end_ms <= last_anchor
        )
        effective = tuple(
            item
            for item in block_observations
            if item.effective_direction in {Direction.LONG, Direction.SHORT}
        )
        settled = tuple(
            outcomes_by_observation[item.observation_id]
            for item in effective
            if item.observation_id in outcomes_by_observation
        )
        total = sum((item.net_return for item in settled), ZERO)
        mean = None if not settled else total / Decimal(len(settled))
        blocks.append(
            ProspectiveValidationBlock(
                block_index=block_index + 1,
                first_anchor_ms=first_anchor,
                last_anchor_ms=last_anchor,
                observation_count=len(block_observations),
                effective_trade_count=len(effective),
                settled_trade_count=len(settled),
                total_net_return=total,
                mean_net_return=mean,
            )
        )
    return tuple(blocks)


def build_prospective_validation_report(
    store: ProspectiveEvidenceStore,
    *,
    as_of_ms: int,
    plan: ProspectiveValidationPlan = HYPE_PROSPECTIVE_VALIDATION_V1,
) -> ProspectiveValidationReport:
    if store.spec.spec_id != plan.candidate_spec_id:
        raise ProspectiveValidationError("prospective campaign and validation plan mismatch")
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    all_observations = store.iter_observations()
    if any(item.anchor_end_ms < plan.validation_start_ms for item in all_observations):
        raise ProspectiveValidationError(
            "prospective campaign contains pre-validation observation"
        )
    if any(item.anchor_end_ms >= plan.validation_end_ms for item in all_observations):
        raise ProspectiveValidationError(
            "prospective campaign contains post-validation observation"
        )
    observations = tuple(
        item
        for item in all_observations
        if item.anchor_end_ms < plan.validation_end_ms
    )
    for observed in observations:
        _validate_anchor(observed, plan)
    observations = tuple(
        sorted(observations, key=lambda item: (item.anchor_end_ms, item.observation_id))
    )
    if len({item.anchor_end_ms for item in observations}) != len(observations):
        raise ProspectiveValidationError("duplicate prospective validation anchors")

    observation_by_id = {item.observation_id: item for item in observations}
    all_outcomes = store.iter_outcomes()
    outcomes: list[ProspectiveOutcome] = []
    outcomes_by_observation: dict[str, ProspectiveOutcome] = {}
    for outcome in all_outcomes:
        observation = observation_by_id.get(outcome.observation_id)
        if observation is None:
            if plan.validation_start_ms <= outcome.anchor_end_ms < plan.validation_end_ms:
                raise ProspectiveValidationError("orphan outcome inside validation window")
            continue
        if outcome.candidate_spec_id != plan.candidate_spec_id:
            raise ProspectiveValidationError("prospective outcome candidate mismatch")
        if outcome.observation_id in outcomes_by_observation:
            raise ProspectiveValidationError("duplicate outcome for prospective observation")
        if outcome.anchor_end_ms != observation.anchor_end_ms:
            raise ProspectiveValidationError("outcome anchor does not match observation")
        if outcome.target_end_ms != observation.target_end_ms:
            raise ProspectiveValidationError("outcome target does not match observation")
        if outcome.direction != observation.effective_direction:
            raise ProspectiveValidationError("outcome direction does not match observation")
        outcomes_by_observation[outcome.observation_id] = outcome
        outcomes.append(outcome)
    resolved_outcomes = tuple(
        sorted(outcomes, key=lambda item: (item.anchor_end_ms, item.outcome_id))
    )

    expected_anchor_count = plan.expected_anchor_count
    expected_anchor_count_to_date = plan.expected_anchor_count_as_of(as_of_ms)
    observation_count_to_date = sum(
        1 for item in observations if item.anchor_end_ms <= as_of_ms
    )
    if observation_count_to_date > expected_anchor_count_to_date:
        raise ProspectiveValidationError(
            "prospective observations exceed expected anchors to date"
        )
    missed_anchor_count_to_date = (
        expected_anchor_count_to_date - observation_count_to_date
    )
    capture_coverage = Decimal(len(observations)) / Decimal(expected_anchor_count)
    capture_coverage_to_date = (
        None
        if expected_anchor_count_to_date == 0
        else (
            Decimal(observation_count_to_date)
            / Decimal(expected_anchor_count_to_date)
        )
    )
    raw_matches = tuple(
        item for item in observations if item.raw_direction is not Direction.NO_TRADE
    )
    effective = tuple(
        item
        for item in observations
        if item.effective_direction in {Direction.LONG, Direction.SHORT}
    )
    occupancy_blocked = tuple(
        item
        for item in observations
        if item.occupancy_blocked_by_observation_id is not None
    )
    settled = tuple(
        outcomes_by_observation[item.observation_id]
        for item in effective
        if item.observation_id in outcomes_by_observation
    )
    overdue = tuple(
        item
        for item in effective
        if item.target_end_ms <= as_of_ms
        and item.observation_id not in outcomes_by_observation
    )

    total_net = sum((item.net_return for item in settled), ZERO)
    mean_net = None if not settled else total_net / Decimal(len(settled))
    positive = sum(1 for item in settled if item.net_return > ZERO)
    non_positive = len(settled) - positive
    blocks = _build_blocks(
        observations,
        outcomes_by_observation,
        plan=plan,
    )

    if as_of_ms < plan.finalization_not_before_ms:
        status = ProspectiveValidationStatus.COLLECTING
    else:
        data_complete = (
            capture_coverage >= plan.min_capture_coverage
            and len(settled) >= plan.min_settled_trades
            and not overdue
            and len(settled) == len(effective)
            and all(
                block.settled_trade_count >= plan.min_block_trades
                for block in blocks
            )
        )
        if not data_complete:
            status = ProspectiveValidationStatus.DATA_INCOMPLETE
        else:
            economic_pass = (
                mean_net is not None
                and mean_net > plan.min_mean_net_return
                and all(
                    block.mean_net_return is not None
                    and block.mean_net_return > plan.min_block_mean_net_return
                    for block in blocks
                )
            )
            status = (
                ProspectiveValidationStatus.ELIGIBLE_FOR_CANDIDATE_REVIEW
                if economic_pass
                else ProspectiveValidationStatus.NOT_QUALIFIED
            )

    evidence_digest = _window_evidence_digest(
        observations,
        resolved_outcomes,
        campaign_id=store.manifest.campaign_id,
    )
    return ProspectiveValidationReport(
        plan=plan,
        as_of_ms=as_of_ms,
        campaign_id=store.manifest.campaign_id,
        evidence_digest=evidence_digest,
        expected_anchor_count=expected_anchor_count,
        expected_anchor_count_to_date=expected_anchor_count_to_date,
        observation_count=len(observations),
        observation_count_to_date=observation_count_to_date,
        missed_anchor_count_to_date=missed_anchor_count_to_date,
        capture_coverage=capture_coverage,
        capture_coverage_to_date=capture_coverage_to_date,
        raw_match_count=len(raw_matches),
        effective_trade_count=len(effective),
        occupancy_blocked_count=len(occupancy_blocked),
        settled_trade_count=len(settled),
        overdue_unsettled_count=len(overdue),
        total_net_return=total_net,
        mean_net_return=mean_net,
        positive_net_count=positive,
        non_positive_net_count=non_positive,
        blocks=blocks,
        status=status,
    )
