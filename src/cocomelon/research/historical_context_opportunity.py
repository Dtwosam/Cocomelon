from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.historical_baselines import (
    ExecutionCostAssumptions,
    basket_breadth_1h_bucket,
    basket_direction_1h_bucket,
    relative_strength_1h_bucket,
)
from cocomelon.research.historical_features import HistoricalTrainingRow

ZERO = Decimal("0")


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
