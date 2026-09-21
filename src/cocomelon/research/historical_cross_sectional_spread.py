from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_dataset import (
    HistoricalDatasetManifest,
    build_training_rows_from_source_root,
    export_training_dataset,
)
from cocomelon.research.historical_features import HistoricalTrainingRow

ZERO = Decimal("0")
EVIDENCE_CLASS = "touched_development"
REPORT_VERSION = "historical-cross-sectional-spread-v1"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class CrossSectionalSpreadObservation:
    anchor_end_ms: int
    horizon_ms: int
    leader_market: str
    laggard_market: str
    leader_score: Decimal
    laggard_score: Decimal
    momentum_net_return: Decimal
    reversal_net_return: Decimal

    def __post_init__(self) -> None:
        if self.anchor_end_ms < 0:
            raise ValueError("anchor_end_ms must be non-negative")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if not self.leader_market.strip() or not self.laggard_market.strip():
            raise ValueError("market names must not be empty")
        if self.leader_market == self.laggard_market:
            raise ValueError("leader and laggard markets must differ")
        for name in (
            "leader_score",
            "laggard_score",
            "momentum_net_return",
            "reversal_net_return",
        ):
            if not getattr(self, name).is_finite():
                raise ValueError(f"{name} must be finite")
        if self.leader_score <= self.laggard_score:
            raise ValueError("leader_score must exceed laggard_score")


@dataclass(frozen=True, slots=True)
class CrossSectionalSpreadBlock:
    block_index: int
    anchor_count: int
    observation_count: int
    mean_momentum_net_return: Decimal | None
    mean_reversal_net_return: Decimal | None

    def __post_init__(self) -> None:
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        if self.anchor_count <= 0:
            raise ValueError("anchor_count must be positive")
        if self.observation_count < 0:
            raise ValueError("observation_count must be non-negative")
        for name in ("mean_momentum_net_return", "mean_reversal_net_return"):
            value = getattr(self, name)
            if value is not None and not value.is_finite():
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class CrossSectionalSpreadEntry:
    horizon_ms: int
    observation_count: int
    mean_momentum_net_return: Decimal
    mean_reversal_net_return: Decimal
    momentum_positive_rate: Decimal
    reversal_positive_rate: Decimal
    blocks: tuple[CrossSectionalSpreadBlock, ...]
    stable_momentum: bool
    stable_reversal: bool
    min_markets_per_anchor: int
    min_block_observations: int
    min_block_mean_net_return: Decimal
    skipped_incomplete_anchors: int
    skipped_tied_anchors: int

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.observation_count <= 0:
            raise ValueError("observation_count must be positive")
        if self.min_markets_per_anchor < 2:
            raise ValueError("min_markets_per_anchor must be at least two")
        if self.min_block_observations <= 0:
            raise ValueError("min_block_observations must be positive")
        if self.skipped_incomplete_anchors < 0 or self.skipped_tied_anchors < 0:
            raise ValueError("skipped anchor counts must be non-negative")
        for name in (
            "mean_momentum_net_return",
            "mean_reversal_net_return",
            "momentum_positive_rate",
            "reversal_positive_rate",
            "min_block_mean_net_return",
        ):
            if not getattr(self, name).is_finite():
                raise ValueError(f"{name} must be finite")
        for rate in (self.momentum_positive_rate, self.reversal_positive_rate):
            if rate < ZERO or rate > Decimal("1"):
                raise ValueError("positive rates must be between zero and one")
        if not self.blocks:
            raise ValueError("blocks must not be empty")


