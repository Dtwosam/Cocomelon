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
