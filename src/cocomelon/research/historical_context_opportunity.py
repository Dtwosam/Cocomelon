from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.research.historical_baselines import (
    ExecutionCostAssumptions,
    basket_breadth_1h_bucket,
    basket_direction_1h_bucket,
    relative_strength_1h_bucket,
)
from cocomelon.domain.market import MarketId
from cocomelon.research.historical_dataset import (
    HistoricalDatasetManifest,
    build_training_rows_from_source_root,
    export_training_dataset,
)
from cocomelon.research.historical_features import HistoricalTrainingRow

ZERO = Decimal("0")
EVIDENCE_CLASS = "touched_development"
REPORT_VERSION = "historical-context-opportunity-v1"


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
class ContextOpportunityBlock:
    block_index: int
    anchor_count: int
    row_count: int
    mean_long_net_return: Decimal | None
    mean_short_net_return: Decimal | None

    def __post_init__(self) -> None:
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        if self.anchor_count <= 0:
            raise ValueError("anchor_count must be positive")
        if self.row_count < 0:
            raise ValueError("row_count must be non-negative")
        for name in ("mean_long_net_return", "mean_short_net_return"):
            value = getattr(self, name)
            if value is not None and not value.is_finite():
                raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class ContextOpportunityEntry:
    dimension: str
    value: str
    horizon_ms: int
    row_count: int
    mean_long_net_return: Decimal
    mean_short_net_return: Decimal
    long_positive_rate: Decimal
    short_positive_rate: Decimal
    blocks: tuple[ContextOpportunityBlock, ...]
    stable_long: bool
    stable_short: bool
    min_block_rows: int
    min_block_mean_net_return: Decimal

    def __post_init__(self) -> None:
        if not self.dimension.strip() or not self.value.strip():
            raise ValueError("dimension and value must not be empty")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")
        if self.min_block_rows <= 0:
            raise ValueError("min_block_rows must be positive")
        for name in (
            "mean_long_net_return",
            "mean_short_net_return",
            "long_positive_rate",
            "short_positive_rate",
            "min_block_mean_net_return",
        ):
            value = getattr(self, name)
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
        for rate in (self.long_positive_rate, self.short_positive_rate):
            if rate < ZERO or rate > Decimal("1"):
                raise ValueError("positive rates must be between zero and one")
        if not self.blocks:
            raise ValueError("blocks must not be empty")


@dataclass(frozen=True, slots=True)
class ContextOpportunityMap:
    stability_blocks: int
    min_block_rows: int
    min_block_mean_net_return: Decimal
    entries: tuple[ContextOpportunityEntry, ...]

    def __post_init__(self) -> None:
        if self.stability_blocks <= 1:
            raise ValueError("stability_blocks must be greater than one")
        if self.min_block_rows <= 0:
            raise ValueError("min_block_rows must be positive")
        if not self.min_block_mean_net_return.is_finite():
            raise ValueError("min_block_mean_net_return must be finite")
        if not self.entries:
            raise ValueError("entries must not be empty")


def _context_state_1h(row: HistoricalTrainingRow) -> str:
    feature = row.feature
    return "/".join(
        (
            basket_direction_1h_bucket(feature.basket_median_return_1h),
            basket_breadth_1h_bucket(feature.basket_breadth_positive_1h),
            relative_strength_1h_bucket(
                feature.relative_return_zscore_1h_vs_basket
            ),
        )
    )


def _dimension_resolvers() -> tuple[
    tuple[str, Callable[[HistoricalTrainingRow], str]], ...
]:
    return (
        ("market", lambda row: row.market.canonical),
        ("trend_regime", lambda row: row.feature.trend_regime.value),
        (
            "basket_direction_1h",
            lambda row: basket_direction_1h_bucket(
                row.feature.basket_median_return_1h
            ),
        ),
        (
            "basket_breadth_1h",
            lambda row: basket_breadth_1h_bucket(
                row.feature.basket_breadth_positive_1h
            ),
        ),
        (
            "relative_strength_1h",
            lambda row: relative_strength_1h_bucket(
                row.feature.relative_return_zscore_1h_vs_basket
            ),
        ),
        ("context_state_1h", _context_state_1h),
    )


