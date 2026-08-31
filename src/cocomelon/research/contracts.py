from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

SIX_HOURS_MS = 21_600_000


class ResearchCandidateState(StrEnum):
    DRAFT = "draft"
    RESEARCHING = "researching"
    REJECTED_OPERATIONAL = "rejected_operational"
    REJECTED_CONTAMINATION = "rejected_contamination"
    REJECTED_FUTILITY = "rejected_futility"
    RESEARCH_PROMISING = "research_promising"
    FROZEN_CHALLENGER = "frozen_challenger"
    VALIDATING = "validating"
    VALIDATED_EDGE = "validated_edge"
    NO_EDGE = "no_edge"


class ResearchCheckpointState(StrEnum):
    INSUFFICIENT_TRADES = "insufficient_trades"
    CONTINUE = "continue"
    RESEARCH_PROMISING = "research_promising"
    REJECT_FUTILITY = "reject_futility"


@dataclass(frozen=True, slots=True, order=True)
class TimeInterval:
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError("start_ms must be non-negative")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")


def intervals_overlap(left: TimeInterval, right: TimeInterval) -> bool:
    return left.start_ms < right.end_ms and right.start_ms < left.end_ms


def normalize_intervals(intervals: Iterable[TimeInterval]) -> tuple[TimeInterval, ...]:
    ordered = sorted(intervals)
    if not ordered:
        return ()

    merged: list[TimeInterval] = [ordered[0]]
    for interval in ordered[1:]:
        current = merged[-1]
        if interval.start_ms <= current.end_ms:
            merged[-1] = TimeInterval(current.start_ms, max(current.end_ms, interval.end_ms))
        else:
            merged.append(interval)
    return tuple(merged)


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_digest(value: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError("config_digest must be a lowercase 64-character sha256 hex digest")


def _canonical_json_object(value: str, field: str) -> str:
    _require_nonempty(value, field)
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON") from exc
    if not isinstance(decoded, dict) or not decoded:
        raise ValueError(f"{field} must be a non-empty JSON object")
    return json.dumps(
        decoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_strings(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if any(not value.strip() for value in values):
        raise ValueError(f"{field} values must not be empty")
    return tuple(sorted(set(values)))


def _interval_is_covered(
    interval: TimeInterval,
    covering_intervals: tuple[TimeInterval, ...],
) -> bool:
    return any(
        covering.start_ms <= interval.start_ms and covering.end_ms >= interval.end_ms
        for covering in covering_intervals
    )


@dataclass(frozen=True, slots=True)
class ResearchCandidateManifest:
    candidate_id: str
    family_id: str
    parent_candidate_id: str | None
    ancestor_candidate_ids: tuple[str, ...]
    config_digest: str
    code_revision: str
    execution_config_json: str
    risk_config_json: str
    state: ResearchCandidateState
    first_observation_ms: int | None
    last_observation_ms: int | None
    source_provenance_ids: tuple[str, ...]
    local_touched_intervals: tuple[TimeInterval, ...]
    effective_touched_intervals: tuple[TimeInterval, ...]
    performance_report_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_nonempty(self.candidate_id, "candidate_id")
        _require_nonempty(self.family_id, "family_id")
        _require_nonempty(self.code_revision, "code_revision")
        _require_digest(self.config_digest)
        object.__setattr__(
            self,
            "execution_config_json",
            _canonical_json_object(self.execution_config_json, "execution_config_json"),
        )
        object.__setattr__(
            self,
            "risk_config_json",
            _canonical_json_object(self.risk_config_json, "risk_config_json"),
        )

        ancestors = self.ancestor_candidate_ids
        if any(not ancestor.strip() for ancestor in ancestors):
            raise ValueError("ancestor ids must not be empty")
        if len(set(ancestors)) != len(ancestors):
            raise ValueError("ancestor ids must be unique")
        if self.candidate_id in ancestors:
            raise ValueError("candidate_id must not appear in ancestor ids")

        if self.parent_candidate_id is None:
            if ancestors:
                raise ValueError("root candidate must not have ancestor ids")
        else:
            _require_nonempty(self.parent_candidate_id, "parent_candidate_id")
            if not ancestors:
                raise ValueError("child candidate must have ancestor ids")
            if ancestors[-1] != self.parent_candidate_id:
                raise ValueError("final ancestor id must equal parent_candidate_id")

        source_ids = _canonical_strings(
            self.source_provenance_ids,
            "source_provenance_ids",
        )
        report_ids = _canonical_strings(
            self.performance_report_ids,
            "performance_report_ids",
        )
        local_touched = normalize_intervals(self.local_touched_intervals)
        effective_touched = normalize_intervals(self.effective_touched_intervals)
        object.__setattr__(self, "source_provenance_ids", source_ids)
        object.__setattr__(self, "performance_report_ids", report_ids)
        object.__setattr__(self, "local_touched_intervals", local_touched)
        object.__setattr__(self, "effective_touched_intervals", effective_touched)

        observation_pair = (self.first_observation_ms, self.last_observation_ms)
        if (observation_pair[0] is None) != (observation_pair[1] is None):
            raise ValueError("observation timestamps must both be set or both be null")
        if local_touched:
            if self.first_observation_ms is None or self.last_observation_ms is None:
                raise ValueError("observation timestamps are required for touched intervals")
            if self.first_observation_ms != local_touched[0].start_ms:
                raise ValueError("first observation must match first local touched interval")
            if self.last_observation_ms != local_touched[-1].end_ms:
                raise ValueError("last observation must match last local touched interval")
            if not source_ids:
                raise ValueError("source provenance is required for touched intervals")
            if not all(
                _interval_is_covered(interval, effective_touched)
                for interval in local_touched
            ):
                raise ValueError("effective touched intervals must cover local touched intervals")
        else:
            if self.first_observation_ms is not None or self.last_observation_ms is not None:
                raise ValueError("observation timestamps require local touched intervals")
            if source_ids:
                raise ValueError("source provenance requires local touched intervals")

        if self.parent_candidate_id is None and effective_touched != local_touched:
            raise ValueError("root effective touched intervals must equal local touched intervals")


def validation_cutover_allowed(
    *,
    validation_start_ms: int,
    freeze_ms: int,
    effective_touched_intervals: Iterable[TimeInterval],
) -> bool:
    if validation_start_ms < 0 or freeze_ms < 0:
        raise ValueError("cutover timestamps must be non-negative")
    if validation_start_ms <= freeze_ms:
        return False

    touched = normalize_intervals(effective_touched_intervals)
    if not touched:
        return True
    return validation_start_ms >= touched[-1].end_ms + SIX_HOURS_MS
