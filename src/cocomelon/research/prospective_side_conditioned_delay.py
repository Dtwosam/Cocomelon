from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    DelayedEntryFillWeightedError,
    DelayedEntryFillWeightedOutcome,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_pair import (
    BASE_DELAY_MS,
    CHALLENGER_DELAY_MS,
)

ZERO: Final = Decimal("0")
CANDIDATE_ID: Final = "long-120s-short-60s-v1"
STATE_SCHEMA_VERSION: Final = 1
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_PAIRED_EVALUABLE_TRADES: Final = 20
MIN_LONG_TRADES: Final = 5
MIN_SHORT_TRADES: Final = 5
TEMPORAL_BLOCKS: Final = 4
MIN_TEMPORAL_TRADES_PER_BLOCK: Final = 5


class ProspectiveSideConditionedDelayError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveSideConditionedDelayState:
    started_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported side-conditioned delay schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported side-conditioned delay candidate")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "long_delay_ms": CHALLENGER_DELAY_MS,
                "short_delay_ms": BASE_DELAY_MS,
                "direction_policy": "both_directions_remain_eligible",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveSideConditionedDelayState:
        if not isinstance(raw, dict):
            raise ProspectiveSideConditionedDelayError(
                "side-conditioned delay state must be an object"
            )
        expected_rule = {
            "long_delay_ms": CHALLENGER_DELAY_MS,
            "short_delay_ms": BASE_DELAY_MS,
            "direction_policy": "both_directions_remain_eligible",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveSideConditionedDelayError(
                "side-conditioned delay rule does not match frozen candidate"
            )
        schema = raw.get("schema_version")
        started = raw.get("started_at_ms")
        candidate = raw.get("candidate_id")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ProspectiveSideConditionedDelayError(
                "schema_version must be an integer"
            )
        if isinstance(started, bool) or not isinstance(started, int):
            raise ProspectiveSideConditionedDelayError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate, str):
            raise ProspectiveSideConditionedDelayError(
                "candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started,
                schema_version=schema,
                candidate_id=candidate,
            )
        except ValueError as exc:
            raise ProspectiveSideConditionedDelayError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class SideConditionedDelayOutcome:
    trade_id: str
    market: str
    direction: str
    closed_at_ms: int
    actual_net_pnl: Decimal
    base_60s_net_pnl: Decimal
    challenger_120s_net_pnl: Decimal
    selected_net_pnl: Decimal
    selected_delay_ms: int
    selected_fill_fraction: Decimal

    @property
    def selected_minus_actual(self) -> Decimal:
        return self.selected_net_pnl - self.actual_net_pnl

    @property
    def selected_minus_60s(self) -> Decimal:
        return self.selected_net_pnl - self.base_60s_net_pnl


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise ProspectiveSideConditionedDelayError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _outcome_map(
    outcomes: tuple[DelayedEntryOutcome, ...],
    *,
    label: str,
) -> dict[str, DelayedEntryOutcome]:
    by_id = {outcome.trade_id: outcome for outcome in outcomes}
    if len(by_id) != len(outcomes):
        raise ProspectiveSideConditionedDelayError(
            f"{label} outcomes contain duplicate trade ids"
        )
    return by_id


def _fill_weighted(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
) -> DelayedEntryFillWeightedOutcome:
    try:
        return evaluate_delayed_entry_fill_weighted_outcome(
            trade,
            outcome,
        )
    except DelayedEntryFillWeightedError as exc:
        raise ProspectiveSideConditionedDelayError(str(exc)) from exc