@dataclass(frozen=True, slots=True)
class HistoricalCrossSectionalSpreadReport:
    dataset_id: str
    dataset_logical_sha256: str
    dataset_row_count: int
    anchor_interval: str
    markets: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    source_manifest_ids: tuple[str, ...]
    costs: ExecutionCostAssumptions
    entries: tuple[CrossSectionalSpreadEntry, ...]
    stability_blocks: int
    min_markets_per_anchor: int
    min_block_observations: int
    min_block_mean_net_return: Decimal
    evidence_class: str = EVIDENCE_CLASS
    report_version: str = REPORT_VERSION
    schema_version: int = 1

    def __post_init__(self) -> None:
        if len(self.dataset_id) != 64:
            raise ValueError("dataset_id must be a SHA-256 identity")
        if len(self.dataset_logical_sha256) != 64:
            raise ValueError("dataset_logical_sha256 must be a SHA-256 digest")
        if self.dataset_row_count <= 0:
            raise ValueError("dataset_row_count must be positive")
        if self.anchor_interval not in {"5m", "15m", "1h"}:
            raise ValueError("unsupported anchor_interval")
        if not self.markets or not self.horizons_ms or not self.source_manifest_ids:
            raise ValueError("dataset provenance fields must not be empty")
        if self.stability_blocks <= 1:
            raise ValueError("stability_blocks must be greater than one")
        if self.min_markets_per_anchor < 2:
            raise ValueError("min_markets_per_anchor must be at least two")
        if self.min_block_observations <= 0:
            raise ValueError("min_block_observations must be positive")
        if not self.min_block_mean_net_return.is_finite():
            raise ValueError("min_block_mean_net_return must be finite")
        if not self.entries:
            raise ValueError("entries must not be empty")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("spread evidence must remain touched_development")

    def identity_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_logical_sha256": self.dataset_logical_sha256,
            "dataset_row_count": self.dataset_row_count,
            "anchor_interval": self.anchor_interval,
            "markets": self.markets,
            "horizons_ms": self.horizons_ms,
            "source_manifest_ids": self.source_manifest_ids,
            "costs": {
                "round_trip_fee_fraction": str(self.costs.round_trip_fee_fraction),
                "round_trip_slippage_fraction": str(
                    self.costs.round_trip_slippage_fraction
                ),
                "funding_reserve_fraction_per_hour": str(
                    self.costs.funding_reserve_fraction_per_hour
                ),
            },
            "stability_blocks": self.stability_blocks,
            "min_markets_per_anchor": self.min_markets_per_anchor,
            "min_block_observations": self.min_block_observations,
            "min_block_mean_net_return": str(self.min_block_mean_net_return),
            "entries": tuple(
                {
                    "horizon_ms": entry.horizon_ms,
                    "observation_count": entry.observation_count,
                    "mean_momentum_net_return": str(
                        entry.mean_momentum_net_return
                    ),
                    "mean_reversal_net_return": str(
                        entry.mean_reversal_net_return
                    ),
                    "momentum_positive_rate": str(entry.momentum_positive_rate),
                    "reversal_positive_rate": str(entry.reversal_positive_rate),
                    "stable_momentum": entry.stable_momentum,
                    "stable_reversal": entry.stable_reversal,
                    "min_markets_per_anchor": entry.min_markets_per_anchor,
                    "min_block_observations": entry.min_block_observations,
                    "min_block_mean_net_return": str(
                        entry.min_block_mean_net_return
                    ),
                    "skipped_incomplete_anchors": entry.skipped_incomplete_anchors,
                    "skipped_tied_anchors": entry.skipped_tied_anchors,
                    "blocks": tuple(
                        {
                            "block_index": block.block_index,
                            "anchor_count": block.anchor_count,
                            "observation_count": block.observation_count,
                            "mean_momentum_net_return": (
                                None
                                if block.mean_momentum_net_return is None
                                else str(block.mean_momentum_net_return)
                            ),
                            "mean_reversal_net_return": (
                                None
                                if block.mean_reversal_net_return is None
                                else str(block.mean_reversal_net_return)
                            ),
                        }
                        for block in entry.blocks
                    ),
                }
                for entry in self.entries
            ),
            "evidence_class": self.evidence_class,
            "report_version": self.report_version,
            "schema_version": self.schema_version,
        }

    @property
    def report_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "report_id": self.report_id}


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("values must not be empty")
    return sum(values, ZERO) / Decimal(len(values))


def _anchor_blocks(
    observations: Sequence[CrossSectionalSpreadObservation],
    *,
    block_count: int,
) -> tuple[tuple[int, ...], ...]:
    anchors = tuple(sorted({item.anchor_end_ms for item in observations}))
    if len(anchors) < block_count:
        raise ValueError("observations have fewer anchors than stability blocks")
    quotient, remainder = divmod(len(anchors), block_count)
    blocks: list[tuple[int, ...]] = []
    offset = 0
    for index in range(block_count):
        size = quotient + (1 if index < remainder else 0)
        block = anchors[offset : offset + size]
        if not block:
            raise ValueError("stability block must not be empty")
        blocks.append(block)
        offset += size
    return tuple(blocks)


