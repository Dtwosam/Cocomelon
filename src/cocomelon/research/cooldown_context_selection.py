from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, cast

EXPECTED_COOLDOWN_CANDIDATE_ID: Final = (
    "prospective-consecutive-loss-cooldown-relaxation-v1"
)
COOLDOWN_CONTEXT_SELECTION_SCHEMA_VERSION = 1
COOLDOWN_CONTEXT_SELECTION_POLICY: Final = (
    "fewest_dimensions_then_validation_support_then_robustness_v1"
)


class CooldownContextSelectionError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CooldownContextSelectionError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise CooldownContextSelectionError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CooldownContextSelectionError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CooldownContextSelectionError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise CooldownContextSelectionError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise CooldownContextSelectionError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CooldownContextSelectionError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise CooldownContextSelectionError(f"{field} must be finite")
    return result


def _validate_cooldown_source(summary: dict[str, object]) -> int:
    if summary.get("candidate_id") != EXPECTED_COOLDOWN_CANDIDATE_ID:
        raise CooldownContextSelectionError(
            "cooldown candidate identity is unsupported"
        )
    if (
        summary.get("research_only") is not True
        or summary.get("descriptive_only") is not True
        or summary.get("execution_authority") is not False
        or summary.get("promotion_authority") is not False
        or summary.get("changes_risk_limits") is not False
        or summary.get("forward_markout_only") is not True
        or summary.get("realized_pnl_modeled") is not False
    ):
        raise CooldownContextSelectionError(
            "cooldown source authority or claim scope drift"
        )
    raw_options = summary.get("option_results")
    if not isinstance(raw_options, list):
        raise CooldownContextSelectionError(
            "cooldown option_results must be a list"
        )
    timestamps = [
        _integer(_mapping(item, "cooldown option").get("timestamp_ms"), "timestamp_ms")
        for item in raw_options
    ]
    return max(timestamps, default=0)


def _validate_stability(
    stability: dict[str, object],
) -> tuple[dict[str, object], ...]:
    if _integer(stability.get("schema_version"), "schema_version") != 1:
        raise CooldownContextSelectionError(
            "cooldown context stability schema is unsupported"
        )
    required_true = (
        "lead_strategy_context_required",
        "one_hour_fee_adjusted_execution_economics_required",
        "chronological_holdout_required",
        "leave_one_option_robustness_required",
        "leave_one_market_robustness_required",
        "validation_block_consistency_required",
        "research_only",
        "descriptive_only",
    )
    for field in required_true:
        if _boolean(stability.get(field), field) is not True:
            raise CooldownContextSelectionError(
                "cooldown stability authority or methodology drift"
            )
    required_false = (
        "direction_only_candidates_allowed",
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    )
    for field in required_false:
        if _boolean(stability.get(field), field) is not False:
            raise CooldownContextSelectionError(
                "cooldown stability authority or methodology drift"
            )

    raw_candidates = _sequence(stability.get("candidates"), "candidates")
    stable: list[dict[str, object]] = []
    for raw_value in raw_candidates:
        candidate = _mapping(raw_value, "candidate")
        if _boolean(
            candidate.get("stable_on_validation"),
            "stable_on_validation",
        ) is not True:
            continue
        dimensions = tuple(
            _string(item, "dimension")
            for item in _sequence(candidate.get("dimensions"), "dimensions")
        )
        values = tuple(
            _string(item, "value")
            for item in _sequence(candidate.get("values"), "values")
        )
        if not dimensions or len(dimensions) != len(values):
            raise CooldownContextSelectionError(
                "stable candidate context is invalid"
            )
        if "lead_strategy" not in dimensions:
            raise CooldownContextSelectionError(
                "stable candidate must retain lead_strategy context"
            )
        if dimensions == ("direction",):
            raise CooldownContextSelectionError(
                "direction-only candidate is forbidden"
            )
        for field in (
            "discovery_positive_share",
            "discovery_total_pnl",
            "discovery_mean_return",
            "validation_positive_share",
            "validation_total_pnl",
            "validation_mean_return",
            "validation_leave_one_option_min_pnl",
            "validation_leave_one_market_min_pnl",
        ):
            value = candidate.get(field)
            if value is None:
                raise CooldownContextSelectionError(
                    f"stable candidate missing {field}"
                )
            _decimal(value, field)
        for field in (
            "discovery_rows",
            "discovery_markets",
            "validation_rows",
            "validation_markets",
            "validation_blocks_consistent",
        ):
            _integer(candidate.get(field), field)
        block_rows = _sequence(
            candidate.get("validation_block_rows"),
            "validation_block_rows",
        )
        block_shares = _sequence(
            candidate.get("validation_block_positive_shares"),
            "validation_block_positive_shares",
        )
        block_pnl = _sequence(
            candidate.get("validation_block_pnl"),
            "validation_block_pnl",
        )
        if (
            not block_rows
            or len(block_rows) != len(block_shares)
            or len(block_rows) != len(block_pnl)
        ):
            raise CooldownContextSelectionError(
                "stable candidate block evidence is invalid"
            )
        for item in block_rows:
            _integer(item, "validation_block_row")
        for item in block_shares:
            if item is None:
                raise CooldownContextSelectionError(
                    "stable candidate block share is missing"
                )
            _decimal(item, "validation_block_positive_share")
        for item in block_pnl:
            _decimal(item, "validation_block_pnl")
        if (
            candidate.get("strategy_authority") is not False
            or candidate.get("risk_authority") is not False
            or candidate.get("execution_authority") is not False
        ):
            raise CooldownContextSelectionError(
                "stable candidate authority drift"
            )
        stable.append(candidate)
    return tuple(stable)


