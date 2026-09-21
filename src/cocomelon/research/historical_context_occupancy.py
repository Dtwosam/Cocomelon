from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_baselines import (
    DecisionAction,
    ExecutionCostAssumptions,
    basket_breadth_1h_bucket,
    basket_direction_1h_bucket,
    relative_strength_1h_bucket,
)
from cocomelon.research.historical_dataset import (
    HistoricalDatasetManifest,
    build_training_rows_from_source_root,
    export_training_dataset,
)
from cocomelon.research.historical_features import HistoricalTrainingRow

ZERO = Decimal("0")
EVIDENCE_CLASS = "touched_development"
REPORT_VERSION = "historical-context-occupancy-v1"


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


def context_state_1h(row: HistoricalTrainingRow) -> str:
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


@dataclass(frozen=True, slots=True)
class ContextOccupancyTrade:
    anchor_end_ms: int
    target_end_ms: int
    realized_net_return: Decimal

    def __post_init__(self) -> None:
        if self.anchor_end_ms < 0:
            raise ValueError("anchor_end_ms must be non-negative")
        if self.target_end_ms <= self.anchor_end_ms:
            raise ValueError("target_end_ms must be greater than anchor_end_ms")
        if not self.realized_net_return.is_finite():
            raise ValueError("realized_net_return must be finite")


@dataclass(frozen=True, slots=True)
class ContextOccupancyBlock:
    block_index: int
    anchor_count: int
    raw_match_count: int
    trade_count: int
    occupied_skip_count: int
    mean_realized_net_return: Decimal | None
    positive_rate: Decimal | None

    def __post_init__(self) -> None:
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        if self.anchor_count <= 0:
            raise ValueError("anchor_count must be positive")
        for field in ("raw_match_count", "trade_count", "occupied_skip_count"):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.trade_count + self.occupied_skip_count != self.raw_match_count:
            raise ValueError("trade and occupied-skip counts must equal raw matches")
        if self.mean_realized_net_return is None:
            if self.trade_count != 0 or self.positive_rate is not None:
                raise ValueError("empty block must not report return statistics")
        else:
            if self.trade_count == 0:
                raise ValueError("non-empty return statistics require trades")
            if not self.mean_realized_net_return.is_finite():
                raise ValueError("mean_realized_net_return must be finite")
            if self.positive_rate is None or not self.positive_rate.is_finite():
                raise ValueError("positive_rate must be finite when trades exist")
            if self.positive_rate < ZERO or self.positive_rate > Decimal("1"):
                raise ValueError("positive_rate must be between zero and one")


@dataclass(frozen=True, slots=True)
class ContextOccupancyEvaluation:
    market: str
    context_state_1h: str
    direction: DecisionAction
    horizon_ms: int
    raw_match_count: int
    trade_count: int
    occupied_skip_count: int
    total_realized_net_return: Decimal
    mean_realized_net_return: Decimal | None
    positive_rate: Decimal | None
    blocks: tuple[ContextOccupancyBlock, ...]
    stable: bool
    min_block_trades: int
    min_block_mean_net_return: Decimal

    def __post_init__(self) -> None:
        if not self.market.strip() or not self.context_state_1h.strip():
            raise ValueError("market and context_state_1h must not be empty")
        if self.direction not in {DecisionAction.LONG, DecisionAction.SHORT}:
            raise ValueError("context occupancy direction must be LONG or SHORT")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.raw_match_count < 0 or self.trade_count < 0:
            raise ValueError("match/trade counts must be non-negative")
        if self.occupied_skip_count < 0:
            raise ValueError("occupied_skip_count must be non-negative")
        if self.trade_count + self.occupied_skip_count != self.raw_match_count:
            raise ValueError("trade and occupied-skip counts must equal raw matches")
        if not self.total_realized_net_return.is_finite():
            raise ValueError("total_realized_net_return must be finite")
        if self.min_block_trades <= 0:
            raise ValueError("min_block_trades must be positive")
        if not self.min_block_mean_net_return.is_finite():
            raise ValueError("min_block_mean_net_return must be finite")
        if not self.blocks:
            raise ValueError("blocks must not be empty")
        if self.mean_realized_net_return is None:
            if self.trade_count != 0 or self.positive_rate is not None:
                raise ValueError("empty evaluation must not report return statistics")
        else:
            if self.trade_count == 0:
                raise ValueError("return statistics require trades")
            if not self.mean_realized_net_return.is_finite():
                raise ValueError("mean_realized_net_return must be finite")
            if self.positive_rate is None or not self.positive_rate.is_finite():
                raise ValueError("positive_rate must be finite when trades exist")
            if self.positive_rate < ZERO or self.positive_rate > Decimal("1"):
                raise ValueError("positive_rate must be between zero and one")


