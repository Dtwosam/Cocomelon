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
    DelayedEntryFillWeightedOutcome,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_pair import (
    BASE_DELAY_MS,
    CHALLENGER_DELAY_MS,
)
from cocomelon.research.entry_mid_markout_shadow import (
    EntryMidMarkoutOutcome,
)

ZERO: Final = Decimal("0")
ADAPTIVE_DELAY_SELECTOR_ID: Final = "adverse-1m-mid-waits-to-120s-v1"
ADAPTIVE_DELAY_SELECTOR_STATE_SCHEMA_VERSION: Final = 1
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_CAUSAL_EVALUABLE_TRADES: Final = 20
MIN_SELECT_60S_TRADES: Final = 5
MIN_SELECT_120S_TRADES: Final = 5


class AdaptiveDelaySelectorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AdaptiveDelaySelectorState:
    started_at_ms: int
    schema_version: int = ADAPTIVE_DELAY_SELECTOR_STATE_SCHEMA_VERSION
    candidate_id: str = ADAPTIVE_DELAY_SELECTOR_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if (
            self.schema_version
            != ADAPTIVE_DELAY_SELECTOR_STATE_SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported adaptive-delay state schema"
            )
        if self.candidate_id != ADAPTIVE_DELAY_SELECTOR_ID:
            raise ValueError(
                "unsupported adaptive-delay candidate"
            )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": (
                "if_fresh_available_1m_mid_gross_r_lt_0_choose_120s_"
                "else_choose_60s"
            ),
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> AdaptiveDelaySelectorState:
        if not isinstance(raw, dict):
            raise AdaptiveDelaySelectorError(
                "adaptive-delay state must be an object"
            )
        schema_version = raw.get("schema_version")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        rule = raw.get("rule")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
        ):
            raise AdaptiveDelaySelectorError(
                "adaptive-delay schema_version must be an integer"
            )
        if (
            isinstance(started_at_ms, bool)
            or not isinstance(started_at_ms, int)
        ):
            raise AdaptiveDelaySelectorError(
                "adaptive-delay started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise AdaptiveDelaySelectorError(
                "adaptive-delay candidate_id must be a string"
            )
        expected_rule = (
            "if_fresh_available_1m_mid_gross_r_lt_0_choose_120s_"
            "else_choose_60s"
        )
        if rule != expected_rule:
            raise AdaptiveDelaySelectorError(
                "adaptive-delay rule does not match frozen candidate"
            )
        try:
            return cls(
                started_at_ms=started_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise AdaptiveDelaySelectorError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class AdaptiveDelayOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    markout_status: str
    markout_gross_r: Decimal | None
    markout_observed_at_ms: int | None
    signal_available_at_decision: bool
    base_attempted_at_ms: int
    selected_delay_ms: int
    actual_net_pnl: Decimal
    base_candidate_net_pnl: Decimal
    challenger_candidate_net_pnl: Decimal
    adaptive_candidate_net_pnl: Decimal
    base_candidate_r: Decimal
    challenger_candidate_r: Decimal
    adaptive_candidate_r: Decimal
    adaptive_fill_fraction: Decimal
    adaptive_minus_base_pnl: Decimal
    adaptive_minus_challenger_pnl: Decimal
    adaptive_minus_actual_pnl: Decimal

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
        ):
            if not identity.strip():
                raise ValueError(
                    "adaptive-delay identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError(
                "adaptive-delay direction must be long or short"
            )
        if self.selected_delay_ms not in {
            BASE_DELAY_MS,
            CHALLENGER_DELAY_MS,
        }:
            raise ValueError(
                "adaptive-delay selection is unsupported"
            )
        if not self.markout_status.strip():
            raise ValueError("markout_status must not be empty")
        if self.signal_available_at_decision:
            if (
                self.markout_status != "fresh"
                or self.markout_gross_r is None
                or self.markout_observed_at_ms is None
                or self.markout_observed_at_ms
                > self.base_attempted_at_ms
            ):
                raise ValueError(
                    "available adaptive signal is inconsistent"
                )
        if (
            self.markout_observed_at_ms is not None
            and self.markout_observed_at_ms < 0
        ):
            raise ValueError(
                "markout_observed_at_ms must be non-negative"
            )
        if not ZERO <= self.adaptive_fill_fraction <= Decimal("1"):
            raise ValueError(
                "adaptive fill fraction must be within [0, 1]"
            )
        if (
            self.markout_gross_r is not None
            and not self.markout_gross_r.is_finite()
        ):
            raise ValueError(
                "adaptive markout gross R must be finite"
            )
        for metric in (
            self.actual_net_pnl,
            self.base_candidate_net_pnl,
            self.challenger_candidate_net_pnl,
            self.adaptive_candidate_net_pnl,
            self.base_candidate_r,
            self.challenger_candidate_r,
            self.adaptive_candidate_r,
            self.adaptive_minus_base_pnl,
            self.adaptive_minus_challenger_pnl,
            self.adaptive_minus_actual_pnl,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "adaptive-delay economics must be finite"
                )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise AdaptiveDelaySelectorError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _delayed_map(
    outcomes: tuple[DelayedEntryOutcome, ...],
    *,
    label: str,
) -> dict[str, DelayedEntryOutcome]:
    by_id = {outcome.trade_id: outcome for outcome in outcomes}
    if len(by_id) != len(outcomes):
        raise AdaptiveDelaySelectorError(
            f"{label} outcomes contain duplicate trade ids"
        )
    return by_id


