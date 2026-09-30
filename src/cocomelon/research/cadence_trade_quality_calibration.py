from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.strategy import Direction
from cocomelon.research.cadence_shadow import (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
    ShadowCadenceOutcome,
)

ZERO: Final = Decimal("0")
PRIMARY_CADENCE_MS: Final = FIFTEEN_MINUTES_MS
REQUIRED_HORIZONS_MS: Final = (
    FIFTEEN_MINUTES_MS,
    ONE_HOUR_MS,
)
MIN_PAIRED_DECISIONS: Final = 600
VALIDATION_DECISIONS: Final = 200
MIN_TRAIN_GROUP: Final = 20
MIN_VALIDATION_ADMITTED: Final = 40
MIN_VALIDATION_SIDE_ADMITTED: Final = 10
STABILITY_BLOCKS: Final = 4
MIN_BLOCK_ADMITTED: Final = 5


class CadenceTradeQualityCalibrationError(RuntimeError):
    pass


def _score_band(score: Decimal) -> str:
    if score < Decimal("65"):
        return "<65"
    if score < Decimal("70"):
        return "65-<70"
    if score < Decimal("75"):
        return "70-<75"
    if score < Decimal("80"):
        return "75-<80"
    return "80+"


@dataclass(frozen=True, slots=True, order=True)
class TradeQualityGroup:
    direction: str
    lead_strategy: str
    score_band: str

    def __post_init__(self) -> None:
        if self.direction not in {
            Direction.LONG.value,
            Direction.SHORT.value,
        }:
            raise ValueError("trade-quality direction must be long or short")
        if not self.lead_strategy.strip():
            raise ValueError("lead_strategy must not be empty")
        if self.score_band not in {
            "<65",
            "65-<70",
            "70-<75",
            "75-<80",
            "80+",
        }:
            raise ValueError("unsupported score band")

    @classmethod
    def from_outcome(
        cls,
        outcome: ShadowCadenceOutcome,
    ) -> TradeQualityGroup:
        sample = outcome.sample
        return cls(
            direction=sample.direction.value,
            lead_strategy=sample.lead_strategy,
            score_band=_score_band(sample.score),
        )

    def payload(self) -> dict[str, str]:
        return {
            "direction": self.direction,
            "lead_strategy": self.lead_strategy,
            "score_band": self.score_band,
        }


@dataclass(frozen=True, slots=True)
class _PairedDecision:
    boundary_ms: int
    evaluated_at_ms: int
    decision_id: str
    market: str
    group: TradeQualityGroup
    net_15m: Decimal
    net_1h: Decimal

    def __post_init__(self) -> None:
        if self.boundary_ms < 0 or self.evaluated_at_ms < self.boundary_ms:
            raise ValueError("paired decision timestamps are invalid")
        if not self.decision_id.strip() or not self.market.strip():
            raise ValueError("paired decision identity must not be empty")
        if not self.net_15m.is_finite() or not self.net_1h.is_finite():
            raise ValueError("paired decision returns must be finite")


@dataclass(slots=True)
class _GroupStats:
    count: int = 0
    net_15m: Decimal = ZERO
    net_1h: Decimal = ZERO

    def add(self, item: _PairedDecision) -> None:
        self.count += 1
        self.net_15m += item.net_15m
        self.net_1h += item.net_1h

    @property
    def mean_15m(self) -> Decimal | None:
        if self.count == 0:
            return None
        return self.net_15m / Decimal(self.count)

    @property
    def mean_1h(self) -> Decimal | None:
        if self.count == 0:
            return None
        return self.net_1h / Decimal(self.count)

    def payload(self) -> dict[str, object]:
        return {
            "count": self.count,
            "net_15m": str(self.net_15m),
            "net_1h": str(self.net_1h),
            "mean_15m": (
                None if self.mean_15m is None else str(self.mean_15m)
            ),
            "mean_1h": (
                None if self.mean_1h is None else str(self.mean_1h)
            ),
        }


def _decision_key(
    outcome: ShadowCadenceOutcome,
) -> tuple[int, str, str]:
    sample = outcome.sample
    return (
        sample.boundary_ms,
        sample.market.canonical,
        sample.decision_id,
    )


