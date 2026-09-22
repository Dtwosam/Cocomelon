from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.research.historical_discovery_freeze import (
    HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1,
)
from cocomelon.research.prospective_context_evidence import (
    ProspectiveCampaignManifest,
)
from cocomelon.research.prospective_context_report import (
    HYPE_PROSPECTIVE_VALIDATION_V1,
)

BLIND_MONITOR_SCHEMA_VERSION = 1
MAX_OPERATIONAL_SOURCE_AGE_MS = 90 * 60 * 1_000


class ProspectiveBlindMonitorError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _load_object(path: str | Path, field: str) -> dict[str, object]:
    resolved = Path(path)
    if not resolved.is_file():
        raise ProspectiveBlindMonitorError(f"{field}_MISSING")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProspectiveBlindMonitorError(f"{field}_INVALID") from exc
    if not isinstance(raw, dict):
        raise ProspectiveBlindMonitorError(f"{field}_INVALID")
    return cast(dict[str, object], raw)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProspectiveBlindMonitorError(f"{field}_INVALID")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveBlindMonitorError(f"{field}_INVALID")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ProspectiveBlindMonitorError(f"{field}_INVALID")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveBlindMonitorError(f"{field}_INVALID")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise ProspectiveBlindMonitorError(f"{field}_INVALID") from exc
    if not resolved.is_finite():
        raise ProspectiveBlindMonitorError(f"{field}_INVALID")
    return resolved


def _verify_identity(
    payload: dict[str, object],
    *,
    identity_field: str,
    error_code: str,
) -> None:
    supplied = _string(payload.get(identity_field), identity_field)
    identity = {
        key: value
        for key, value in payload.items()
        if key != identity_field
    }
    calculated = hashlib.sha256(
        _canonical_json(identity).encode("utf-8")
    ).hexdigest()
    if supplied != calculated:
        raise ProspectiveBlindMonitorError(error_code)