def _mid_map(
    outcomes: tuple[EntryMidMarkoutOutcome, ...],
) -> dict[str, EntryMidMarkoutOutcome]:
    selected = tuple(
        outcome
        for outcome in outcomes
        if outcome.horizon_ms == BASE_DELAY_MS
    )
    by_id = {outcome.trade_id: outcome for outcome in selected}
    if len(by_id) != len(selected):
        raise AdaptiveDelaySelectorError(
            "1m mid-markout outcomes contain duplicate trade ids"
        )
    return by_id


def _validate_mid_lineage(
    trade: TradeJournalEntry,
    mid: EntryMidMarkoutOutcome,
) -> None:
    if (
        mid.opening_plan_id != trade.opening_plan_id
        or mid.market != trade.market.canonical
        or mid.direction != trade.direction.value
        or mid.strategy_decision_id != trade.strategy_decision_id
        or mid.feature_snapshot_id != trade.feature_snapshot_id
        or mid.replay_run_id != trade.replay_run_id
        or mid.target_timestamp_ms
        != trade.opened_at_ms + BASE_DELAY_MS
    ):
        raise AdaptiveDelaySelectorError(
            "mid-markout lineage does not match journal"
        )


def _evaluate_delayed(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
) -> DelayedEntryFillWeightedOutcome:
    try:
        return evaluate_delayed_entry_fill_weighted_outcome(
            trade,
            outcome,
        )
    except DelayedEntryFillWeightedError as exc:
        raise AdaptiveDelaySelectorError(str(exc)) from exc


def _item(
    trade: TradeJournalEntry,
    mid: EntryMidMarkoutOutcome,
    base: DelayedEntryOutcome,
    challenger: DelayedEntryOutcome,
) -> AdaptiveDelayOutcome:
    _validate_mid_lineage(trade, mid)
    if base.observation_lag_ms is None:
        raise AdaptiveDelaySelectorError(
            "60s delayed attempt is missing observation lag"
        )
    base_attempted_at_ms = (
        trade.opened_at_ms
        + BASE_DELAY_MS
        + base.observation_lag_ms
    )
    signal_available = (
        mid.status == "fresh"
        and mid.observed_timestamp_ms is not None
        and mid.gross_r is not None
        and mid.observed_timestamp_ms <= base_attempted_at_ms
    )

    base_item = _evaluate_delayed(trade, base)
    challenger_item = _evaluate_delayed(trade, challenger)
    choose_challenger = (
        signal_available
        and mid.gross_r is not None
        and mid.gross_r < ZERO
    )
    selected = (
        challenger_item
        if choose_challenger
        else base_item
    )
    selected_delay_ms = (
        CHALLENGER_DELAY_MS
        if choose_challenger
        else BASE_DELAY_MS
    )

    return AdaptiveDelayOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        markout_status=mid.status,
        markout_gross_r=mid.gross_r,
        markout_observed_at_ms=mid.observed_timestamp_ms,
        signal_available_at_decision=signal_available,
        base_attempted_at_ms=base_attempted_at_ms,
        selected_delay_ms=selected_delay_ms,
        actual_net_pnl=trade.net_pnl,
        base_candidate_net_pnl=(
            base_item.candidate_net_pnl_estimate
        ),
        challenger_candidate_net_pnl=(
            challenger_item.candidate_net_pnl_estimate
        ),
        adaptive_candidate_net_pnl=(
            selected.candidate_net_pnl_estimate
        ),
        base_candidate_r=(
            base_item.candidate_net_r_contribution
        ),
        challenger_candidate_r=(
            challenger_item.candidate_net_r_contribution
        ),
        adaptive_candidate_r=(
            selected.candidate_net_r_contribution
        ),
        adaptive_fill_fraction=selected.fill_fraction,
        adaptive_minus_base_pnl=(
            selected.candidate_net_pnl_estimate
            - base_item.candidate_net_pnl_estimate
        ),
        adaptive_minus_challenger_pnl=(
            selected.candidate_net_pnl_estimate
            - challenger_item.candidate_net_pnl_estimate
        ),
        adaptive_minus_actual_pnl=(
            selected.candidate_net_pnl_estimate
            - trade.net_pnl
        ),
    )


