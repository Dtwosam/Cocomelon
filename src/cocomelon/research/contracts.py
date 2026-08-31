from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class ResearchCandidateManifest:
    candidate_id: str
    family_id: str
    parent_candidate_id: str | None
    ancestor_candidate_ids: tuple[str, ...]
    config_digest: str
    code_revision: str
    state: ResearchCandidateState

    def __post_init__(self) -> None:
        _require_nonempty(self.candidate_id, "candidate_id")
        _require_nonempty(self.family_id, "family_id")
        _require_nonempty(self.code_revision, "code_revision")
        _require_digest(self.config_digest)

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
            return

        _require_nonempty(self.parent_candidate_id, "parent_candidate_id")
        if not ancestors:
            raise ValueError("child candidate must have ancestor ids")
        if ancestors[-1] != self.parent_candidate_id:
            raise ValueError("final ancestor id must equal parent_candidate_id")


def validation_cutover_allowed(
    *,
    validation_start_ms: int,
    freeze_ms: int,
    effective_touched_intervals: Iterable[TimeInterval],
) -> bool:
    if validation_start_ms < 0 or freeze_ms < 0:
        raise ValueError("cutover timestamps must be non-negative")
    if validation_start_ms < freeze_ms:
        return False

    touched = normalize_intervals(effective_touched_intervals)
    if not touched:
        return True
    return validation_start_ms >= touched[-1].end_ms + SIX_HOURS_MS