@dataclass(frozen=True, slots=True)
class BlindBlockHealth:
    block_index: int
    settled_trade_count: int
    remaining_expected_anchors: int
    maximum_possible_settled_trades: int
    required_settled_trades: int
    recoverable: bool

    def __post_init__(self) -> None:
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        for field in (
            "settled_trade_count",
            "remaining_expected_anchors",
            "maximum_possible_settled_trades",
            "required_settled_trades",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "settled_trade_count": self.settled_trade_count,
            "remaining_expected_anchors": self.remaining_expected_anchors,
            "maximum_possible_settled_trades": self.maximum_possible_settled_trades,
            "required_settled_trades": self.required_settled_trades,
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True, slots=True)
class ProspectiveBlindMonitor:
    as_of_ms: int
    campaign_health_status: str
    lineage_status: str
    campaign_id: str
    state_artifact_id: str
    current_state_digest: str
    health_id: str
    lineage_receipt_id: str
    expected_anchor_count: int
    expected_anchor_count_to_date: int
    observation_count_to_date: int
    capture_coverage_to_date: str | None
    missed_anchor_count_to_date: int
    missed_anchor_budget: int
    remaining_missed_anchor_budget: int
    remaining_expected_anchors: int
    required_final_observation_count: int
    settled_trade_count: int
    required_settled_trades: int
    maximum_possible_settled_trades: int
    overdue_unsettled_count: int
    block_recoverability: tuple[BlindBlockHealth, ...]
    irrecoverable_reasons: tuple[str, ...]
    interim_economics_redacted: bool = True
    schema_version: int = BLIND_MONITOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.campaign_health_status not in {
            "pre_validation",
            "healthy",
            "degraded",
            "irrecoverable",
        }:
            raise ValueError("unsupported campaign_health_status")
        if self.lineage_status not in {
            "append_only_valid",
            "waiting_for_second_frozen_format_state",
        }:
            raise ValueError("unsupported lineage_status")
        if not self.state_artifact_id.isdigit():
            raise ValueError("state_artifact_id must be numeric")
        for field in (
            "campaign_id",
            "current_state_digest",
            "health_id",
            "lineage_receipt_id",
        ):
            if len(cast(str, getattr(self, field))) != 64:
                raise ValueError(f"{field} must be SHA-256")
        for field in (
            "expected_anchor_count",
            "expected_anchor_count_to_date",
            "observation_count_to_date",
            "missed_anchor_count_to_date",
            "missed_anchor_budget",
            "remaining_expected_anchors",
            "required_final_observation_count",
            "settled_trade_count",
            "required_settled_trades",
            "maximum_possible_settled_trades",
            "overdue_unsettled_count",
        ):
            if cast(int, getattr(self, field)) < 0:
                raise ValueError(f"{field} must be non-negative")
        if not self.interim_economics_redacted:
            raise ValueError("interim economics must remain redacted")
        if self.schema_version != BLIND_MONITOR_SCHEMA_VERSION:
            raise ValueError("unsupported blind monitor schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "as_of_ms": self.as_of_ms,
            "campaign_health_status": self.campaign_health_status,
            "lineage_status": self.lineage_status,
            "campaign_id": self.campaign_id,
            "state_artifact_id": self.state_artifact_id,
            "current_state_digest": self.current_state_digest,
            "health_id": self.health_id,
            "lineage_receipt_id": self.lineage_receipt_id,
            "expected_anchor_count": self.expected_anchor_count,
            "expected_anchor_count_to_date": self.expected_anchor_count_to_date,
            "observation_count_to_date": self.observation_count_to_date,
            "capture_coverage_to_date": self.capture_coverage_to_date,
            "missed_anchor_count_to_date": self.missed_anchor_count_to_date,
            "missed_anchor_budget": self.missed_anchor_budget,
            "remaining_missed_anchor_budget": self.remaining_missed_anchor_budget,
            "remaining_expected_anchors": self.remaining_expected_anchors,
            "required_final_observation_count": self.required_final_observation_count,
            "settled_trade_count": self.settled_trade_count,
            "required_settled_trades": self.required_settled_trades,
            "maximum_possible_settled_trades": self.maximum_possible_settled_trades,
            "overdue_unsettled_count": self.overdue_unsettled_count,
            "block_recoverability": tuple(
                item.to_dict() for item in self.block_recoverability
            ),
            "irrecoverable_reasons": self.irrecoverable_reasons,
            "interim_economics_redacted": self.interim_economics_redacted,
            "schema_version": self.schema_version,
        }

    @property
    def monitor_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "monitor_id": self.monitor_id}