def _observations_for_horizon(
    rows: Sequence[HistoricalTrainingRow],
    *,
    horizon_ms: int,
    costs: ExecutionCostAssumptions,
    min_markets_per_anchor: int,
) -> tuple[tuple[CrossSectionalSpreadObservation, ...], int, int]:
    grouped: dict[int, list[HistoricalTrainingRow]] = defaultdict(list)
    for row in rows:
        if row.horizon_ms == horizon_ms:
            grouped[row.anchor_end_ms].append(row)

    observations: list[CrossSectionalSpreadObservation] = []
    skipped_incomplete = 0
    skipped_tied = 0
    leg_cost = costs.total_cost_fraction(horizon_ms)

    for anchor_end_ms, group in sorted(grouped.items()):
        scored = tuple(
            row
            for row in group
            if row.feature.relative_return_zscore_1h_vs_basket is not None
        )
        markets = {row.market.canonical for row in scored}
        if len(scored) < min_markets_per_anchor or len(markets) < min_markets_per_anchor:
            skipped_incomplete += 1
            continue
        ordered = tuple(
            sorted(
                scored,
                key=lambda row: (
                    row.feature.relative_return_zscore_1h_vs_basket,
                    row.market.canonical,
                ),
            )
        )
        laggard = ordered[0]
        leader = ordered[-1]
        laggard_score = laggard.feature.relative_return_zscore_1h_vs_basket
        leader_score = leader.feature.relative_return_zscore_1h_vs_basket
        if laggard_score is None or leader_score is None:
            raise ValueError("scored rows must have relative strength")
        if sum(
            1
            for row in ordered
            if row.feature.relative_return_zscore_1h_vs_basket == laggard_score
        ) > 1 or sum(
            1
            for row in ordered
            if row.feature.relative_return_zscore_1h_vs_basket == leader_score
        ) > 1:
            skipped_tied += 1
            continue

        two_leg_cost = leg_cost * Decimal("2")
        observations.append(
            CrossSectionalSpreadObservation(
                anchor_end_ms=anchor_end_ms,
                horizon_ms=horizon_ms,
                leader_market=leader.market.canonical,
                laggard_market=laggard.market.canonical,
                leader_score=leader_score,
                laggard_score=laggard_score,
                momentum_net_return=(
                    leader.long_gross_return
                    + laggard.short_gross_return
                    - two_leg_cost
                ),
                reversal_net_return=(
                    laggard.long_gross_return
                    + leader.short_gross_return
                    - two_leg_cost
                ),
            )
        )

    return tuple(observations), skipped_incomplete, skipped_tied