def _anchor_blocks(
    anchors: Sequence[int],
    *,
    block_count: int,
) -> tuple[tuple[int, ...], ...]:
    ordered = tuple(sorted(set(anchors)))
    if len(ordered) < block_count:
        raise ValueError("rows have fewer anchors than stability blocks")
    quotient, remainder = divmod(len(ordered), block_count)
    blocks: list[tuple[int, ...]] = []
    offset = 0
    for index in range(block_count):
        size = quotient + (1 if index < remainder else 0)
        block = ordered[offset : offset + size]
        if not block:
            raise ValueError("stability block must not be empty")
        blocks.append(block)
        offset += size
    return tuple(blocks)


def _realized_net_return(
    row: HistoricalTrainingRow,
    *,
    direction: DecisionAction,
    costs: ExecutionCostAssumptions,
) -> Decimal:
    cost = costs.total_cost_fraction(row.horizon_ms)
    if direction is DecisionAction.LONG:
        return row.long_gross_return - cost
    if direction is DecisionAction.SHORT:
        return row.short_gross_return - cost
    raise ValueError("direction must be LONG or SHORT")


def evaluate_context_occupancy(
    rows: Sequence[HistoricalTrainingRow],
    *,
    market: MarketId,
    context: str,
    direction: DecisionAction,
    horizon_ms: int,
    costs: ExecutionCostAssumptions,
    stability_blocks: int = 4,
    min_block_trades: int = 20,
    min_block_mean_net_return: Decimal = ZERO,
) -> ContextOccupancyEvaluation:
    if not rows:
        raise ValueError("rows must not be empty")
    if direction not in {DecisionAction.LONG, DecisionAction.SHORT}:
        raise ValueError("direction must be LONG or SHORT")
    if horizon_ms <= 0:
        raise ValueError("horizon_ms must be positive")
    if stability_blocks <= 1:
        raise ValueError("stability_blocks must be greater than one")
    if min_block_trades <= 0:
        raise ValueError("min_block_trades must be positive")
    if not min_block_mean_net_return.is_finite():
        raise ValueError("min_block_mean_net_return must be finite")
    if not context.strip():
        raise ValueError("context must not be empty")

    target_rows = tuple(
        sorted(
            (
                row
                for row in rows
                if row.market == market and row.horizon_ms == horizon_ms
            ),
            key=lambda row: (row.anchor_end_ms, row.training_row_id),
        )
    )
    if not target_rows:
        raise ValueError("no target market/horizon rows")

    seen_anchors: set[int] = set()
    for row in target_rows:
        if row.anchor_end_ms in seen_anchors:
            raise ValueError("duplicate target market/horizon anchor")
        seen_anchors.add(row.anchor_end_ms)

    anchor_blocks = _anchor_blocks(
        tuple(row.anchor_end_ms for row in target_rows),
        block_count=stability_blocks,
    )
    block_by_anchor = {
        anchor: index
        for index, block in enumerate(anchor_blocks, start=1)
        for anchor in block
    }

    matched = tuple(
        row for row in target_rows if context_state_1h(row) == context
    )
    occupied_until_ms: int | None = None
    trades: list[ContextOccupancyTrade] = []
    skipped_by_block: dict[int, int] = {
        index: 0 for index in range(1, stability_blocks + 1)
    }
    matched_by_block: dict[int, int] = {
        index: 0 for index in range(1, stability_blocks + 1)
    }
    trades_by_block: dict[int, list[ContextOccupancyTrade]] = {
        index: [] for index in range(1, stability_blocks + 1)
    }

    for row in matched:
        block_index = block_by_anchor[row.anchor_end_ms]
        matched_by_block[block_index] += 1
        if occupied_until_ms is not None and row.anchor_end_ms < occupied_until_ms:
            skipped_by_block[block_index] += 1
            continue
        trade = ContextOccupancyTrade(
            anchor_end_ms=row.anchor_end_ms,
            target_end_ms=row.outcome.target_end_ms,
            realized_net_return=_realized_net_return(
                row,
                direction=direction,
                costs=costs,
            ),
        )
        trades.append(trade)
        trades_by_block[block_index].append(trade)
        occupied_until_ms = row.outcome.target_end_ms

    blocks: list[ContextOccupancyBlock] = []
    stable = True
    for block_index, anchors in enumerate(anchor_blocks, start=1):
        block_trades = tuple(trades_by_block[block_index])
        returns = tuple(item.realized_net_return for item in block_trades)
        if returns:
            total = sum(returns, ZERO)
            mean = total / Decimal(len(returns))
            positive_rate = (
                Decimal(sum(1 for value in returns if value > ZERO))
                / Decimal(len(returns))
            )
        else:
            mean = None
            positive_rate = None
        block = ContextOccupancyBlock(
            block_index=block_index,
            anchor_count=len(anchors),
            raw_match_count=matched_by_block[block_index],
            trade_count=len(block_trades),
            occupied_skip_count=skipped_by_block[block_index],
            mean_realized_net_return=mean,
            positive_rate=positive_rate,
        )
        blocks.append(block)
        stable = stable and (
            block.trade_count >= min_block_trades
            and block.mean_realized_net_return is not None
            and block.mean_realized_net_return > min_block_mean_net_return
        )

    realized = tuple(item.realized_net_return for item in trades)
    total = sum(realized, ZERO)
    mean = None if not realized else total / Decimal(len(realized))
    positive_rate = (
        None
        if not realized
        else Decimal(sum(1 for value in realized if value > ZERO))
        / Decimal(len(realized))
    )

    return ContextOccupancyEvaluation(
        market=market.canonical,
        context_state_1h=context,
        direction=direction,
        horizon_ms=horizon_ms,
        raw_match_count=len(matched),
        trade_count=len(trades),
        occupied_skip_count=len(matched) - len(trades),
        total_realized_net_return=total,
        mean_realized_net_return=mean,
        positive_rate=positive_rate,
        blocks=tuple(blocks),
        stable=stable,
        min_block_trades=min_block_trades,
        min_block_mean_net_return=min_block_mean_net_return,
    )