def _same_decision(
    first: ShadowCadenceOutcome,
    second: ShadowCadenceOutcome,
) -> bool:
    a = first.sample
    b = second.sample
    return (
        a.cadence_ms == b.cadence_ms
        and a.boundary_ms == b.boundary_ms
        and a.evaluated_at_ms == b.evaluated_at_ms
        and a.market == b.market
        and a.direction is b.direction
        and a.score == b.score
        and a.lead_strategy == b.lead_strategy
        and a.decision_id == b.decision_id
        and a.feature_snapshot_id == b.feature_snapshot_id
        and a.entry_px == b.entry_px
        and a.off_primary_boundary == b.off_primary_boundary
    )


def _pair_decisions(
    outcomes: Sequence[ShadowCadenceOutcome],
) -> tuple[tuple[_PairedDecision, ...], int]:
    grouped: dict[
        tuple[int, str, str],
        dict[int, ShadowCadenceOutcome],
    ] = defaultdict(dict)
    for outcome in outcomes:
        sample = outcome.sample
        if sample.cadence_ms != PRIMARY_CADENCE_MS:
            continue
        if sample.horizon_ms not in REQUIRED_HORIZONS_MS:
            continue
        key = _decision_key(outcome)
        horizon_group = grouped[key]
        if sample.horizon_ms in horizon_group:
            raise CadenceTradeQualityCalibrationError(
                "duplicate cadence outcome for one decision horizon"
            )
        horizon_group[sample.horizon_ms] = outcome

    paired: list[_PairedDecision] = []
    incomplete = 0
    for horizon_group in grouped.values():
        if set(horizon_group) != set(REQUIRED_HORIZONS_MS):
            incomplete += 1
            continue
        short = horizon_group[FIFTEEN_MINUTES_MS]
        long = horizon_group[ONE_HOUR_MS]
        if not _same_decision(short, long):
            raise CadenceTradeQualityCalibrationError(
                "cadence outcome horizon lineage mismatch"
            )
        paired.append(
            _PairedDecision(
                boundary_ms=short.sample.boundary_ms,
                evaluated_at_ms=short.sample.evaluated_at_ms,
                decision_id=short.sample.decision_id,
                market=short.sample.market.canonical,
                group=TradeQualityGroup.from_outcome(short),
                net_15m=short.net_return,
                net_1h=long.net_return,
            )
        )

    paired.sort(
        key=lambda item: (
            item.boundary_ms,
            item.evaluated_at_ms,
            item.market,
            item.decision_id,
        )
    )
    return tuple(paired), incomplete


def _stats(items: Sequence[_PairedDecision]) -> _GroupStats:
    result = _GroupStats()
    for item in items:
        result.add(item)
    return result


def _group_stats(
    items: Sequence[_PairedDecision],
) -> dict[TradeQualityGroup, _GroupStats]:
    result: dict[TradeQualityGroup, _GroupStats] = {}
    for item in items:
        result.setdefault(item.group, _GroupStats()).add(item)
    return result


def _selected_groups(
    train: Sequence[_PairedDecision],
) -> tuple[
    frozenset[TradeQualityGroup],
    dict[TradeQualityGroup, _GroupStats],
]:
    stats = _group_stats(train)
    selected = frozenset(
        group
        for group, group_stats in stats.items()
        if group_stats.count >= MIN_TRAIN_GROUP
        and group_stats.mean_15m is not None
        and group_stats.mean_15m > ZERO
        and group_stats.mean_1h is not None
        and group_stats.mean_1h > ZERO
    )
    return selected, stats


def _block_ranges(count: int) -> tuple[tuple[int, int], ...]:
    if count <= 0:
        return tuple((0, 0) for _ in range(STABILITY_BLOCKS))
    return tuple(
        (
            count * index // STABILITY_BLOCKS,
            count * (index + 1) // STABILITY_BLOCKS,
        )
        for index in range(STABILITY_BLOCKS)
    )