def _anchor_blocks(
    rows: Sequence[HistoricalTrainingRow],
    *,
    block_count: int,
) -> tuple[tuple[int, ...], ...]:
    anchors = tuple(sorted({row.anchor_end_ms for row in rows}))
    if len(anchors) < block_count:
        raise ValueError("rows have fewer anchors than stability blocks")
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


def _means(
    rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if not rows:
        raise ValueError("rows must not be empty")
    long_returns: list[Decimal] = []
    short_returns: list[Decimal] = []
    for row in rows:
        cost = costs.total_cost_fraction(row.horizon_ms)
        long_returns.append(row.long_gross_return - cost)
        short_returns.append(row.short_gross_return - cost)
    denominator = Decimal(len(rows))
    return (
        sum(long_returns, ZERO) / denominator,
        sum(short_returns, ZERO) / denominator,
        Decimal(sum(1 for value in long_returns if value > ZERO)) / denominator,
        Decimal(sum(1 for value in short_returns if value > ZERO)) / denominator,
    )


@dataclass(frozen=True, slots=True)
class HistoricalContextOpportunityReport:
    dataset_id: str
    dataset_logical_sha256: str
    dataset_row_count: int
    anchor_interval: str
    markets: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    source_manifest_ids: tuple[str, ...]
    costs: ExecutionCostAssumptions
    opportunity_map: ContextOpportunityMap
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
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("opportunity evidence must remain touched_development")

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
            "opportunity_map": {
                "stability_blocks": self.opportunity_map.stability_blocks,
                "min_block_rows": self.opportunity_map.min_block_rows,
                "min_block_mean_net_return": str(
                    self.opportunity_map.min_block_mean_net_return
                ),
                "entries": tuple(
                    {
                        "dimension": entry.dimension,
                        "value": entry.value,
                        "horizon_ms": entry.horizon_ms,
                        "row_count": entry.row_count,
                        "mean_long_net_return": str(entry.mean_long_net_return),
                        "mean_short_net_return": str(entry.mean_short_net_return),
                        "long_positive_rate": str(entry.long_positive_rate),
                        "short_positive_rate": str(entry.short_positive_rate),
                        "stable_long": entry.stable_long,
                        "stable_short": entry.stable_short,
                        "min_block_rows": entry.min_block_rows,
                        "min_block_mean_net_return": str(
                            entry.min_block_mean_net_return
                        ),
                        "blocks": tuple(
                            {
                                "block_index": block.block_index,
                                "anchor_count": block.anchor_count,
                                "row_count": block.row_count,
                                "mean_long_net_return": (
                                    None
                                    if block.mean_long_net_return is None
                                    else str(block.mean_long_net_return)
                                ),
                                "mean_short_net_return": (
                                    None
                                    if block.mean_short_net_return is None
                                    else str(block.mean_short_net_return)
                                ),
                            }
                            for block in entry.blocks
                        ),
                    }
                    for entry in self.opportunity_map.entries
                ),
            },
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


def build_context_opportunity_report(
    rows: Sequence[HistoricalTrainingRow],
    *,
    dataset_manifest: HistoricalDatasetManifest,
    costs: ExecutionCostAssumptions,
    stability_blocks: int,
    min_block_rows: int,
    min_block_mean_net_return: Decimal = ZERO,
) -> HistoricalContextOpportunityReport:
    opportunity_map = build_context_opportunity_map(
        rows,
        costs=costs,
        stability_blocks=stability_blocks,
        min_block_rows=min_block_rows,
        min_block_mean_net_return=min_block_mean_net_return,
    )
    return HistoricalContextOpportunityReport(
        dataset_id=dataset_manifest.dataset_id,
        dataset_logical_sha256=dataset_manifest.logical_sha256,
        dataset_row_count=dataset_manifest.row_count,
        anchor_interval=dataset_manifest.anchor_interval,
        markets=dataset_manifest.markets,
        horizons_ms=dataset_manifest.horizons_ms,
        source_manifest_ids=dataset_manifest.source_manifest_ids,
        costs=costs,
        opportunity_map=opportunity_map,
    )


def run_context_opportunity_from_sources(
    *,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
    anchor_interval: str,
    costs: ExecutionCostAssumptions,
    stability_blocks: int,
    min_block_rows: int,
    min_block_mean_net_return: Decimal = ZERO,
) -> HistoricalContextOpportunityReport:
    rows = build_training_rows_from_source_root(
        source_root,
        markets=markets,
        horizons_ms=horizons_ms,
        anchor_interval=anchor_interval,
    )
    manifest = export_training_dataset(rows, output_root / "dataset")
    report = build_context_opportunity_report(
        rows,
        dataset_manifest=manifest,
        costs=costs,
        stability_blocks=stability_blocks,
        min_block_rows=min_block_rows,
        min_block_mean_net_return=min_block_mean_net_return,
    )
    _atomic_write(
        output_root / "opportunity.json",
        (_canonical_json(report.to_dict()) + "\n").encode("utf-8"),
    )
    return report


def build_context_opportunity_map(
    rows: Sequence[HistoricalTrainingRow],
    *,
    costs: ExecutionCostAssumptions,
    stability_blocks: int = 4,
    min_block_rows: int = 20,
    min_block_mean_net_return: Decimal = ZERO,
) -> ContextOpportunityMap:
    if not rows:
        raise ValueError("rows must not be empty")
    if stability_blocks <= 1:
        raise ValueError("stability_blocks must be greater than one")
    if min_block_rows <= 0:
        raise ValueError("min_block_rows must be positive")
    if not min_block_mean_net_return.is_finite():
        raise ValueError("min_block_mean_net_return must be finite")

    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                row.anchor_end_ms,
                row.market.canonical,
                row.horizon_ms,
                row.training_row_id,
            ),
        )
    )
    anchor_blocks = _anchor_blocks(ordered, block_count=stability_blocks)
    block_index_by_anchor = {
        anchor: index
        for index, block in enumerate(anchor_blocks, start=1)
        for anchor in block
    }

    grouped: dict[
        tuple[str, str, int],
        list[HistoricalTrainingRow],
    ] = defaultdict(list)
    for dimension, resolver in _dimension_resolvers():
        for row in ordered:
            grouped[(dimension, resolver(row), row.horizon_ms)].append(row)

    entries: list[ContextOpportunityEntry] = []
    for (dimension, value, horizon_ms), group in sorted(grouped.items()):
        mean_long, mean_short, long_positive, short_positive = _means(
            group,
            costs=costs,
        )
        by_block: dict[int, list[HistoricalTrainingRow]] = defaultdict(list)
        for row in group:
            by_block[block_index_by_anchor[row.anchor_end_ms]].append(row)

        blocks: list[ContextOpportunityBlock] = []
        stable_long = True
        stable_short = True
        for block_index, anchors in enumerate(anchor_blocks, start=1):
            block_rows = tuple(by_block.get(block_index, ()))
            if block_rows:
                block_long, block_short, _long_rate, _short_rate = _means(
                    block_rows,
                    costs=costs,
                )
            else:
                block_long = None
                block_short = None
            blocks.append(
                ContextOpportunityBlock(
                    block_index=block_index,
                    anchor_count=len(anchors),
                    row_count=len(block_rows),
                    mean_long_net_return=block_long,
                    mean_short_net_return=block_short,
                )
            )
            stable_long = stable_long and (
                len(block_rows) >= min_block_rows
                and block_long is not None
                and block_long > min_block_mean_net_return
            )
            stable_short = stable_short and (
                len(block_rows) >= min_block_rows
                and block_short is not None
                and block_short > min_block_mean_net_return
            )

        entries.append(
            ContextOpportunityEntry(
                dimension=dimension,
                value=value,
                horizon_ms=horizon_ms,
                row_count=len(group),
                mean_long_net_return=mean_long,
                mean_short_net_return=mean_short,
                long_positive_rate=long_positive,
                short_positive_rate=short_positive,
                blocks=tuple(blocks),
                stable_long=stable_long,
                stable_short=stable_short,
                min_block_rows=min_block_rows,
                min_block_mean_net_return=min_block_mean_net_return,
            )
        )

    return ContextOpportunityMap(
        stability_blocks=stability_blocks,
        min_block_rows=min_block_rows,
        min_block_mean_net_return=min_block_mean_net_return,
        entries=tuple(entries),
    )