def _summary(
    items: tuple[AdaptiveDelayOutcome, ...],
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
        (
            item.challenger_candidate_net_pnl
            for item in items
        ),
        ZERO,
    )
    adaptive = sum(
        (
            item.adaptive_candidate_net_pnl
            for item in items
        ),
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
            if item.selected_delay_ms
            == CHALLENGER_DELAY_MS
        ),
        "adaptive_better_than_60s": sum(
            1
            for item in items
            if item.adaptive_minus_base_pnl > ZERO
        ),
        "adaptive_worse_than_60s": sum(
            1
            for item in items
            if item.adaptive_minus_base_pnl < ZERO
        ),
        "adaptive_equal_to_60s": sum(
            1
            for item in items
            if item.adaptive_minus_base_pnl == ZERO
        ),
        "adaptive_better_than_120s": sum(
            1
            for item in items
            if item.adaptive_minus_challenger_pnl > ZERO
        ),
        "adaptive_worse_than_120s": sum(
            1
            for item in items
            if item.adaptive_minus_challenger_pnl < ZERO
        ),
        "adaptive_equal_to_120s": sum(
            1
            for item in items
            if item.adaptive_minus_challenger_pnl == ZERO
        ),
        "actual_net_pnl": str(actual),
        "always_60s_net_pnl": str(base),
        "always_120s_net_pnl": str(challenger),
        "adaptive_net_pnl": str(adaptive),
        "adaptive_minus_actual_pnl": str(
            adaptive - actual
        ),
        "adaptive_minus_60s_pnl": str(
            adaptive - base
        ),
        "adaptive_minus_120s_pnl": str(
            adaptive - challenger
        ),
        "mean_adaptive_fill_fraction": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.adaptive_fill_fraction
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_adaptive_r_contribution": (
            None
            if count == 0
            else str(
                sum(
                    (
                        item.adaptive_candidate_r
                        for item in items
                    ),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
    }


def adaptive_delay_selector_summary(
    journal: JournalStore,
    mid_outcomes: tuple[EntryMidMarkoutOutcome, ...],
    base_outcomes: tuple[DelayedEntryOutcome, ...],
    challenger_outcomes: tuple[DelayedEntryOutcome, ...],
    *,
    started_at_ms: int,
) -> dict[str, object]:
    if started_at_ms < 0:
        raise ValueError("started_at_ms must be non-negative")

    trades = _trade_map(journal)
    mid_map = _mid_map(mid_outcomes)
    base_map = _delayed_map(base_outcomes, label="60s")
    challenger_map = _delayed_map(
        challenger_outcomes,
        label="120s",
    )
    prospective = tuple(
        trade
        for trade in trades.values()
        if trade.opened_at_ms >= started_at_ms
    )

    evaluated: list[AdaptiveDelayOutcome] = []
    missing_mid = 0
    non_fresh_mid = 0
    late_mid = 0
    missing_base = 0
    missing_challenger = 0
    non_evaluable_base = 0
    non_evaluable_challenger = 0
    lineage_mismatches = 0

    for trade in prospective:
        mid = mid_map.get(trade.trade_id)
        base = base_map.get(trade.trade_id)
        challenger = challenger_map.get(trade.trade_id)
        if mid is None:
            missing_mid += 1
            continue
        if (
            mid.status != "fresh"
            or mid.observed_timestamp_ms is None
            or mid.gross_r is None
        ):
            non_fresh_mid += 1
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
        if base.observation_lag_ms is None:
            non_evaluable_base += 1
            continue
        base_attempted_at_ms = (
            trade.opened_at_ms
            + BASE_DELAY_MS
            + base.observation_lag_ms
        )
        if (
            mid.status == "fresh"
            and mid.observed_timestamp_ms is not None
            and mid.observed_timestamp_ms > base_attempted_at_ms
        ):
            late_mid += 1
        try:
            evaluated.append(
                _item(
                    trade,
                    mid,
                    base,
                    challenger,
                )
            )
        except AdaptiveDelaySelectorError:
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
        and missing_mid == 0
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
        "candidate_id": ADAPTIVE_DELAY_SELECTOR_ID,
        "claim_scope": (
            "fill_weighted_same_exit_trade_contribution_only"
        ),
        "rule": (
            "if_fresh_available_1m_mid_gross_r_lt_0_choose_120s_"
            "else_choose_60s"
        ),
        "causality_rule": (
            "late_or_nonfresh_mid_falls_back_to_60s"
        ),
        "base_delay_ms": BASE_DELAY_MS,
        "challenger_delay_ms": CHALLENGER_DELAY_MS,
        "started_at_ms": started_at_ms,
        "prospective_closed_trades": len(prospective),
        "causal_evaluable_trades": len(items),
        "missing_mid_outcome": missing_mid,
        "non_fresh_mid_outcome": non_fresh_mid,
        "late_mid_signal": late_mid,
        "missing_base_outcome": missing_base,
        "missing_challenger_outcome": missing_challenger,
        "non_evaluable_base": non_evaluable_base,
        "non_evaluable_challenger": (
            non_evaluable_challenger
        ),
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
        "by_signal": {
            "adverse_available_choose_120s": _summary(
                tuple(
                    item
                    for item in items
                    if (
                        item.signal_available_at_decision
                        and item.markout_gross_r is not None
                        and item.markout_gross_r < ZERO
                    )
                )
            ),
            "otherwise_choose_60s": _summary(
                tuple(
                    item
                    for item in items
                    if item.selected_delay_ms == BASE_DELAY_MS
                )
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