def build_cross_sectional_spread_entries(
    rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    stability_blocks: int = 4,
    min_markets_per_anchor: int = 4,
    min_block_observations: int = 50,
    min_block_mean_net_return: Decimal = ZERO,
) -> tuple[CrossSectionalSpreadEntry, ...]:
    if not rows:
        raise ValueError("rows must not be empty")
    if stability_blocks <= 1:
        raise ValueError("stability_blocks must be greater than one")
    if min_markets_per_anchor < 2:
        raise ValueError("min_markets_per_anchor must be at least two")
    if min_block_observations <= 0:
        raise ValueError("min_block_observations must be positive")
    if not min_block_mean_net_return.is_finite():
        raise ValueError("min_block_mean_net_return must be finite")

    entries: list[CrossSectionalSpreadEntry] = []
    for horizon_ms in sorted({row.horizon_ms for row in rows}):
        observations, skipped_incomplete, skipped_tied = _observations_for_horizon(
            rows,
            horizon_ms=horizon_ms,
            costs=costs,
            min_markets_per_anchor=min_markets_per_anchor,
        )
        if not observations:
            continue

        momentum = tuple(item.momentum_net_return for item in observations)
        reversal = tuple(item.reversal_net_return for item in observations)
        blocks_by_anchor = _anchor_blocks(
            observations,
            block_count=stability_blocks,
        )
        observation_by_anchor = {
            item.anchor_end_ms: item for item in observations
        }
        blocks: list[CrossSectionalSpreadBlock] = []
        stable_momentum = True
        stable_reversal = True

        for block_index, anchors in enumerate(blocks_by_anchor, start=1):
            block_observations = tuple(
                observation_by_anchor[anchor]
                for anchor in anchors
                if anchor in observation_by_anchor
            )
            block_momentum = tuple(
                item.momentum_net_return for item in block_observations
            )
            block_reversal = tuple(
                item.reversal_net_return for item in block_observations
            )
            mean_momentum = _mean(block_momentum) if block_momentum else None
            mean_reversal = _mean(block_reversal) if block_reversal else None
            blocks.append(
                CrossSectionalSpreadBlock(
                    block_index=block_index,
                    anchor_count=len(anchors),
                    observation_count=len(block_observations),
                    mean_momentum_net_return=mean_momentum,
                    mean_reversal_net_return=mean_reversal,
                )
            )
            stable_momentum = stable_momentum and (
                len(block_observations) >= min_block_observations
                and mean_momentum is not None
                and mean_momentum > min_block_mean_net_return
            )
            stable_reversal = stable_reversal and (
                len(block_observations) >= min_block_observations
                and mean_reversal is not None
                and mean_reversal > min_block_mean_net_return
            )

        denominator = Decimal(len(observations))
        entries.append(
            CrossSectionalSpreadEntry(
                horizon_ms=horizon_ms,
                observation_count=len(observations),
                mean_momentum_net_return=_mean(momentum),
                mean_reversal_net_return=_mean(reversal),
                momentum_positive_rate=(
                    Decimal(sum(1 for value in momentum if value > ZERO))
                    / denominator
                ),
                reversal_positive_rate=(
                    Decimal(sum(1 for value in reversal if value > ZERO))
                    / denominator
                ),
                blocks=tuple(blocks),
                stable_momentum=stable_momentum,
                stable_reversal=stable_reversal,
                min_markets_per_anchor=min_markets_per_anchor,
                min_block_observations=min_block_observations,
                min_block_mean_net_return=min_block_mean_net_return,
                skipped_incomplete_anchors=skipped_incomplete,
                skipped_tied_anchors=skipped_tied,
            )
        )

    if not entries:
        raise ValueError("no eligible cross-sectional spread observations")
    return tuple(entries)


def build_cross_sectional_spread_report(
    rows: Sequence[HistoricalTrainingRow],
    *,
    dataset_manifest: HistoricalDatasetManifest,
    costs: ExecutionCostAssumptions,
    stability_blocks: int,
    min_markets_per_anchor: int,
    min_block_observations: int,
    min_block_mean_net_return: Decimal = ZERO,
) -> HistoricalCrossSectionalSpreadReport:
    entries = build_cross_sectional_spread_entries(
        rows,
        costs=costs,
        stability_blocks=stability_blocks,
        min_markets_per_anchor=min_markets_per_anchor,
        min_block_observations=min_block_observations,
        min_block_mean_net_return=min_block_mean_net_return,
    )
    return HistoricalCrossSectionalSpreadReport(
        dataset_id=dataset_manifest.dataset_id,
        dataset_logical_sha256=dataset_manifest.logical_sha256,
        dataset_row_count=dataset_manifest.row_count,
        anchor_interval=dataset_manifest.anchor_interval,
        markets=dataset_manifest.markets,
        horizons_ms=dataset_manifest.horizons_ms,
        source_manifest_ids=dataset_manifest.source_manifest_ids,
        costs=costs,
        entries=entries,
        stability_blocks=stability_blocks,
        min_markets_per_anchor=min_markets_per_anchor,
        min_block_observations=min_block_observations,
        min_block_mean_net_return=min_block_mean_net_return,
    )


def run_cross_sectional_spread_from_sources(
    *,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
    anchor_interval: str,
    costs: ExecutionCostAssumptions,
    stability_blocks: int,
    min_markets_per_anchor: int,
    min_block_observations: int,
    min_block_mean_net_return: Decimal = ZERO,
) -> HistoricalCrossSectionalSpreadReport:
    rows = build_training_rows_from_source_root(
        source_root,
        markets=markets,
        horizons_ms=horizons_ms,
        anchor_interval=anchor_interval,
    )
    manifest = export_training_dataset(rows, output_root / "dataset")
    report = build_cross_sectional_spread_report(
        rows,
        dataset_manifest=manifest,
        costs=costs,
        stability_blocks=stability_blocks,
        min_markets_per_anchor=min_markets_per_anchor,
        min_block_observations=min_block_observations,
        min_block_mean_net_return=min_block_mean_net_return,
    )
    _atomic_write(
        output_root / "spread.json",
        (_canonical_json(report.to_dict()) + "\n").encode("utf-8"),
    )
    return report
