from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    DELAY_MS,
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    MIN_EVALUATED_DELAYED_ATTEMPTS,
    DelayedEntryFillWeightedError,
    DelayedEntryFillWeightedOutcome,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_funding import (
    DelayedEntryFundingError,
    DelayedEntryFundingMissingError,
    FundingLoader,
    scaled_funding_events,
    trade_funding_accruals,
)

ZERO: Final = Decimal("0")
MIN_CLOSED_SHADOW_OUTCOMES: Final = 30


class DelayedEntryFundingCorrectedFillError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FundingCorrectedFillOutcome:
    trade_id: str
    market: str
    direction: str
    source: str
    fill_fraction: Decimal
    actual_net_pnl: Decimal
    actual_net_r: Decimal
    legacy_scaled_funding_pnl: Decimal
    exact_post_delay_funding_pnl: Decimal
    funding_timing_delta_pnl: Decimal
    legacy_candidate_net_pnl: Decimal
    corrected_candidate_net_pnl: Decimal
    corrected_candidate_r_contribution: Decimal
    corrected_delta_net_pnl: Decimal
    corrected_delta_r_contribution: Decimal

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.market,
            self.direction,
            self.source,
        ):
            if not identity.strip():
                raise ValueError(
                    "funding-corrected fill identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if not ZERO <= self.fill_fraction <= Decimal("1"):
            raise ValueError(
                "fill_fraction must be between zero and one"
            )
        for metric in (
            self.actual_net_pnl,
            self.actual_net_r,
            self.legacy_scaled_funding_pnl,
            self.exact_post_delay_funding_pnl,
            self.funding_timing_delta_pnl,
            self.legacy_candidate_net_pnl,
            self.corrected_candidate_net_pnl,
            self.corrected_candidate_r_contribution,
            self.corrected_delta_net_pnl,
            self.corrected_delta_r_contribution,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "funding-corrected economics must be finite"
                )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryFundingCorrectedFillError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _corrected_outcome(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    weighted: DelayedEntryFillWeightedOutcome,
    funding_loader: FundingLoader,
    *,
    delay_ms: int,
) -> FundingCorrectedFillOutcome:
    exact_funding = ZERO
    if weighted.delayed_filled_quantity > ZERO:
        lag_ms = outcome.observation_lag_ms
        if lag_ms is None or lag_ms < 0:
            raise DelayedEntryFundingCorrectedFillError(
                "filled delayed outcome is missing valid observation lag"
            )
        candidate_open_ms = (
            trade.opened_at_ms + delay_ms + lag_ms
        )
        if candidate_open_ms >= trade.closed_at_ms:
            raise DelayedEntryFundingCorrectedFillError(
                "filled delayed outcome opens after trade close"
            )
        accruals = trade_funding_accruals(
            trade,
            funding_loader,
        )
        exact_funding = sum(
            (
                cash_delta
                for _boundary_ms, cash_delta
                in scaled_funding_events(
                    accruals,
                    fill_fraction=weighted.fill_fraction,
                    open_ms=candidate_open_ms,
                )
            ),
            ZERO,
        )

    funding_delta = (
        exact_funding - weighted.scaled_funding_pnl
    )
    corrected_candidate = (
        weighted.candidate_net_pnl_estimate + funding_delta
    )
    corrected_r = (
        corrected_candidate / trade.initial_risk_amount
    )
    return FundingCorrectedFillOutcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        fill_fraction=weighted.fill_fraction,
        actual_net_pnl=trade.net_pnl,
        actual_net_r=trade.net_r,
        legacy_scaled_funding_pnl=(
            weighted.scaled_funding_pnl
        ),
        exact_post_delay_funding_pnl=exact_funding,
        funding_timing_delta_pnl=funding_delta,
        legacy_candidate_net_pnl=(
            weighted.candidate_net_pnl_estimate
        ),
        corrected_candidate_net_pnl=corrected_candidate,
        corrected_candidate_r_contribution=corrected_r,
        corrected_delta_net_pnl=(
            corrected_candidate - trade.net_pnl
        ),
        corrected_delta_r_contribution=(
            corrected_r - trade.net_r
        ),
    )