def _summary(
    items: tuple[SideConditionedDelayOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    actual = sum((item.actual_net_pnl for item in items), ZERO)
    base = sum((item.base_60s_net_pnl for item in items), ZERO)
    challenger = sum(
        (item.challenger_120s_net_pnl for item in items),
        ZERO,
    )
    selected = sum((item.selected_net_pnl for item in items), ZERO)
    return {
        "trades": count,
        "actual_net_pnl": str(actual),
        "always_60s_net_pnl": str(base),
        "always_120s_net_pnl": str(challenger),
        "selected_net_pnl": str(selected),
        "selected_minus_actual_pnl": str(selected - actual),
        "selected_minus_60s_pnl": str(selected - base),
        "selected_minus_120s_pnl": str(selected - challenger),
        "selected_positive_contributions": sum(
            1 for item in items if item.selected_net_pnl > ZERO
        ),
        "selected_negative_contributions": sum(
            1 for item in items if item.selected_net_pnl < ZERO
        ),
        "selected_zero_contributions": sum(
            1 for item in items if item.selected_net_pnl == ZERO
        ),
        "mean_selected_pnl": (
            None if count == 0 else str(selected / Decimal(count))
        ),
        "mean_selected_fill_fraction": (
            None
            if count == 0
            else str(
                sum(
                    (item.selected_fill_fraction for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
    }


def _temporal_robustness(
    items: tuple[SideConditionedDelayOutcome, ...],
) -> dict[str, object]:
    ordered = tuple(
        sorted(items, key=lambda item: (item.closed_at_ms, item.trade_id))
    )
    blocks: list[dict[str, object]] = []
    for index in range(TEMPORAL_BLOCKS):
        start = index * len(ordered) // TEMPORAL_BLOCKS
        end = (index + 1) * len(ordered) // TEMPORAL_BLOCKS
        block = ordered[start:end]
        if not block:
            continue
        summary = _summary(block)
        full = len(block) >= MIN_TEMPORAL_TRADES_PER_BLOCK
        blocks.append(
            {
                "block_index": index,
                "trades": len(block),
                "full_block": full,
                "first_closed_at_ms": block[0].closed_at_ms,
                "last_closed_at_ms": block[-1].closed_at_ms,
                **summary,
                "positive_vs_actual": (
                    Decimal(str(summary["selected_minus_actual_pnl"]))
                    > ZERO
                ),
                "positive_vs_60s": (
                    Decimal(str(summary["selected_minus_60s_pnl"]))
                    > ZERO
                ),
            }
        )
    full_blocks = tuple(
        block for block in blocks if block["full_block"] is True
    )
    return {
        "configured_blocks": TEMPORAL_BLOCKS,
        "min_trades_per_full_block": MIN_TEMPORAL_TRADES_PER_BLOCK,
        "full_blocks": len(full_blocks),
        "positive_full_blocks_vs_actual": sum(
            1 for block in full_blocks if block["positive_vs_actual"] is True
        ),
        "positive_full_blocks_vs_60s": sum(
            1 for block in full_blocks if block["positive_vs_60s"] is True
        ),
        "all_full_blocks_positive_vs_actual": (
            bool(full_blocks)
            and all(
                block["positive_vs_actual"] is True
                for block in full_blocks
            )
        ),
        "all_full_blocks_positive_vs_60s": (
            bool(full_blocks)
            and all(
                block["positive_vs_60s"] is True
                for block in full_blocks
            )
        ),
        "chronological_blocks": blocks,
    }


def _market_robustness(
    items: tuple[SideConditionedDelayOutcome, ...],
) -> dict[str, object]:
    grouped: defaultdict[
        str,
        list[SideConditionedDelayOutcome],
    ] = defaultdict(list)
    for item in items:
        grouped[item.market].append(item)
    by_market = {
        market: _summary(tuple(values))
        for market, values in sorted(grouped.items())
    }
    total_delta = sum(
        (item.selected_minus_60s for item in items),
        ZERO,
    )
    leave_one_out = {
        market: str(
            total_delta
            - sum(
                (item.selected_minus_60s for item in values),
                ZERO,
            )
        )
        for market, values in sorted(grouped.items())
    }
    values = tuple(Decimal(value) for value in leave_one_out.values())
    return {
        "by_market": by_market,
        "leave_one_market_out_delta_vs_60s": leave_one_out,
        "leave_one_market_out_min_delta_vs_60s": (
            None if not values else str(min(values))
        ),
        "positive_vs_60s_after_any_single_market_removed": (
            bool(values) and all(value > ZERO for value in values)
        ),
    }


def prospective_side_conditioned_delay_summary(
    journal: JournalStore,
    base_60s_outcomes: tuple[DelayedEntryOutcome, ...],
    challenger_120s_outcomes: tuple[DelayedEntryOutcome, ...],
    state: ProspectiveSideConditionedDelayState,
) -> dict[str, object]:
    trades = _trade_map(journal)
    base_map = _outcome_map(base_60s_outcomes, label="60s")
    challenger_map = _outcome_map(
        challenger_120s_outcomes,
        label="120s",
    )
    prospective = tuple(
        sorted(
            (
                trade
                for trade in trades.values()
                if trade.opened_at_ms >= state.started_at_ms
            ),
            key=lambda trade: (trade.closed_at_ms, trade.trade_id),
        )
    )

    evaluated: list[SideConditionedDelayOutcome] = []
    missing_60s = 0
    missing_120s = 0
    non_evaluable_60s = 0
    non_evaluable_120s = 0
    lineage_mismatches = 0

    for trade in prospective:
        base = base_map.get(trade.trade_id)
        challenger = challenger_map.get(trade.trade_id)
        if base is None:
            missing_60s += 1
            continue
        if challenger is None:
            missing_120s += 1
            continue
        if base.source not in EVALUABLE_SOURCES:
            non_evaluable_60s += 1
            continue
        if challenger.source not in EVALUABLE_SOURCES:
            non_evaluable_120s += 1
            continue
        try:
            base_item = _fill_weighted(trade, base)
            challenger_item = _fill_weighted(trade, challenger)
        except ProspectiveSideConditionedDelayError:
            lineage_mismatches += 1
            continue

        selected = (
            challenger_item
            if trade.direction is Direction.LONG
            else base_item
        )
        selected_delay = (
            CHALLENGER_DELAY_MS
            if trade.direction is Direction.LONG
            else BASE_DELAY_MS
        )
        evaluated.append(
            SideConditionedDelayOutcome(
                trade_id=trade.trade_id,
                market=trade.market.canonical,
                direction=trade.direction.value,
                closed_at_ms=trade.closed_at_ms,
                actual_net_pnl=trade.net_pnl,
                base_60s_net_pnl=(
                    base_item.candidate_net_pnl_estimate
                ),
                challenger_120s_net_pnl=(
                    challenger_item.candidate_net_pnl_estimate
                ),
                selected_net_pnl=(
                    selected.candidate_net_pnl_estimate
                ),
                selected_delay_ms=selected_delay,
                selected_fill_fraction=selected.fill_fraction,
            )
        )

    items = tuple(evaluated)
    long_count = sum(1 for item in items if item.direction == "long")
    short_count = sum(1 for item in items if item.direction == "short")
    integrity_clean = (
        missing_60s == 0
        and missing_120s == 0
        and lineage_mismatches == 0
    )
    ready = (
        len(prospective) >= MIN_PROSPECTIVE_CLOSED_TRADES
        and len(items) >= MIN_PAIRED_EVALUABLE_TRADES
        and long_count >= MIN_LONG_TRADES
        and short_count >= MIN_SHORT_TRADES
        and integrity_clean
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "claim_scope": (
            "prospective_side_conditioned_fill_weighted_same_exit_contribution"
        ),
        "rule": state.payload()["rule"],
        "prospective_closed_trades": len(prospective),
        "paired_evaluable_trades": len(items),
        "missing_60s_outcomes": missing_60s,
        "missing_120s_outcomes": missing_120s,
        "non_evaluable_60s": non_evaluable_60s,
        "non_evaluable_120s": non_evaluable_120s,
        "lineage_mismatches": lineage_mismatches,
        "overall": _summary(items),
        "by_side": {
            side: _summary(
                tuple(item for item in items if item.direction == side)
            )
            for side in ("long", "short")
        },
        "robustness": {
            "descriptive_only": True,
            "changes_readiness_gate": False,
            "temporal": _temporal_robustness(items),
            "market": _market_robustness(items),
        },
        "readiness": {
            "ready_for_review": ready,
            "integrity_clean": integrity_clean,
            "min_prospective_closed_trades": MIN_PROSPECTIVE_CLOSED_TRADES,
            "min_paired_evaluable_trades": MIN_PAIRED_EVALUABLE_TRADES,
            "min_long_trades": MIN_LONG_TRADES,
            "min_short_trades": MIN_SHORT_TRADES,
            "missing_prospective_closed_trades": max(
                0,
                MIN_PROSPECTIVE_CLOSED_TRADES - len(prospective),
            ),
            "missing_paired_evaluable_trades": max(
                0,
                MIN_PAIRED_EVALUABLE_TRADES - len(items),
            ),
            "missing_long_trades": max(0, MIN_LONG_TRADES - long_count),
            "missing_short_trades": max(0, MIN_SHORT_TRADES - short_count),
        },
    }
