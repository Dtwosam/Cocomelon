from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Mapping

from cocomelon.research.entry_markout import (
    ENTRY_MARKOUT_HORIZONS_MS,
)

MIN_OBSERVATIONS_PER_HORIZON: Final = 30


class EntryMarkoutReadinessError(RuntimeError):
    pass


class EntryMarkoutReadinessStatus(StrEnum):
    COLLECTING = "collecting"
    READY_FOR_REVIEW = "ready_for_review"


@dataclass(frozen=True, slots=True)
class EntryMarkoutHorizonReadiness:
    horizon_ms: int
    observations: int
    missing_observations: int
    status: EntryMarkoutReadinessStatus

    def __post_init__(self) -> None:
        if self.horizon_ms not in ENTRY_MARKOUT_HORIZONS_MS:
            raise ValueError("unsupported markout horizon")
        if self.observations < 0:
            raise ValueError("observations must be non-negative")
        if self.missing_observations < 0:
            raise ValueError(
                "missing_observations must be non-negative"
            )
        expected_missing = max(
            0,
            MIN_OBSERVATIONS_PER_HORIZON - self.observations,
        )
        if self.missing_observations != expected_missing:
            raise ValueError(
                "missing_observations must reconcile"
            )
        expected_status = (
            EntryMarkoutReadinessStatus.READY_FOR_REVIEW
            if expected_missing == 0
            else EntryMarkoutReadinessStatus.COLLECTING
        )
        if self.status is not expected_status:
            raise ValueError("readiness status must reconcile")


@dataclass(frozen=True, slots=True)
class EntryMarkoutReadiness:
    horizons: tuple[EntryMarkoutHorizonReadiness, ...]
    all_horizons_ready_for_review: bool
    promotion_authority: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if tuple(
            item.horizon_ms for item in self.horizons
        ) != ENTRY_MARKOUT_HORIZONS_MS:
            raise ValueError(
                "markout readiness horizons must match protocol"
            )
        expected = all(
            item.status
            is EntryMarkoutReadinessStatus.READY_FOR_REVIEW
            for item in self.horizons
        )
        if self.all_horizons_ready_for_review != expected:
            raise ValueError(
                "all_horizons_ready_for_review must reconcile"
            )
        if self.promotion_authority or self.execution_authority:
            raise ValueError(
                "readiness cannot grant promotion or execution authority"
            )


def _observations(
    raw: object,
    *,
    horizon_ms: int,
) -> int:
    if not isinstance(raw, Mapping):
        raise EntryMarkoutReadinessError(
            "markout horizon summary must be an object"
        )
    value = raw.get("observations")
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntryMarkoutReadinessError(
            f"markout observations must be integer for {horizon_ms}"
        )
    if value < 0:
        raise EntryMarkoutReadinessError(
            f"markout observations must be non-negative for {horizon_ms}"
        )
    return value


def entry_markout_readiness(
    summary: Mapping[str, object],
) -> EntryMarkoutReadiness:
    raw_horizons = summary.get("by_horizon_ms")
    if not isinstance(raw_horizons, Mapping):
        raise EntryMarkoutReadinessError(
            "markout summary is missing by_horizon_ms"
        )

    horizons: list[EntryMarkoutHorizonReadiness] = []
    for horizon_ms in ENTRY_MARKOUT_HORIZONS_MS:
        observations = _observations(
            raw_horizons.get(str(horizon_ms)),
            horizon_ms=horizon_ms,
        )
        missing = max(
            0,
            MIN_OBSERVATIONS_PER_HORIZON - observations,
        )
        status = (
            EntryMarkoutReadinessStatus.READY_FOR_REVIEW
            if missing == 0
            else EntryMarkoutReadinessStatus.COLLECTING
        )
        horizons.append(
            EntryMarkoutHorizonReadiness(
                horizon_ms=horizon_ms,
                observations=observations,
                missing_observations=missing,
                status=status,
            )
        )

    resolved = tuple(horizons)
    return EntryMarkoutReadiness(
        horizons=resolved,
        all_horizons_ready_for_review=all(
            item.status
            is EntryMarkoutReadinessStatus.READY_FOR_REVIEW
            for item in resolved
        ),
    )
