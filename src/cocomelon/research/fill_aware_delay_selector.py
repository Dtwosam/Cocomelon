from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    DelayedEntryFillWeightedError,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_pair import (
    BASE_DELAY_MS,
    CHALLENGER_DELAY_MS,
)

ZERO: Final = Decimal("0")
FILL_AWARE_DELAY_SELECTOR_ID: Final = (
    "nonfull-60s-waits-to-120s-v1"
)
FILL_AWARE_DELAY_SELECTOR_STATE_SCHEMA_VERSION: Final = 1
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_CAUSAL_EVALUABLE_TRADES: Final = 20
MIN_SELECT_60S_TRADES: Final = 5
MIN_SELECT_120S_TRADES: Final = 5
TEMPORAL_BLOCKS: Final = 4
MIN_TEMPORAL_TRADES_PER_BLOCK: Final = 5


class FillAwareDelaySelectorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FillAwareDelaySelectorState:
    started_at_ms: int
    schema_version: int = (
        FILL_AWARE_DELAY_SELECTOR_STATE_SCHEMA_VERSION
    )
    candidate_id: str = FILL_AWARE_DELAY_SELECTOR_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if (
            self.schema_version
            != FILL_AWARE_DELAY_SELECTOR_STATE_SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported fill-aware delay state schema"
            )
        if self.candidate_id != FILL_AWARE_DELAY_SELECTOR_ID:
            raise ValueError(
                "unsupported fill-aware delay candidate"
            )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": (
                "if_60s_full_visible_book_ioc_choose_60s_"
                "else_if_60s_partial_or_no_fill_choose_120s"
            ),
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> FillAwareDelaySelectorState:
        if not isinstance(raw, dict):
            raise FillAwareDelaySelectorError(
                "fill-aware delay state must be an object"
            )
        schema_version = raw.get("schema_version")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        rule = raw.get("rule")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
        ):
            raise FillAwareDelaySelectorError(
                "fill-aware delay schema_version must be an integer"
            )
        if (
            isinstance(started_at_ms, bool)
            or not isinstance(started_at_ms, int)
        ):
            raise FillAwareDelaySelectorError(
                "fill-aware delay started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise FillAwareDelaySelectorError(
                "fill-aware delay candidate_id must be a string"
            )
        expected_rule = (
            "if_60s_full_visible_book_ioc_choose_60s_"
            "else_if_60s_partial_or_no_fill_choose_120s"
        )
        if rule != expected_rule:
            raise FillAwareDelaySelectorError(
                "fill-aware delay rule does not match frozen candidate"
            )
        try:
            return cls(
                started_at_ms=started_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise FillAwareDelaySelectorError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class FillAwareDelayOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    base_source: str
    challenger_source: str
    selected_delay_ms: int
    actual_net_pnl: Decimal
    base_candidate_net_pnl: Decimal
    challenger_candidate_net_pnl: Decimal
    selected_candidate_net_pnl: Decimal
    base_candidate_r: Decimal
    challenger_candidate_r: Decimal
    selected_candidate_r: Decimal
    selected_fill_fraction: Decimal
    selected_minus_actual_pnl: Decimal
    selected_minus_60s_pnl: Decimal
    selected_minus_120s_pnl: Decimal

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
            self.base_source,
            self.challenger_source,
        ):
            if not identity.strip():
                raise ValueError(
                    "fill-aware delay identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError(
                "fill-aware delay direction must be long or short"
            )
        if self.selected_delay_ms not in {
            BASE_DELAY_MS,
            CHALLENGER_DELAY_MS,
        }:
            raise ValueError(
                "fill-aware delay selection is unsupported"
            )
        if not ZERO <= self.selected_fill_fraction <= Decimal("1"):
            raise ValueError(
                "selected fill fraction must be within [0, 1]"
            )
        for metric in (
            self.actual_net_pnl,
            self.base_candidate_net_pnl,
            self.challenger_candidate_net_pnl,
            self.selected_candidate_net_pnl,
            self.base_candidate_r,
            self.challenger_candidate_r,
            self.selected_candidate_r,
            self.selected_minus_actual_pnl,
            self.selected_minus_60s_pnl,
            self.selected_minus_120s_pnl,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "fill-aware delay economics must be finite"
                )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise FillAwareDelaySelectorError(
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
        raise FillAwareDelaySelectorError(
            f"{label} delayed-entry outcomes contain duplicate trade ids"
        )
    return by_id


def _item(
    trade: TradeJournalEntry,
    base: DelayedEntryOutcome,
    challenger: DelayedEntryOutcome,
) -> FillAwareDelayOutcome:
    try:
        base_item = evaluate_delayed_entry_fill_weighted_outcome(
            trade,
            base,
        )
        challenger_item = (
            evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                challenger,
            )
        )
    except DelayedEntryFillWeightedError as exc:
        raise FillAwareDelaySelectorError(str(exc)) from exc

    choose_60s = (
        base_item.source == "full_visible_book_ioc"
    )
    selected = base_item if choose_60s else challenger_item
    selected_delay_ms = (
        BASE_DELAY_MS if choose_60s else CHALLENGER_DELAY_MS
    )
    return FillAwareDelayOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        base_source=base_item.source,
        challenger_source=challenger_item.source,
        selected_delay_ms=selected_delay_ms,
        actual_net_pnl=trade.net_pnl,
        base_candidate_net_pnl=(
            base_item.candidate_net_pnl_estimate
        ),
        challenger_candidate_net_pnl=(
            challenger_item.candidate_net_pnl_estimate
        ),
        selected_candidate_net_pnl=(
            selected.candidate_net_pnl_estimate
        ),
        base_candidate_r=(
            base_item.candidate_net_r_contribution
        ),
        challenger_candidate_r=(
            challenger_item.candidate_net_r_contribution
        ),
        selected_candidate_r=(
            selected.candidate_net_r_contribution
        ),
        selected_fill_fraction=selected.fill_fraction,
        selected_minus_actual_pnl=(
            selected.candidate_net_pnl_estimate
            - trade.net_pnl
        ),
        selected_minus_60s_pnl=(
            selected.candidate_net_pnl_estimate
            - base_item.candidate_net_pnl_estimate
        ),
        selected_minus_120s_pnl=(
            selected.candidate_net_pnl_estimate
            - challenger_item.candidate_net_pnl_estimate
        ),
    )


