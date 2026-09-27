from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from cocomelon.research.entry_mid_markout_shadow import (
    ENTRY_MID_MARKOUT_HORIZONS_MS,
    ENTRY_MID_MARKOUT_MAX_LAG_MS,
)

MIN_FRESH_OBSERVATIONS_PER_HORIZON: Final = 30
MAX_NON_FRESH_FRACTION: Final = Decimal("0.10")
EXPECTED_SOURCE: Final = "allMids_mid_px"


class EntryMidMarkoutReadinessError(RuntimeError):
    pass


class EntryMidMarkoutReadinessStatus(StrEnum):
    COLLECTING = "collecting"
    READY_FOR_REVIEW = "ready_for_review"


@dataclass(frozen=True, slots=True)
class EntryMidMarkoutHorizonReadiness:
    horizon_ms: int
    fresh: int
    stale: int
    missing_at_close: int
    censored: int
    decision_attribution_misses: int
    missing_fresh_observations: int
    non_fresh_fraction: Decimal | None
    coverage_quality_ready: bool
    status: EntryMidMarkoutReadinessStatus

    def __post_init__(self) -> None:
        if self.horizon_ms not in ENTRY_MID_MARKOUT_HORIZONS_MS:
            raise ValueError("unsupported allMids markout horizon")
        for field_name in (
            "fresh",
            "stale",
            "missing_at_close",
            "censored",
            "decision_attribution_misses",
            "missing_fresh_observations",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")

        expected_missing = max(
            0,
            MIN_FRESH_OBSERVATIONS_PER_HORIZON - self.fresh,
        )
        if self.missing_fresh_observations != expected_missing:
            raise ValueError(
                "missing_fresh_observations must reconcile"
            )

        eligible = self.fresh + self.stale + self.missing_at_close
        expected_fraction = (
            None
            if eligible == 0
            else Decimal(self.stale + self.missing_at_close)
            / Decimal(eligible)
        )
        if self.non_fresh_fraction != expected_fraction:
            raise ValueError("non_fresh_fraction must reconcile")

        expected_quality = (
            expected_fraction is not None
            and expected_fraction <= MAX_NON_FRESH_FRACTION
            and self.decision_attribution_misses == 0
        )
        if self.coverage_quality_ready != expected_quality:
            raise ValueError("coverage_quality_ready must reconcile")

        expected_status = (
            EntryMidMarkoutReadinessStatus.READY_FOR_REVIEW
            if expected_missing == 0 and expected_quality
            else EntryMidMarkoutReadinessStatus.COLLECTING
        )
        if self.status is not expected_status:
            raise ValueError("readiness status must reconcile")


@dataclass(frozen=True, slots=True)
class EntryMidMarkoutReadiness:
    horizons: tuple[EntryMidMarkoutHorizonReadiness, ...]
    unmatched_closed_trades: int
    all_horizons_ready_for_review: bool
    promotion_authority: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        if tuple(
            item.horizon_ms for item in self.horizons
        ) != ENTRY_MID_MARKOUT_HORIZONS_MS:
            raise ValueError(
                "allMids readiness horizons must match protocol"
            )
        if self.unmatched_closed_trades < 0:
            raise ValueError(
                "unmatched_closed_trades must be non-negative"
            )
        expected = (
            self.unmatched_closed_trades == 0
            and all(
                item.status
                is EntryMidMarkoutReadinessStatus.READY_FOR_REVIEW
                for item in self.horizons
            )
        )
        if self.all_horizons_ready_for_review != expected:
            raise ValueError(
                "all_horizons_ready_for_review must reconcile"
            )
        if self.promotion_authority or self.execution_authority:
            raise ValueError(
                "readiness cannot grant promotion or execution authority"
            )


def _non_negative_int(
    raw: Mapping[str, object],
    field_name: str,
    *,
    horizon_ms: int | None = None,
) -> int:
    value = raw.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        suffix = (
            ""
            if horizon_ms is None
            else f" for horizon {horizon_ms}"
        )
        raise EntryMidMarkoutReadinessError(
            f"{field_name} must be an integer{suffix}"
        )
    if value < 0:
        raise EntryMidMarkoutReadinessError(
            f"{field_name} must be non-negative"
        )
    return value


def entry_mid_markout_readiness(
    summary: Mapping[str, object],
) -> EntryMidMarkoutReadiness:
    if summary.get("source") != EXPECTED_SOURCE:
        raise EntryMidMarkoutReadinessError(
            "allMids readiness source mismatch"
        )
    if summary.get("horizons_ms") != list(
        ENTRY_MID_MARKOUT_HORIZONS_MS
    ):
        raise EntryMidMarkoutReadinessError(
            "allMids readiness horizon protocol mismatch"
        )
    if summary.get("max_observation_lag_ms") != (
        ENTRY_MID_MARKOUT_MAX_LAG_MS
    ):
        raise EntryMidMarkoutReadinessError(
            "allMids readiness lag protocol mismatch"
        )

    raw_horizons = summary.get("by_horizon_ms")
    if not isinstance(raw_horizons, Mapping):
        raise EntryMidMarkoutReadinessError(
            "allMids summary is missing by_horizon_ms"
        )

    horizons: list[EntryMidMarkoutHorizonReadiness] = []
    for horizon_ms in ENTRY_MID_MARKOUT_HORIZONS_MS:
        raw = raw_horizons.get(str(horizon_ms))
        if not isinstance(raw, Mapping):
            raise EntryMidMarkoutReadinessError(
                f"missing allMids horizon {horizon_ms}"
            )
        fresh = _non_negative_int(
            raw,
            "fresh",
            horizon_ms=horizon_ms,
        )
        stale = _non_negative_int(
            raw,
            "stale",
            horizon_ms=horizon_ms,
        )
        missing_at_close = _non_negative_int(
            raw,
            "missing_at_close",
            horizon_ms=horizon_ms,
        )
        censored = _non_negative_int(
            raw,
            "censored",
            horizon_ms=horizon_ms,
        )
        attribution_misses = _non_negative_int(
            raw,
            "decision_attribution_misses",
            horizon_ms=horizon_ms,
        )

        eligible = fresh + stale + missing_at_close
        non_fresh_fraction = (
            None
            if eligible == 0
            else Decimal(stale + missing_at_close)
            / Decimal(eligible)
        )
        missing_fresh = max(
            0,
            MIN_FRESH_OBSERVATIONS_PER_HORIZON - fresh,
        )
        quality_ready = (
            non_fresh_fraction is not None
            and non_fresh_fraction <= MAX_NON_FRESH_FRACTION
            and attribution_misses == 0
        )
        status = (
            EntryMidMarkoutReadinessStatus.READY_FOR_REVIEW
            if missing_fresh == 0 and quality_ready
            else EntryMidMarkoutReadinessStatus.COLLECTING
        )
        horizons.append(
            EntryMidMarkoutHorizonReadiness(
                horizon_ms=horizon_ms,
                fresh=fresh,
                stale=stale,
                missing_at_close=missing_at_close,
                censored=censored,
                decision_attribution_misses=(
                    attribution_misses
                ),
                missing_fresh_observations=missing_fresh,
                non_fresh_fraction=non_fresh_fraction,
                coverage_quality_ready=quality_ready,
                status=status,
            )
        )

    unmatched_closed = _non_negative_int(
        summary,
        "unmatched_closed_trades",
    )
    resolved = tuple(horizons)
    return EntryMidMarkoutReadiness(
        horizons=resolved,
        unmatched_closed_trades=unmatched_closed,
        all_horizons_ready_for_review=(
            unmatched_closed == 0
            and all(
                item.status
                is EntryMidMarkoutReadinessStatus.READY_FOR_REVIEW
                for item in resolved
            )
        ),
    )