def _sort_key(candidate: dict[str, object]) -> tuple[object, ...]:
    dimensions = tuple(
        _string(item, "dimension")
        for item in _sequence(candidate.get("dimensions"), "dimensions")
    )
    values = tuple(
        _string(item, "value")
        for item in _sequence(candidate.get("values"), "values")
    )
    return (
        len(dimensions),
        -_integer(candidate.get("validation_rows"), "validation_rows"),
        -_integer(candidate.get("validation_markets"), "validation_markets"),
        -_decimal(
            candidate.get("validation_positive_share"),
            "validation_positive_share",
        ),
        -_decimal(
            candidate.get("validation_leave_one_market_min_pnl"),
            "validation_leave_one_market_min_pnl",
        ),
        -_decimal(
            candidate.get("validation_leave_one_option_min_pnl"),
            "validation_leave_one_option_min_pnl",
        ),
        -_integer(candidate.get("discovery_rows"), "discovery_rows"),
        dimensions,
        values,
    )


@dataclass(frozen=True, slots=True)
class CooldownContextSelectionRecord:
    cooldown_source_digest: str
    stability_source_digest: str
    source_max_timestamp_ms: int
    settled_1h_outcomes: int
    stable_candidate_count: int
    selected_candidate: dict[str, object] | None
    stable_candidates: tuple[dict[str, object], ...]
    selection_policy: str = COOLDOWN_CONTEXT_SELECTION_POLICY
    schema_version: int = COOLDOWN_CONTEXT_SELECTION_SCHEMA_VERSION

    def identity_payload(self) -> dict[str, object]:
        return {
            "cooldown_source_digest": self.cooldown_source_digest,
            "stability_source_digest": self.stability_source_digest,
            "source_max_timestamp_ms": self.source_max_timestamp_ms,
            "settled_1h_outcomes": self.settled_1h_outcomes,
            "stable_candidate_count": self.stable_candidate_count,
            "selected_candidate": self.selected_candidate,
            "stable_candidates": self.stable_candidates,
            "selection_policy": self.selection_policy,
            "direction_only_candidates_allowed": False,
            "lead_strategy_context_required": True,
            "prospective_freeze_required_before_strategy_use": True,
            "research_only": True,
            "descriptive_only": True,
            "changes_strategy": False,
            "changes_risk_limits": False,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }

    @property
    def source_record_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "source_record_id": self.source_record_id,
        }


def build_cooldown_context_selection_record(
    cooldown_summary: dict[str, object],
    stability_report: dict[str, object],
) -> CooldownContextSelectionRecord:
    source_max_timestamp_ms = _validate_cooldown_source(cooldown_summary)
    stable = _validate_stability(stability_report)
    ordered = tuple(sorted(stable, key=_sort_key))
    selected = None if not ordered else ordered[0]
    return CooldownContextSelectionRecord(
        cooldown_source_digest=_sha256_json(cooldown_summary),
        stability_source_digest=_sha256_json(stability_report),
        source_max_timestamp_ms=source_max_timestamp_ms,
        settled_1h_outcomes=_integer(
            stability_report.get("settled_1h_outcomes"),
            "settled_1h_outcomes",
        ),
        stable_candidate_count=len(ordered),
        selected_candidate=selected,
        stable_candidates=ordered,
    )