def _summary(
    items: tuple[FillAwareDelayOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    actual = sum(
        (item.actual_net_pnl for item in items),
        ZERO,
    )
    base = sum(
        (item.base_candidate_net_pnl for item in items),
        ZERO,
    )
    challenger = sum(
        (item.challenger_candidate_net_pnl for item in items),
        ZERO,
    )
    selected = sum(
        (item.selected_candidate_net_pnl for item in items),
        ZERO,
    )
    return {
        "trades": count,
        "selected_60s": sum(
            1
            for item in items
            if item.selected_delay_ms == BASE_DELAY_MS
        ),
        "selected_120s": sum(
            1
            for item in items
            if item.selected_delay_ms == CHALLENGER_DELAY_MS
        ),
        "actual_net_pnl": str(actual),
        "always_60s_net_pnl": str(base),
        "always_120s_net_pnl": str(challenger),
        "fill_aware_net_pnl": str(selected),
        "fill_aware_minus_actual_pnl": str(
            selected - actual
        ),
        "fill_aware_minus_60s_pnl": str(
            selected - base
        ),
        "fill_aware_minus_120s_pnl": str(
            selected - challenger
        ),
        "fill_aware_better_than_60s": sum(
            1
            for item in items
            if item.selected_minus_60s_pnl > ZERO
        ),
        "fill_aware_worse_than_60s": sum(
            1
            for item in items
            if item.selected_minus_60s_pnl < ZERO
        ),
        "fill_aware_better_than_120s": sum(
            1
            for item in items
            if item.selected_minus_120s_pnl > ZERO
        ),
        "fill_aware_worse_than_120s": sum(
            1
            for item in items
            if item.selected_minus_120s_pnl < ZERO
        ),
        "mean_selected_fill_fraction": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.selected_fill_fraction
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_selected_r_contribution": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.selected_candidate_r
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
    }


def _edge_robustness(
    items: tuple[FillAwareDelayOutcome, ...],
    *,
    field: str,
) -> dict[str, object]:
    values: list[Decimal] = []
    by_market: dict[str, Decimal] = {}
    for item in items:
        value = getattr(item, field)
        if not isinstance(value, Decimal):
            raise FillAwareDelaySelectorError(
                "fill-aware robustness field must be Decimal"
            )
        values.append(value)
        by_market[item.market] = (
            by_market.get(item.market, ZERO) + value
        )

    typed = tuple(values)
    total = sum(typed, ZERO)
    abs_trade_total = sum(
        (abs(value) for value in typed),
        ZERO,
    )
    abs_market_total = sum(
        (abs(value) for value in by_market.values()),
        ZERO,
    )
    largest_trade = (
        None
        if not typed
        else max(typed, key=abs)
    )
    largest_market = (
        None
        if not by_market
        else max(
            by_market.items(),
            key=lambda item: abs(item[1]),
        )
    )
    leave_one_trade_out = tuple(
        total - value
        for value in typed
    )
    leave_one_market_out = tuple(
        total - value
        for value in by_market.values()
    )
    return {
        "trades": len(items),
        "markets": len(by_market),
        "total_delta_pnl": str(total),
        "largest_abs_trade_contribution": (
            None
            if largest_trade is None
            else str(largest_trade)
        ),
        "largest_abs_trade_share": (
            None
            if largest_trade is None
            or abs_trade_total == ZERO
            else str(abs(largest_trade) / abs_trade_total)
        ),
        "leave_one_trade_out_min_delta": (
            None
            if not leave_one_trade_out
            else str(min(leave_one_trade_out))
        ),
        "positive_after_any_single_trade_removed": (
            None
            if len(items) < 2
            else min(leave_one_trade_out) > ZERO
        ),
        "largest_abs_market": (
            None
            if largest_market is None
            else largest_market[0]
        ),
        "largest_abs_market_contribution": (
            None
            if largest_market is None
            else str(largest_market[1])
        ),
        "largest_abs_market_share": (
            None
            if largest_market is None
            or abs_market_total == ZERO
            else str(
                abs(largest_market[1]) / abs_market_total
            )
        ),
        "leave_one_market_out_min_delta": (
            None
            if not leave_one_market_out
            else str(min(leave_one_market_out))
        ),
        "positive_after_any_single_market_removed": (
            None
            if len(by_market) < 2
            else min(leave_one_market_out) > ZERO
        ),
    }


def _block_trade_count(
    block: dict[str, object],
) -> int:
    value = block.get("trades")
    if isinstance(value, bool) or not isinstance(value, int):
        raise FillAwareDelaySelectorError(
            "fill-aware temporal block trade count is invalid"
        )
    return value


def _temporal_robustness(
    items: tuple[FillAwareDelayOutcome, ...],
    trades: dict[str, TradeJournalEntry],
) -> dict[str, object]:
    if not items:
        return {
            "chronological_blocks": [],
            "full_blocks": 0,
            "positive_blocks_vs_60s": 0,
            "positive_blocks_vs_120s": 0,
            "all_full_blocks_positive_vs_60s": False,
            "all_full_blocks_positive_vs_120s": False,
            "configured_blocks": TEMPORAL_BLOCKS,
            "min_trades_per_full_block": (
                MIN_TEMPORAL_TRADES_PER_BLOCK
            ),
        }

    try:
        ordered = tuple(
            sorted(
                items,
                key=lambda item: (
                    trades[item.trade_id].closed_at_ms,
                    trades[item.trade_id].opened_at_ms,
                    item.trade_id,
                ),
            )
        )
    except KeyError as exc:
        raise FillAwareDelaySelectorError(
            "fill-aware temporal robustness is missing journal trade"
        ) from exc

    quotient, remainder = divmod(
        len(ordered),
        TEMPORAL_BLOCKS,
    )
    blocks: list[dict[str, object]] = []
    start = 0
    for index in range(TEMPORAL_BLOCKS):
        count = quotient + (1 if index < remainder else 0)
        stop = start + count
        block_items = ordered[start:stop]
        start = stop
        if not block_items:
            continue
        first_trade = trades[block_items[0].trade_id]
        last_trade = trades[block_items[-1].trade_id]
        versus_60s = sum(
            (
                item.selected_minus_60s_pnl
                for item in block_items
            ),
            ZERO,
        )
        versus_120s = sum(
            (
                item.selected_minus_120s_pnl
                for item in block_items
            ),
            ZERO,
        )
        versus_actual = sum(
            (
                item.selected_minus_actual_pnl
                for item in block_items
            ),
            ZERO,
        )
        blocks.append(
            {
                "block": index + 1,
                "trades": len(block_items),
                "first_closed_at_ms": (
                    first_trade.closed_at_ms
                ),
                "last_closed_at_ms": (
                    last_trade.closed_at_ms
                ),
                "selected_60s": sum(
                    1
                    for item in block_items
                    if item.selected_delay_ms == BASE_DELAY_MS
                ),
                "selected_120s": sum(
                    1
                    for item in block_items
                    if item.selected_delay_ms
                    == CHALLENGER_DELAY_MS
                ),
                "fill_aware_minus_60s_pnl": str(
                    versus_60s
                ),
                "fill_aware_minus_120s_pnl": str(
                    versus_120s
                ),
                "fill_aware_minus_actual_pnl": str(
                    versus_actual
                ),
                "positive_vs_60s": versus_60s > ZERO,
                "positive_vs_120s": versus_120s > ZERO,
            }
        )

    full_blocks = tuple(
        block
        for block in blocks
        if _block_trade_count(block)
        >= MIN_TEMPORAL_TRADES_PER_BLOCK
    )
    positive_60 = sum(
        1
        for block in full_blocks
        if block["positive_vs_60s"] is True
    )
    positive_120 = sum(
        1
        for block in full_blocks
        if block["positive_vs_120s"] is True
    )
    return {
        "chronological_blocks": blocks,
        "full_blocks": len(full_blocks),
        "positive_blocks_vs_60s": positive_60,
        "positive_blocks_vs_120s": positive_120,
        "all_full_blocks_positive_vs_60s": (
            len(full_blocks) == TEMPORAL_BLOCKS
            and positive_60 == TEMPORAL_BLOCKS
        ),
        "all_full_blocks_positive_vs_120s": (
            len(full_blocks) == TEMPORAL_BLOCKS
            and positive_120 == TEMPORAL_BLOCKS
        ),
        "configured_blocks": TEMPORAL_BLOCKS,
        "min_trades_per_full_block": (
            MIN_TEMPORAL_TRADES_PER_BLOCK
        ),
    }


def fill_aware_delay_selector_summary(
    journal: JournalStore,
    base_outcomes: tuple[DelayedEntryOutcome, ...],
    challenger_outcomes: tuple[DelayedEntryOutcome, ...],
    *,
    started_at_ms: int,
) -> dict[str, object]:
    if started_at_ms < 0:
        raise ValueError("started_at_ms must be non-negative")

    trades = _trade_map(journal)
    base_map = _outcome_map(base_outcomes, label="60s")
    challenger_map = _outcome_map(
        challenger_outcomes,
        label="120s",
    )
    prospective = tuple(
        trade
        for trade in trades.values()
        if trade.opened_at_ms >= started_at_ms
    )

    evaluated: list[FillAwareDelayOutcome] = []
    missing_base = 0
    missing_challenger = 0
    non_evaluable_base = 0
    non_evaluable_challenger = 0
    lineage_mismatches = 0

    for trade in prospective:
        base = base_map.get(trade.trade_id)
        challenger = challenger_map.get(trade.trade_id)
        if base is None:
            missing_base += 1
            continue
        if challenger is None:
            missing_challenger += 1
            continue
        if base.source not in EVALUABLE_SOURCES:
            non_evaluable_base += 1
            continue
        if challenger.source not in EVALUABLE_SOURCES:
            non_evaluable_challenger += 1
            continue
        try:
            evaluated.append(
                _item(
                    trade,
                    base,
                    challenger,
                )
            )
        except FillAwareDelaySelectorError:
            lineage_mismatches += 1

    items = tuple(evaluated)
    selected_60s = sum(
        1
        for item in items
        if item.selected_delay_ms == BASE_DELAY_MS
    )
    selected_120s = len(items) - selected_60s
    ready = (
        len(prospective) >= MIN_PROSPECTIVE_CLOSED_TRADES
        and len(items) >= MIN_CAUSAL_EVALUABLE_TRADES
        and selected_60s >= MIN_SELECT_60S_TRADES
        and selected_120s >= MIN_SELECT_120S_TRADES
        and missing_base == 0
        and missing_challenger == 0
        and non_evaluable_base == 0
        and non_evaluable_challenger == 0
        and lineage_mismatches == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": FILL_AWARE_DELAY_SELECTOR_ID,
        "claim_scope": (
            "fill_weighted_same_exit_trade_contribution_only"
        ),
        "rule": (
            "if_60s_full_visible_book_ioc_choose_60s_"
            "else_if_60s_partial_or_no_fill_choose_120s"
        ),
        "base_delay_ms": BASE_DELAY_MS,
        "challenger_delay_ms": CHALLENGER_DELAY_MS,
        "started_at_ms": started_at_ms,
        "prospective_closed_trades": len(prospective),
        "causal_evaluable_trades": len(items),
        "missing_base_outcome": missing_base,
        "missing_challenger_outcome": missing_challenger,
        "non_evaluable_base": non_evaluable_base,
        "non_evaluable_challenger": non_evaluable_challenger,
        "lineage_mismatches": lineage_mismatches,
        "overall": _summary(items),
        "by_side": {
            side: _summary(
                tuple(
                    item
                    for item in items
                    if item.direction == side
                )
            )
            for side in ("long", "short")
        },
        "by_60s_source": {
            source: _summary(
                tuple(
                    item
                    for item in items
                    if item.base_source == source
                )
            )
            for source in sorted(EVALUABLE_SOURCES)
        },
        "robustness": {
            "descriptive_only": True,
            "changes_readiness_gate": False,
            "fill_aware_minus_60s": _edge_robustness(
                items,
                field="selected_minus_60s_pnl",
            ),
            "fill_aware_minus_120s": _edge_robustness(
                items,
                field="selected_minus_120s_pnl",
            ),
            "temporal": _temporal_robustness(
                items,
                trades,
            ),
        },
        "readiness": {
            "ready_for_review": ready,
            "min_prospective_closed_trades": (
                MIN_PROSPECTIVE_CLOSED_TRADES
            ),
            "min_causal_evaluable_trades": (
                MIN_CAUSAL_EVALUABLE_TRADES
            ),
            "min_selected_60s_trades": (
                MIN_SELECT_60S_TRADES
            ),
            "min_selected_120s_trades": (
                MIN_SELECT_120S_TRADES
            ),
            "missing_prospective_closed_trades": max(
                0,
                MIN_PROSPECTIVE_CLOSED_TRADES
                - len(prospective),
            ),
            "missing_causal_evaluable_trades": max(
                0,
                MIN_CAUSAL_EVALUABLE_TRADES
                - len(items),
            ),
            "missing_selected_60s_trades": max(
                0,
                MIN_SELECT_60S_TRADES - selected_60s,
            ),
            "missing_selected_120s_trades": max(
                0,
                MIN_SELECT_120S_TRADES - selected_120s,
            ),
        },
    }
