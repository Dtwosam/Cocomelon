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
DELAY_SELECTOR_COMPARISON_ID: Final = (
    "markout-vs-fill-aware-delay-v1"
)
DELAY_SELECTOR_COMPARISON_STATE_SCHEMA_VERSION: Final = 1
MIN_PROSPECTIVE_CLOSED_TRADES: Final = 30
MIN_CAUSAL_EVALUABLE_TRADES: Final = 20
MIN_DISAGREEMENT_TRADES: Final = 10


class DelaySelectorComparisonError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelaySelectorComparisonState:
    started_at_ms: int
    schema_version: int = (
        DELAY_SELECTOR_COMPARISON_STATE_SCHEMA_VERSION
    )
    candidate_id: str = DELAY_SELECTOR_COMPARISON_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if (
            self.schema_version
            != DELAY_SELECTOR_COMPARISON_STATE_SCHEMA_VERSION
        ):
            raise ValueError(
                "unsupported delay-selector comparison schema"
            )
        if self.candidate_id != DELAY_SELECTOR_COMPARISON_ID:
            raise ValueError(
                "unsupported delay-selector comparison candidate"
            )

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "comparison": (
                "adverse_1m_markout_selector_vs_"
                "60s_fill_quality_selector"
            ),
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> DelaySelectorComparisonState:
        if not isinstance(raw, dict):
            raise DelaySelectorComparisonError(
                "delay-selector comparison state must be an object"
            )
        schema_version = raw.get("schema_version")
        started_at_ms = raw.get("started_at_ms")
        candidate_id = raw.get("candidate_id")
        comparison = raw.get("comparison")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
        ):
            raise DelaySelectorComparisonError(
                "comparison schema_version must be an integer"
            )
        if (
            isinstance(started_at_ms, bool)
            or not isinstance(started_at_ms, int)
        ):
            raise DelaySelectorComparisonError(
                "comparison started_at_ms must be an integer"
            )
        if not isinstance(candidate_id, str):
            raise DelaySelectorComparisonError(
                "comparison candidate_id must be a string"
            )
        if comparison != (
            "adverse_1m_markout_selector_vs_"
            "60s_fill_quality_selector"
        ):
            raise DelaySelectorComparisonError(
                "comparison definition does not match frozen study"
            )
        try:
            return cls(
                started_at_ms=started_at_ms,
                schema_version=schema_version,
                candidate_id=candidate_id,
            )
        except ValueError as exc:
            raise DelaySelectorComparisonError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class DelaySelectorComparisonOutcome:
    trade_id: str
    market: str
    direction: str
    markout_delay_ms: int
    fill_aware_delay_ms: int
    base_source: str
    signal_available_at_60s: bool
    markout_gross_r: Decimal | None
    markout_candidate_pnl: Decimal
    fill_aware_candidate_pnl: Decimal
    fill_aware_minus_markout_pnl: Decimal
    disagreement: bool

    def __post_init__(self) -> None:
        for value in (
            self.trade_id,
            self.market,
            self.direction,
            self.base_source,
        ):
            if not value.strip():
                raise ValueError("comparison identity must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        valid_delays = {BASE_DELAY_MS, CHALLENGER_DELAY_MS}
        if self.markout_delay_ms not in valid_delays:
            raise ValueError("unsupported markout-selected delay")
        if self.fill_aware_delay_ms not in valid_delays:
            raise ValueError("unsupported fill-aware-selected delay")
        if self.disagreement != (
            self.markout_delay_ms != self.fill_aware_delay_ms
        ):
            raise ValueError("disagreement flag must reconcile")
        if (
            self.markout_gross_r is not None
            and not self.markout_gross_r.is_finite()
        ):
            raise ValueError("markout gross R must be finite")
        for metric in (
            self.markout_candidate_pnl,
            self.fill_aware_candidate_pnl,
            self.fill_aware_minus_markout_pnl,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "comparison economics must be finite"
                )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelaySelectorComparisonError(
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
        raise DelaySelectorComparisonError(
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
        raise DelaySelectorComparisonError(
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
        raise DelaySelectorComparisonError(
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
        raise DelaySelectorComparisonError(str(exc)) from exc


def _item(
    trade: TradeJournalEntry,
    mid: EntryMidMarkoutOutcome,
    base: DelayedEntryOutcome,
    challenger: DelayedEntryOutcome,
) -> DelaySelectorComparisonOutcome:
    _validate_mid_lineage(trade, mid)
    if base.observation_lag_ms is None:
        raise DelaySelectorComparisonError(
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

    markout_delay = (
        CHALLENGER_DELAY_MS
        if (
            signal_available
            and mid.gross_r is not None
            and mid.gross_r < ZERO
        )
        else BASE_DELAY_MS
    )
    fill_aware_delay = (
        BASE_DELAY_MS
        if base.source == "full_visible_book_ioc"
        else CHALLENGER_DELAY_MS
    )
    markout_item = (
        base_item
        if markout_delay == BASE_DELAY_MS
        else challenger_item
    )
    fill_aware_item = (
        base_item
        if fill_aware_delay == BASE_DELAY_MS
        else challenger_item
    )
    delta = (
        fill_aware_item.candidate_net_pnl_estimate
        - markout_item.candidate_net_pnl_estimate
    )
    return DelaySelectorComparisonOutcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        markout_delay_ms=markout_delay,
        fill_aware_delay_ms=fill_aware_delay,
        base_source=base.source,
        signal_available_at_60s=signal_available,
        markout_gross_r=mid.gross_r,
        markout_candidate_pnl=(
            markout_item.candidate_net_pnl_estimate
        ),
        fill_aware_candidate_pnl=(
            fill_aware_item.candidate_net_pnl_estimate
        ),
        fill_aware_minus_markout_pnl=delta,
        disagreement=(markout_delay != fill_aware_delay),
    )


def _summary(
    items: tuple[DelaySelectorComparisonOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    markout_pnl = sum(
        (item.markout_candidate_pnl for item in items),
        ZERO,
    )
    fill_pnl = sum(
        (item.fill_aware_candidate_pnl for item in items),
        ZERO,
    )
    delta = fill_pnl - markout_pnl
    return {
        "trades": count,
        "agreements": sum(
            1 for item in items if not item.disagreement
        ),
        "disagreements": sum(
            1 for item in items if item.disagreement
        ),
        "both_60s": sum(
            1
            for item in items
            if (
                item.markout_delay_ms == BASE_DELAY_MS
                and item.fill_aware_delay_ms == BASE_DELAY_MS
            )
        ),
        "both_120s": sum(
            1
            for item in items
            if (
                item.markout_delay_ms == CHALLENGER_DELAY_MS
                and item.fill_aware_delay_ms == CHALLENGER_DELAY_MS
            )
        ),
        "markout_60s_fill_120s": sum(
            1
            for item in items
            if (
                item.markout_delay_ms == BASE_DELAY_MS
                and item.fill_aware_delay_ms == CHALLENGER_DELAY_MS
            )
        ),
        "markout_120s_fill_60s": sum(
            1
            for item in items
            if (
                item.markout_delay_ms == CHALLENGER_DELAY_MS
                and item.fill_aware_delay_ms == BASE_DELAY_MS
            )
        ),
        "fill_aware_better": sum(
            1
            for item in items
            if item.fill_aware_minus_markout_pnl > ZERO
        ),
        "markout_better": sum(
            1
            for item in items
            if item.fill_aware_minus_markout_pnl < ZERO
        ),
        "equal_contribution": sum(
            1
            for item in items
            if item.fill_aware_minus_markout_pnl == ZERO
        ),
        "markout_selector_pnl": str(markout_pnl),
        "fill_aware_selector_pnl": str(fill_pnl),
        "fill_aware_minus_markout_pnl": str(delta),
        "mean_fill_aware_minus_markout_pnl": (
            None
            if count == 0
            else str(delta / Decimal(count))
        ),
    }


def delay_selector_comparison_summary(
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

    evaluated: list[DelaySelectorComparisonOutcome] = []
    missing_mid = 0
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
                    mid,
                    base,
                    challenger,
                )
            )
        except DelaySelectorComparisonError:
            lineage_mismatches += 1

    items = tuple(evaluated)
    disagreements = tuple(
        item for item in items if item.disagreement
    )
    ready = (
        len(prospective) >= MIN_PROSPECTIVE_CLOSED_TRADES
        and len(items) >= MIN_CAUSAL_EVALUABLE_TRADES
        and len(disagreements) >= MIN_DISAGREEMENT_TRADES
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
        "candidate_id": DELAY_SELECTOR_COMPARISON_ID,
        "claim_scope": (
            "paired_fill_weighted_same_exit_trade_contribution_only"
        ),
        "started_at_ms": started_at_ms,
        "prospective_closed_trades": len(prospective),
        "causal_evaluable_trades": len(items),
        "disagreement_trades": len(disagreements),
        "missing_mid_outcome": missing_mid,
        "missing_base_outcome": missing_base,
        "missing_challenger_outcome": missing_challenger,
        "non_evaluable_base": non_evaluable_base,
        "non_evaluable_challenger": non_evaluable_challenger,
        "lineage_mismatches": lineage_mismatches,
        "overall": _summary(items),
        "disagreements": _summary(disagreements),
        "by_side": {
            side: _summary(
                tuple(
                    item
                    for item in disagreements
                    if item.direction == side
                )
            )
            for side in ("long", "short")
        },
        "by_disagreement_type": {
            "markout_60s_fill_120s": _summary(
                tuple(
                    item
                    for item in disagreements
                    if (
                        item.markout_delay_ms == BASE_DELAY_MS
                        and item.fill_aware_delay_ms
                        == CHALLENGER_DELAY_MS
                    )
                )
            ),
            "markout_120s_fill_60s": _summary(
                tuple(
                    item
                    for item in disagreements
                    if (
                        item.markout_delay_ms
                        == CHALLENGER_DELAY_MS
                        and item.fill_aware_delay_ms
                        == BASE_DELAY_MS
                    )
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
            "min_disagreement_trades": MIN_DISAGREEMENT_TRADES,
            "missing_prospective_closed_trades": max(
                0,
                MIN_PROSPECTIVE_CLOSED_TRADES
                - len(prospective),
            ),
            "missing_causal_evaluable_trades": max(
                0,
                MIN_CAUSAL_EVALUABLE_TRADES - len(items),
            ),
            "missing_disagreement_trades": max(
                0,
                MIN_DISAGREEMENT_TRADES - len(disagreements),
            ),
        },
    }