def verify_prospective_hype_blind_monitor_receipt(
    path: str | Path,
) -> ProspectiveBlindMonitor:
    payload = _load_object(path, "BLIND_MONITOR")
    _verify_identity(
        payload,
        identity_field="monitor_id",
        error_code="BLIND_MONITOR_ID_MISMATCH",
    )
    raw_blocks = payload.get("block_recoverability")
    if not isinstance(raw_blocks, list):
        raise ProspectiveBlindMonitorError("BLOCK_RECOVERABILITY_INVALID")
    blocks: list[BlindBlockHealth] = []
    try:
        for index, raw in enumerate(raw_blocks, start=1):
            if not isinstance(raw, dict):
                raise ProspectiveBlindMonitorError("BLOCK_RECOVERABILITY_INVALID")
            block_payload = cast(dict[str, object], raw)
            resolved = BlindBlockHealth(
                block_index=_integer(block_payload.get("block_index"), "BLOCK_INDEX"),
                settled_trade_count=_integer(
                    block_payload.get("settled_trade_count"),
                    "BLOCK_SETTLED_TRADE_COUNT",
                ),
                remaining_expected_anchors=_integer(
                    block_payload.get("remaining_expected_anchors"),
                    "BLOCK_REMAINING_EXPECTED_ANCHORS",
                ),
                maximum_possible_settled_trades=_integer(
                    block_payload.get("maximum_possible_settled_trades"),
                    "BLOCK_MAXIMUM_POSSIBLE_SETTLED_TRADES",
                ),
                required_settled_trades=_integer(
                    block_payload.get("required_settled_trades"),
                    "BLOCK_REQUIRED_SETTLED_TRADES",
                ),
                recoverable=_boolean(
                    block_payload.get("recoverable"),
                    "BLOCK_RECOVERABLE",
                ),
            )
            if resolved.block_index != index:
                raise ProspectiveBlindMonitorError("BLOCK_INDEX_MISMATCH")
            blocks.append(resolved)

        raw_reasons = payload.get("irrecoverable_reasons")
        if not isinstance(raw_reasons, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in raw_reasons
        ):
            raise ProspectiveBlindMonitorError("IRRECOVERABLE_REASONS_INVALID")
        coverage_raw = payload.get("capture_coverage_to_date")
        coverage = (
            None
            if coverage_raw is None
            else _string(coverage_raw, "CAPTURE_COVERAGE_TO_DATE")
        )
        monitor = ProspectiveBlindMonitor(
            as_of_ms=_integer(payload.get("as_of_ms"), "AS_OF_MS"),
            campaign_health_status=_string(
                payload.get("campaign_health_status"),
                "CAMPAIGN_HEALTH_STATUS",
            ),
            lineage_status=_string(payload.get("lineage_status"), "LINEAGE_STATUS"),
            campaign_id=_string(payload.get("campaign_id"), "CAMPAIGN_ID"),
            state_artifact_id=_string(
                payload.get("state_artifact_id"),
                "STATE_ARTIFACT_ID",
            ),
            current_state_digest=_string(
                payload.get("current_state_digest"),
                "CURRENT_STATE_DIGEST",
            ),
            health_id=_string(payload.get("health_id"), "HEALTH_ID"),
            lineage_receipt_id=_string(
                payload.get("lineage_receipt_id"),
                "LINEAGE_RECEIPT_ID",
            ),
            expected_anchor_count=_integer(
                payload.get("expected_anchor_count"),
                "EXPECTED_ANCHOR_COUNT",
            ),
            expected_anchor_count_to_date=_integer(
                payload.get("expected_anchor_count_to_date"),
                "EXPECTED_ANCHOR_COUNT_TO_DATE",
            ),
            observation_count_to_date=_integer(
                payload.get("observation_count_to_date"),
                "OBSERVATION_COUNT_TO_DATE",
            ),
            capture_coverage_to_date=coverage,
            missed_anchor_count_to_date=_integer(
                payload.get("missed_anchor_count_to_date"),
                "MISSED_ANCHOR_COUNT_TO_DATE",
            ),
            missed_anchor_budget=_integer(
                payload.get("missed_anchor_budget"),
                "MISSED_ANCHOR_BUDGET",
            ),
            remaining_missed_anchor_budget=_integer(
                payload.get("remaining_missed_anchor_budget"),
                "REMAINING_MISSED_ANCHOR_BUDGET",
            ),
            remaining_expected_anchors=_integer(
                payload.get("remaining_expected_anchors"),
                "REMAINING_EXPECTED_ANCHORS",
            ),
            required_final_observation_count=_integer(
                payload.get("required_final_observation_count"),
                "REQUIRED_FINAL_OBSERVATION_COUNT",
            ),
            settled_trade_count=_integer(
                payload.get("settled_trade_count"),
                "SETTLED_TRADE_COUNT",
            ),
            required_settled_trades=_integer(
                payload.get("required_settled_trades"),
                "REQUIRED_SETTLED_TRADES",
            ),
            maximum_possible_settled_trades=_integer(
                payload.get("maximum_possible_settled_trades"),
                "MAXIMUM_POSSIBLE_SETTLED_TRADES",
            ),
            overdue_unsettled_count=_integer(
                payload.get("overdue_unsettled_count"),
                "OVERDUE_UNSETTLED_COUNT",
            ),
            block_recoverability=tuple(blocks),
            irrecoverable_reasons=tuple(cast(list[str], raw_reasons)),
            interim_economics_redacted=_boolean(
                payload.get("interim_economics_redacted"),
                "INTERIM_ECONOMICS_REDACTED",
            ),
            schema_version=_integer(payload.get("schema_version"), "SCHEMA_VERSION"),
        )
    except ValueError as exc:
        raise ProspectiveBlindMonitorError("BLIND_MONITOR_INVALID") from exc

    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    expected_campaign_id = ProspectiveCampaignManifest(
        candidate_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        validation_not_before_ms=spec.validation_not_before_ms,
    ).campaign_id
    if monitor.campaign_id != expected_campaign_id:
        raise ProspectiveBlindMonitorError("CAMPAIGN_ID_MISMATCH")
    if monitor.expected_anchor_count != plan.expected_anchor_count:
        raise ProspectiveBlindMonitorError("EXPECTED_ANCHOR_COUNT_MISMATCH")

    required_final = int(
        (
            plan.min_capture_coverage * Decimal(plan.expected_anchor_count)
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    missed_budget = plan.expected_anchor_count - required_final
    if monitor.required_final_observation_count != required_final:
        raise ProspectiveBlindMonitorError("FINAL_OBSERVATION_FLOOR_MISMATCH")
    if monitor.missed_anchor_budget != missed_budget:
        raise ProspectiveBlindMonitorError("MISSED_ANCHOR_BUDGET_MISMATCH")
    if not 0 <= monitor.expected_anchor_count_to_date <= plan.expected_anchor_count:
        raise ProspectiveBlindMonitorError("EXPECTED_ANCHOR_COUNT_TO_DATE_INVALID")
    if not 0 <= monitor.observation_count_to_date <= monitor.expected_anchor_count_to_date:
        raise ProspectiveBlindMonitorError("OBSERVATION_COUNT_TO_DATE_INVALID")
    expected_missed = (
        monitor.expected_anchor_count_to_date - monitor.observation_count_to_date
    )
    if monitor.missed_anchor_count_to_date != expected_missed:
        raise ProspectiveBlindMonitorError("MISSED_ANCHOR_COUNT_MISMATCH")
    if monitor.remaining_expected_anchors != (
        plan.expected_anchor_count - monitor.expected_anchor_count_to_date
    ):
        raise ProspectiveBlindMonitorError("REMAINING_EXPECTED_ANCHORS_MISMATCH")
    if monitor.remaining_missed_anchor_budget != max(
        0,
        missed_budget - expected_missed,
    ):
        raise ProspectiveBlindMonitorError("REMAINING_MISSED_BUDGET_MISMATCH")
    if monitor.expected_anchor_count_to_date == 0:
        if monitor.capture_coverage_to_date is not None:
            raise ProspectiveBlindMonitorError("CAPTURE_COVERAGE_TO_DATE_MISMATCH")
    else:
        expected_coverage = str(
            Decimal(monitor.observation_count_to_date)
            / Decimal(monitor.expected_anchor_count_to_date)
        )
        if monitor.capture_coverage_to_date != expected_coverage:
            raise ProspectiveBlindMonitorError("CAPTURE_COVERAGE_TO_DATE_MISMATCH")
    if monitor.required_settled_trades != plan.min_settled_trades:
        raise ProspectiveBlindMonitorError("REQUIRED_SETTLED_TRADES_MISMATCH")
    if len(monitor.block_recoverability) != plan.stability_blocks:
        raise ProspectiveBlindMonitorError("BLOCK_RECOVERABILITY_INVALID")
    for block in monitor.block_recoverability:
        if block.required_settled_trades != plan.min_block_trades:
            raise ProspectiveBlindMonitorError("BLOCK_SETTLED_FLOOR_MISMATCH")
        if block.maximum_possible_settled_trades < block.settled_trade_count:
            raise ProspectiveBlindMonitorError("BLOCK_MAXIMUM_SETTLED_INVALID")
        if block.recoverable != (
            block.maximum_possible_settled_trades >= block.required_settled_trades
        ):
            raise ProspectiveBlindMonitorError("BLOCK_RECOVERABILITY_MISMATCH")
    return monitor


def _validate_health(payload: dict[str, object]) -> None:
    _verify_identity(
        payload,
        identity_field="health_id",
        error_code="HEALTH_ID_MISMATCH",
    )
    plan = HYPE_PROSPECTIVE_VALIDATION_V1
    if _string(payload.get("plan_id"), "HEALTH_PLAN_ID") != plan.plan_id:
        raise ProspectiveBlindMonitorError("HEALTH_PLAN_ID_MISMATCH")
    if _integer(payload.get("schema_version"), "HEALTH_SCHEMA_VERSION") != 1:
        raise ProspectiveBlindMonitorError("HEALTH_SCHEMA_UNSUPPORTED")

    expected = _integer(payload.get("expected_anchor_count"), "EXPECTED_ANCHOR_COUNT")
    if expected != plan.expected_anchor_count:
        raise ProspectiveBlindMonitorError("EXPECTED_ANCHOR_COUNT_MISMATCH")
    expected_to_date = _integer(
        payload.get("expected_anchor_count_to_date"),
        "EXPECTED_ANCHOR_COUNT_TO_DATE",
    )
    as_of_ms = _integer(payload.get("as_of_ms"), "HEALTH_AS_OF_MS")
    if expected_to_date != plan.expected_anchor_count_as_of(as_of_ms):
        raise ProspectiveBlindMonitorError("EXPECTED_ANCHORS_TO_DATE_MISMATCH")
    observed = _integer(
        payload.get("observation_count_to_date"),
        "OBSERVATION_COUNT_TO_DATE",
    )
    missed = _integer(
        payload.get("missed_anchor_count_to_date"),
        "MISSED_ANCHOR_COUNT_TO_DATE",
    )
    if observed + missed != expected_to_date:
        raise ProspectiveBlindMonitorError("CAPTURE_COUNT_RECONCILIATION_FAILED")

    required = int(
        (
            plan.min_capture_coverage * Decimal(expected)
        ).to_integral_value(rounding=ROUND_CEILING)
    )
    if _integer(
        payload.get("required_final_observation_count"),
        "REQUIRED_FINAL_OBSERVATION_COUNT",
    ) != required:
        raise ProspectiveBlindMonitorError("REQUIRED_CAPTURE_FLOOR_MISMATCH")
    missed_budget = expected - required
    if _integer(payload.get("missed_anchor_budget"), "MISSED_ANCHOR_BUDGET") != missed_budget:
        raise ProspectiveBlindMonitorError("MISSED_ANCHOR_BUDGET_MISMATCH")
    if _integer(
        payload.get("remaining_missed_anchor_budget"),
        "REMAINING_MISSED_ANCHOR_BUDGET",
    ) != missed_budget - missed:
        raise ProspectiveBlindMonitorError("REMAINING_MISS_BUDGET_MISMATCH")

    remaining = _integer(
        payload.get("remaining_expected_anchors"),
        "REMAINING_EXPECTED_ANCHORS",
    )
    if remaining != expected - expected_to_date:
        raise ProspectiveBlindMonitorError("REMAINING_ANCHOR_COUNT_MISMATCH")
    maximum_observations = _integer(
        payload.get("maximum_final_observation_count"),
        "MAXIMUM_FINAL_OBSERVATION_COUNT",
    )
    if maximum_observations != observed + remaining:
        raise ProspectiveBlindMonitorError("MAXIMUM_OBSERVATION_COUNT_MISMATCH")
    maximum_capture = _decimal(
        payload.get("maximum_final_capture_coverage"),
        "MAXIMUM_FINAL_CAPTURE_COVERAGE",
    )
    if maximum_capture != Decimal(maximum_observations) / Decimal(expected):
        raise ProspectiveBlindMonitorError("MAXIMUM_CAPTURE_COVERAGE_MISMATCH")
    if _integer(
        payload.get("remaining_trade_opportunities_upper_bound"),
        "REMAINING_TRADE_OPPORTUNITIES_UPPER_BOUND",
    ) != remaining:
        raise ProspectiveBlindMonitorError("REMAINING_TRADE_BOUND_MISMATCH")

    effective = _integer(payload.get("effective_trade_count"), "EFFECTIVE_TRADE_COUNT")
    maximum_settled = _integer(
        payload.get("maximum_possible_settled_trades"),
        "MAXIMUM_POSSIBLE_SETTLED_TRADES",
    )
    if maximum_settled != effective + remaining:
        raise ProspectiveBlindMonitorError("MAXIMUM_SETTLED_COUNT_MISMATCH")
    if _integer(
        payload.get("required_settled_trades"),
        "REQUIRED_SETTLED_TRADES",
    ) != plan.min_settled_trades:
        raise ProspectiveBlindMonitorError("REQUIRED_SETTLED_TRADES_MISMATCH")
    settled = _integer(payload.get("settled_trade_count"), "SETTLED_TRADE_COUNT")
    overdue = _integer(
        payload.get("overdue_unsettled_count"),
        "OVERDUE_UNSETTLED_COUNT",
    )
    if settled > effective:
        raise ProspectiveBlindMonitorError("SETTLED_TRADE_COUNT_EXCEEDS_EFFECTIVE")
    if overdue > effective - settled:
        raise ProspectiveBlindMonitorError("OVERDUE_UNSETTLED_COUNT_INVALID")

    raw_blocks = payload.get("block_recoverability")
    if not isinstance(raw_blocks, list) or len(raw_blocks) != plan.stability_blocks:
        raise ProspectiveBlindMonitorError("BLOCK_RECOVERABILITY_INVALID")
    for index, raw in enumerate(raw_blocks, start=1):
        if not isinstance(raw, dict):
            raise ProspectiveBlindMonitorError("BLOCK_RECOVERABILITY_INVALID")
        block = cast(dict[str, object], raw)
        if _integer(block.get("block_index"), "BLOCK_INDEX") != index:
            raise ProspectiveBlindMonitorError("BLOCK_INDEX_MISMATCH")
        if _integer(
            block.get("required_settled_trades"),
            "BLOCK_REQUIRED_SETTLED_TRADES",
        ) != plan.min_block_trades:
            raise ProspectiveBlindMonitorError("BLOCK_SETTLED_FLOOR_MISMATCH")
        block_effective = _integer(
            block.get("effective_trade_count"),
            "BLOCK_EFFECTIVE_TRADE_COUNT",
        )
        block_remaining = _integer(
            block.get("remaining_expected_anchors"),
            "BLOCK_REMAINING_EXPECTED_ANCHORS",
        )
        block_maximum = _integer(
            block.get("maximum_possible_settled_trades"),
            "BLOCK_MAXIMUM_POSSIBLE_SETTLED_TRADES",
        )
        if block_maximum != block_effective + block_remaining:
            raise ProspectiveBlindMonitorError("BLOCK_MAXIMUM_SETTLED_MISMATCH")
        recoverable = _boolean(block.get("recoverable"), "BLOCK_RECOVERABLE")
        if recoverable != (block_maximum >= plan.min_block_trades):
            raise ProspectiveBlindMonitorError("BLOCK_RECOVERABILITY_MISMATCH")

    reasons = payload.get("irrecoverable_reasons")
    if not isinstance(reasons, list) or any(
        not isinstance(item, str) or not item.strip() for item in reasons
    ):
        raise ProspectiveBlindMonitorError("IRRECOVERABLE_REASONS_INVALID")
    status = _string(payload.get("status"), "HEALTH_STATUS")
    if reasons:
        expected_status = "irrecoverable"
    elif as_of_ms < plan.first_expected_anchor_ms:
        expected_status = "pre_validation"
    elif missed > 0 or overdue > 0:
        expected_status = "degraded"
    else:
        expected_status = "healthy"
    if status != expected_status:
        raise ProspectiveBlindMonitorError("HEALTH_STATUS_MISMATCH")


def _validate_lineage(
    payload: dict[str, object],
    *,
    expected_state_artifact_id: str,
) -> None:
    _verify_identity(
        payload,
        identity_field="receipt_id",
        error_code="LINEAGE_RECEIPT_ID_MISMATCH",
    )
    current_id = _string(payload.get("current_artifact_id"), "CURRENT_ARTIFACT_ID")
    if not current_id.isdigit():
        raise ProspectiveBlindMonitorError("CURRENT_ARTIFACT_ID_INVALID")
    if current_id != expected_state_artifact_id:
        raise ProspectiveBlindMonitorError("LINEAGE_STATE_ARTIFACT_MISMATCH")
    status = _string(payload.get("lineage_status"), "LINEAGE_STATUS")
    if status not in {
        "append_only_valid",
        "waiting_for_second_frozen_format_state",
    }:
        raise ProspectiveBlindMonitorError("LINEAGE_STATUS_INVALID")

    spec = HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1
    expected_campaign_id = ProspectiveCampaignManifest(
        candidate_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        validation_not_before_ms=spec.validation_not_before_ms,
    ).campaign_id
    if _string(payload.get("campaign_id"), "CAMPAIGN_ID") != expected_campaign_id:
        raise ProspectiveBlindMonitorError("CAMPAIGN_ID_MISMATCH")
    for field in (
        "current_state_digest",
        "runtime_attestation_id",
        "control_plane_id",
    ):
        if len(_string(payload.get(field), field.upper())) != 64:
            raise ProspectiveBlindMonitorError(f"{field.upper()}_INVALID")


def _validate_operational_source_freshness(
    health: dict[str, object],
    lineage: dict[str, object],
    *,
    audited_at_ms: int,
    max_source_age_ms: int,
) -> None:
    if audited_at_ms < 0:
        raise ValueError("audited_at_ms must be non-negative")
    if max_source_age_ms <= 0:
        raise ValueError("max_source_age_ms must be positive")

    health_as_of_ms = _integer(health.get("as_of_ms"), "HEALTH_AS_OF_MS")
    lineage_as_of_ms = _integer(
        lineage.get("current_audited_at_ms"),
        "LINEAGE_AUDITED_AT_MS",
    )
    for source_name, source_time_ms in (
        ("HEALTH", health_as_of_ms),
        ("LINEAGE", lineage_as_of_ms),
    ):
        if source_time_ms > audited_at_ms:
            raise ProspectiveBlindMonitorError(
                f"{source_name}_SOURCE_TIME_AFTER_AUDIT"
            )
        if audited_at_ms - source_time_ms > max_source_age_ms:
            raise ProspectiveBlindMonitorError(
                f"{source_name}_ARTIFACT_STALE"
            )


def build_prospective_hype_blind_monitor(
    health_path: str | Path,
    lineage_path: str | Path,
    *,
    expected_state_artifact_id: str,
    audited_at_ms: int | None = None,
    max_source_age_ms: int = MAX_OPERATIONAL_SOURCE_AGE_MS,
) -> ProspectiveBlindMonitor:
    if not expected_state_artifact_id.isdigit():
        raise ValueError("expected_state_artifact_id must be numeric")

    health = _load_object(health_path, "HEALTH_ARTIFACT")
    lineage = _load_object(lineage_path, "LINEAGE_ARTIFACT")
    _validate_health(health)
    _validate_lineage(
        lineage,
        expected_state_artifact_id=expected_state_artifact_id,
    )
    if audited_at_ms is not None:
        _validate_operational_source_freshness(
            health,
            lineage,
            audited_at_ms=audited_at_ms,
            max_source_age_ms=max_source_age_ms,
        )

    expected_to_date = _integer(
        health.get("expected_anchor_count_to_date"),
        "EXPECTED_ANCHOR_COUNT_TO_DATE",
    )
    observed = _integer(
        health.get("observation_count_to_date"),
        "OBSERVATION_COUNT_TO_DATE",
    )
    coverage = (
        None
        if expected_to_date == 0
        else str(Decimal(observed) / Decimal(expected_to_date))
    )

    raw_blocks = cast(list[object], health["block_recoverability"])
    blocks = tuple(
        BlindBlockHealth(
            block_index=_integer(cast(dict[str, object], raw).get("block_index"), "BLOCK_INDEX"),
            settled_trade_count=_integer(
                cast(dict[str, object], raw).get("settled_trade_count"),
                "BLOCK_SETTLED_TRADE_COUNT",
            ),
            remaining_expected_anchors=_integer(
                cast(dict[str, object], raw).get("remaining_expected_anchors"),
                "BLOCK_REMAINING_EXPECTED_ANCHORS",
            ),
            maximum_possible_settled_trades=_integer(
                cast(dict[str, object], raw).get("maximum_possible_settled_trades"),
                "BLOCK_MAXIMUM_POSSIBLE_SETTLED_TRADES",
            ),
            required_settled_trades=_integer(
                cast(dict[str, object], raw).get("required_settled_trades"),
                "BLOCK_REQUIRED_SETTLED_TRADES",
            ),
            recoverable=_boolean(
                cast(dict[str, object], raw).get("recoverable"),
                "BLOCK_RECOVERABLE",
            ),
        )
        for raw in raw_blocks
    )
    reasons = tuple(
        cast(str, item)
        for item in cast(list[object], health["irrecoverable_reasons"])
    )

    return ProspectiveBlindMonitor(
        as_of_ms=_integer(health.get("as_of_ms"), "HEALTH_AS_OF_MS"),
        campaign_health_status=_string(health.get("status"), "HEALTH_STATUS"),
        lineage_status=_string(lineage.get("lineage_status"), "LINEAGE_STATUS"),
        campaign_id=_string(lineage.get("campaign_id"), "CAMPAIGN_ID"),
        state_artifact_id=expected_state_artifact_id,
        current_state_digest=_string(
            lineage.get("current_state_digest"),
            "CURRENT_STATE_DIGEST",
        ),
        health_id=_string(health.get("health_id"), "HEALTH_ID"),
        lineage_receipt_id=_string(lineage.get("receipt_id"), "LINEAGE_RECEIPT_ID"),
        expected_anchor_count=_integer(
            health.get("expected_anchor_count"),
            "EXPECTED_ANCHOR_COUNT",
        ),
        expected_anchor_count_to_date=expected_to_date,
        observation_count_to_date=observed,
        capture_coverage_to_date=coverage,
        missed_anchor_count_to_date=_integer(
            health.get("missed_anchor_count_to_date"),
            "MISSED_ANCHOR_COUNT_TO_DATE",
        ),
        missed_anchor_budget=_integer(
            health.get("missed_anchor_budget"),
            "MISSED_ANCHOR_BUDGET",
        ),
        remaining_missed_anchor_budget=_integer(
            health.get("remaining_missed_anchor_budget"),
            "REMAINING_MISSED_ANCHOR_BUDGET",
        ),
        remaining_expected_anchors=_integer(
            health.get("remaining_expected_anchors"),
            "REMAINING_EXPECTED_ANCHORS",
        ),
        required_final_observation_count=_integer(
            health.get("required_final_observation_count"),
            "REQUIRED_FINAL_OBSERVATION_COUNT",
        ),
        settled_trade_count=_integer(
            health.get("settled_trade_count"),
            "SETTLED_TRADE_COUNT",
        ),
        required_settled_trades=_integer(
            health.get("required_settled_trades"),
            "REQUIRED_SETTLED_TRADES",
        ),
        maximum_possible_settled_trades=_integer(
            health.get("maximum_possible_settled_trades"),
            "MAXIMUM_POSSIBLE_SETTLED_TRADES",
        ),
        overdue_unsettled_count=_integer(
            health.get("overdue_unsettled_count"),
            "OVERDUE_UNSETTLED_COUNT",
        ),
        block_recoverability=blocks,
        irrecoverable_reasons=reasons,
    )