@dataclass(frozen=True, slots=True)
class HistoricalContextOccupancyReport:
    dataset_id: str
    dataset_logical_sha256: str
    dataset_row_count: int
    anchor_interval: str
    markets: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    source_manifest_ids: tuple[str, ...]
    discovery_report_id: str
    discovery_dataset_id: str
    costs: ExecutionCostAssumptions
    evaluation: ContextOccupancyEvaluation
    evidence_class: str = EVIDENCE_CLASS
    report_version: str = REPORT_VERSION
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in ("dataset_id", "dataset_logical_sha256", "discovery_dataset_id"):
            value = getattr(self, field)
            if len(value) != 64:
                raise ValueError(f"{field} must be a SHA-256 identity")
        if len(self.discovery_report_id) != 64:
            raise ValueError("discovery_report_id must be a SHA-256 identity")
        if self.dataset_row_count <= 0:
            raise ValueError("dataset_row_count must be positive")
        if self.anchor_interval not in {"5m", "15m", "1h"}:
            raise ValueError("unsupported anchor_interval")
        if not self.markets or not self.horizons_ms or not self.source_manifest_ids:
            raise ValueError("dataset provenance fields must not be empty")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("context occupancy evidence must remain touched_development")

    def identity_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_logical_sha256": self.dataset_logical_sha256,
            "dataset_row_count": self.dataset_row_count,
            "anchor_interval": self.anchor_interval,
            "markets": self.markets,
            "horizons_ms": self.horizons_ms,
            "source_manifest_ids": self.source_manifest_ids,
            "discovery_report_id": self.discovery_report_id,
            "discovery_dataset_id": self.discovery_dataset_id,
            "costs": {
                "round_trip_fee_fraction": str(self.costs.round_trip_fee_fraction),
                "round_trip_slippage_fraction": str(
                    self.costs.round_trip_slippage_fraction
                ),
                "funding_reserve_fraction_per_hour": str(
                    self.costs.funding_reserve_fraction_per_hour
                ),
            },
            "evaluation": {
                "market": self.evaluation.market,
                "context_state_1h": self.evaluation.context_state_1h,
                "direction": self.evaluation.direction.value,
                "horizon_ms": self.evaluation.horizon_ms,
                "raw_match_count": self.evaluation.raw_match_count,
                "trade_count": self.evaluation.trade_count,
                "occupied_skip_count": self.evaluation.occupied_skip_count,
                "total_realized_net_return": str(
                    self.evaluation.total_realized_net_return
                ),
                "mean_realized_net_return": (
                    None
                    if self.evaluation.mean_realized_net_return is None
                    else str(self.evaluation.mean_realized_net_return)
                ),
                "positive_rate": (
                    None
                    if self.evaluation.positive_rate is None
                    else str(self.evaluation.positive_rate)
                ),
                "stable": self.evaluation.stable,
                "min_block_trades": self.evaluation.min_block_trades,
                "min_block_mean_net_return": str(
                    self.evaluation.min_block_mean_net_return
                ),
                "blocks": tuple(
                    {
                        "block_index": block.block_index,
                        "anchor_count": block.anchor_count,
                        "raw_match_count": block.raw_match_count,
                        "trade_count": block.trade_count,
                        "occupied_skip_count": block.occupied_skip_count,
                        "mean_realized_net_return": (
                            None
                            if block.mean_realized_net_return is None
                            else str(block.mean_realized_net_return)
                        ),
                        "positive_rate": (
                            None
                            if block.positive_rate is None
                            else str(block.positive_rate)
                        ),
                    }
                    for block in self.evaluation.blocks
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


def run_context_occupancy_from_sources(
    *,
    source_root: Path,
    output_root: Path,
    markets: Sequence[MarketId],
    horizons_ms: Sequence[int],
    anchor_interval: str,
    discovery_report_id: str,
    discovery_dataset_id: str,
    market: MarketId,
    context: str,
    direction: DecisionAction,
    horizon_ms: int,
    costs: ExecutionCostAssumptions,
    stability_blocks: int,
    min_block_trades: int,
    min_block_mean_net_return: Decimal = ZERO,
) -> HistoricalContextOccupancyReport:
    rows = build_training_rows_from_source_root(
        source_root,
        markets=markets,
        horizons_ms=horizons_ms,
        anchor_interval=anchor_interval,
    )
    manifest = export_training_dataset(rows, output_root / "dataset")
    evaluation = evaluate_context_occupancy(
        rows,
        market=market,
        context=context,
        direction=direction,
        horizon_ms=horizon_ms,
        costs=costs,
        stability_blocks=stability_blocks,
        min_block_trades=min_block_trades,
        min_block_mean_net_return=min_block_mean_net_return,
    )
    report = HistoricalContextOccupancyReport(
        dataset_id=manifest.dataset_id,
        dataset_logical_sha256=manifest.logical_sha256,
        dataset_row_count=manifest.row_count,
        anchor_interval=manifest.anchor_interval,
        markets=manifest.markets,
        horizons_ms=manifest.horizons_ms,
        source_manifest_ids=manifest.source_manifest_ids,
        discovery_report_id=discovery_report_id,
        discovery_dataset_id=discovery_dataset_id,
        costs=costs,
        evaluation=evaluation,
    )
    _atomic_write(
        output_root / "context_occupancy.json",
        (_canonical_json(report.to_dict()) + "\n").encode("utf-8"),
    )
    return report