def _summary(
    items: tuple[FundingCorrectedFillOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    actual = sum(
        (item.actual_net_pnl for item in items),
        ZERO,
    )
    legacy = sum(
        (item.legacy_candidate_net_pnl for item in items),
        ZERO,
    )
    corrected = sum(
        (item.corrected_candidate_net_pnl for item in items),
        ZERO,
    )
    legacy_funding = sum(
        (item.legacy_scaled_funding_pnl for item in items),
        ZERO,
    )
    exact_funding = sum(
        (item.exact_post_delay_funding_pnl for item in items),
        ZERO,
    )
    corrected_r = sum(
        (
            item.corrected_candidate_r_contribution
            for item in items
        ),
        ZERO,
    )
    actual_r = sum(
        (item.actual_net_r for item in items),
        ZERO,
    )
    return {
        "trades": count,
        "actual_net_pnl": str(actual),
        "legacy_fill_weighted_candidate_net_pnl": str(legacy),
        "funding_corrected_candidate_net_pnl": str(corrected),
        "legacy_scaled_funding_pnl": str(legacy_funding),
        "exact_post_delay_funding_pnl": str(exact_funding),
        "funding_timing_delta_pnl": str(
            exact_funding - legacy_funding
        ),
        "corrected_delta_vs_actual_pnl": str(
            corrected - actual
        ),
        "corrected_delta_vs_legacy_pnl": str(
            corrected - legacy
        ),
        "corrected_better_than_actual": sum(
            1
            for item in items
            if item.corrected_candidate_net_pnl
            > item.actual_net_pnl
        ),
        "corrected_worse_than_actual": sum(
            1
            for item in items
            if item.corrected_candidate_net_pnl
            < item.actual_net_pnl
        ),
        "corrected_equal_to_actual": sum(
            1
            for item in items
            if item.corrected_candidate_net_pnl
            == item.actual_net_pnl
        ),
        "mean_fill_fraction": (
            None
            if count == 0
            else str(
                sum(
                    (item.fill_fraction for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "corrected_mean_r_contribution": (
            None
            if count == 0
            else str(corrected_r / Decimal(count))
        ),
        "corrected_mean_delta_r_contribution": (
            None
            if count == 0
            else str(
                (corrected_r - actual_r) / Decimal(count)
            )
        ),
    }


def delayed_entry_funding_corrected_fill_weighted(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    funding_loader: FundingLoader,
    *,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")

    trades = _trade_map(journal)
    evaluated: list[FundingCorrectedFillOutcome] = []
    missing_journal = 0
    missing_funding_events = 0
    lineage_mismatches = 0

    source_counts = {
        "full_visible_book_ioc": 0,
        "partial_visible_book_ioc": 0,
        "no_fill": 0,
        "censored_before_delay": 0,
        "missing_delayed_book": 0,
        "rejected": 0,
        "expired": 0,
    }

    for outcome in outcomes:
        source_counts[outcome.source] = (
            source_counts.get(outcome.source, 0) + 1
        )
        if outcome.source not in EVALUABLE_SOURCES:
            continue
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        try:
            weighted = (
                evaluate_delayed_entry_fill_weighted_outcome(
                    trade,
                    outcome,
                )
            )
            evaluated.append(
                _corrected_outcome(
                    trade,
                    outcome,
                    weighted,
                    funding_loader,
                    delay_ms=delay_ms,
                )
            )
        except DelayedEntryFundingMissingError:
            missing_funding_events += 1
        except (
            DelayedEntryFillWeightedError,
            DelayedEntryFundingError,
            DelayedEntryFundingCorrectedFillError,
            ValueError,
        ):
            lineage_mismatches += 1

    items = tuple(evaluated)
    by_side = {
        side: _summary(
            tuple(
                item
                for item in items
                if item.direction == side
            )
        )
        for side in ("long", "short")
    }
    by_source = {
        source: _summary(
            tuple(
                item
                for item in items
                if item.source == source
            )
        )
        for source in (
            "full_visible_book_ioc",
            "partial_visible_book_ioc",
            "no_fill",
        )
    }

    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and len(items) >= MIN_EVALUATED_DELAYED_ATTEMPTS
        and missing_journal == 0
        and missing_funding_events == 0
        and lineage_mismatches == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "funding_corrected_fill_weighted_same_exit_"
            "trade_contribution_only"
        ),
        "delay_ms": delay_ms,
        "exit_assumption": (
            "actual_exit_price_with_exit_fee_scaled_by_fill_fraction"
        ),
        "legacy_funding_assumption": (
            "actual_trade_funding_scaled_by_fill_fraction"
        ),
        "corrected_funding_assumption": (
            "recorded_funding_boundaries_strictly_after_delayed_open_"
            "with_recorded_boundary_quantity_scaled_by_fill_fraction"
        ),
        "unfilled_assumption": (
            "unfilled_quantity_contributes_zero_and_pays_no_funding"
        ),
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_delayed_attempts": len(items),
        "missing_journal_trades": missing_journal,
        "missing_funding_events": missing_funding_events,
        "lineage_mismatches": lineage_mismatches,
        "source_counts": source_counts,
        "overall": _summary(items),
        "by_side": by_side,
        "by_source": by_source,
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": (
                MIN_CLOSED_SHADOW_OUTCOMES
            ),
            "min_evaluated_delayed_attempts": (
                MIN_EVALUATED_DELAYED_ATTEMPTS
            ),
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_SHADOW_OUTCOMES - len(outcomes),
            ),
            "missing_evaluated_delayed_attempts": max(
                0,
                MIN_EVALUATED_DELAYED_ATTEMPTS - len(items),
            ),
        },
    }