def cadence_trade_quality_calibration(
    outcomes: Sequence[ShadowCadenceOutcome],
) -> dict[str, object]:
    paired, incomplete = _pair_decisions(outcomes)
    base = {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "evidence_class": "touched_development",
        "primary_cadence_ms": PRIMARY_CADENCE_MS,
        "required_horizons_ms": list(REQUIRED_HORIZONS_MS),
        "feature_registry": [
            "direction",
            "lead_strategy",
            "score_band",
        ],
        "minimum_paired_decisions": MIN_PAIRED_DECISIONS,
        "validation_decisions": VALIDATION_DECISIONS,
        "minimum_train_group": MIN_TRAIN_GROUP,
        "paired_decisions": len(paired),
        "incomplete_decision_pairs": incomplete,
    }
    if len(paired) < MIN_PAIRED_DECISIONS:
        return {
            **base,
            "status": "not_ready",
            "still_needed_paired_decisions": (
                MIN_PAIRED_DECISIONS - len(paired)
            ),
            "selected_groups": [],
            "qualifies_development": False,
        }

    train = paired[:-VALIDATION_DECISIONS]
    validation = paired[-VALIDATION_DECISIONS:]
    selected, train_groups = _selected_groups(train)
    admitted = tuple(
        item for item in validation if item.group in selected
    )
    baseline_stats = _stats(validation)
    candidate_stats = _stats(admitted)
    by_side = {
        direction: _stats(
            tuple(
                item
                for item in admitted
                if item.group.direction == direction
            )
        )
        for direction in (
            Direction.LONG.value,
            Direction.SHORT.value,
        )
    }

    blocks: list[dict[str, object]] = []
    all_blocks_positive = True
    for block_index, (start, end) in enumerate(
        _block_ranges(len(validation)),
        start=1,
    ):
        window = validation[start:end]
        block_admitted = tuple(
            item for item in window if item.group in selected
        )
        block_stats = _stats(block_admitted)
        positive = (
            block_stats.count >= MIN_BLOCK_ADMITTED
            and block_stats.mean_15m is not None
            and block_stats.mean_15m > ZERO
            and block_stats.mean_1h is not None
            and block_stats.mean_1h > ZERO
        )
        all_blocks_positive = all_blocks_positive and positive
        blocks.append(
            {
                "block": block_index,
                "validation_rows": len(window),
                "admitted_rows": block_stats.count,
                "mean_15m": (
                    None
                    if block_stats.mean_15m is None
                    else str(block_stats.mean_15m)
                ),
                "mean_1h": (
                    None
                    if block_stats.mean_1h is None
                    else str(block_stats.mean_1h)
                ),
                "positive_both_horizons": positive,
            }
        )

    long_count = by_side[Direction.LONG.value].count
    short_count = by_side[Direction.SHORT.value].count
    qualifies = (
        bool(selected)
        and candidate_stats.count >= MIN_VALIDATION_ADMITTED
        and long_count >= MIN_VALIDATION_SIDE_ADMITTED
        and short_count >= MIN_VALIDATION_SIDE_ADMITTED
        and candidate_stats.mean_15m is not None
        and candidate_stats.mean_15m > ZERO
        and candidate_stats.mean_1h is not None
        and candidate_stats.mean_1h > ZERO
        and all_blocks_positive
    )

    selected_payload = []
    for group in sorted(selected):
        group_stats = train_groups[group]
        selected_payload.append(
            {
                **group.payload(),
                "train": group_stats.payload(),
            }
        )

    return {
        **base,
        "status": "completed",
        "still_needed_paired_decisions": 0,
        "train_decisions": len(train),
        "validation_decision_count": len(validation),
        "selected_groups": selected_payload,
        "selected_group_count": len(selected),
        "baseline_validation": baseline_stats.payload(),
        "candidate_validation": candidate_stats.payload(),
        "candidate_validation_by_direction": {
            direction: side_stats.payload()
            for direction, side_stats in by_side.items()
        },
        "stability_blocks": blocks,
        "all_stability_blocks_positive": all_blocks_positive,
        "requirements": {
            "minimum_validation_admitted": MIN_VALIDATION_ADMITTED,
            "minimum_validation_side_admitted": (
                MIN_VALIDATION_SIDE_ADMITTED
            ),
            "stability_blocks": STABILITY_BLOCKS,
            "minimum_block_admitted": MIN_BLOCK_ADMITTED,
            "positive_both_horizons": True,
        },
        "qualifies_development": qualifies,
    }
