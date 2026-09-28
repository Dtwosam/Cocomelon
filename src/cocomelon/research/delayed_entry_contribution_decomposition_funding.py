from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_contribution_decomposition import (
    DelayedEntryContributionDecompositionError,
    evaluate_delayed_entry_contribution_decomposition,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DELAY_MS,
    MIN_CLOSED_ELIGIBLE_TRADES,
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    MIN_EVALUATED_DELAYED_ATTEMPTS,
    DelayedEntryFillWeightedError,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_fill_weighted_funding import (
    DelayedEntryFundingCorrectedFillError,
    evaluate_delayed_entry_funding_corrected_fill_weighted_outcome,
)
from cocomelon.research.delayed_entry_funding import (
    DelayedEntryFundingError,
    DelayedEntryFundingMissingError,
    FundingLoader,
)

ZERO: Final = Decimal("0")


class DelayedEntryFundingDecompositionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryFundingDecompositionOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    source: str
    capacity_cause: str
    fill_fraction: Decimal
    actual_net_pnl: Decimal
    legacy_candidate_net_pnl: Decimal
    corrected_candidate_net_pnl: Decimal
    price_effect_pnl: Decimal
    entry_fee_effect_pnl: Decimal
    exposure_effect_pnl: Decimal
    funding_timing_effect_pnl: Decimal
    legacy_total_delta_pnl: Decimal
    corrected_total_delta_pnl: Decimal
    price_effect_r: Decimal
    entry_fee_effect_r: Decimal
    exposure_effect_r: Decimal
    funding_timing_effect_r: Decimal
    corrected_total_delta_r: Decimal

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.opening_plan_id,
            self.market,
            self.direction,
            self.source,
            self.capacity_cause,
        ):
            if not identity.strip():
                raise ValueError(
                    "funding decomposition identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if not ZERO <= self.fill_fraction <= Decimal("1"):
            raise ValueError(
                "fill_fraction must be between zero and one"
            )
        for metric in (
            self.actual_net_pnl,
            self.legacy_candidate_net_pnl,
            self.corrected_candidate_net_pnl,
            self.price_effect_pnl,
            self.entry_fee_effect_pnl,
            self.exposure_effect_pnl,
            self.funding_timing_effect_pnl,
            self.legacy_total_delta_pnl,
            self.corrected_total_delta_pnl,
            self.price_effect_r,
            self.entry_fee_effect_r,
            self.exposure_effect_r,
            self.funding_timing_effect_r,
            self.corrected_total_delta_r,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "funding decomposition economics must be finite"
                )
        if (
            self.price_effect_pnl
            + self.entry_fee_effect_pnl
            + self.exposure_effect_pnl
            + self.funding_timing_effect_pnl
            != self.corrected_total_delta_pnl
        ):
            raise ValueError(
                "funding decomposition PnL effects must reconcile"
            )
        if (
            self.price_effect_r
            + self.entry_fee_effect_r
            + self.exposure_effect_r
            + self.funding_timing_effect_r
            != self.corrected_total_delta_r
        ):
            raise ValueError(
                "funding decomposition R effects must reconcile"
            )
        if (
            self.legacy_total_delta_pnl
            + self.funding_timing_effect_pnl
            != self.corrected_total_delta_pnl
        ):
            raise ValueError(
                "funding correction must bridge legacy and corrected delta"
            )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryFundingDecompositionError(
            "journal contains duplicate trade ids"
        )
    return by_id


def evaluate_delayed_entry_funding_decomposition(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    funding_loader: FundingLoader,
    *,
    delay_ms: int = DELAY_MS,
) -> DelayedEntryFundingDecompositionOutcome:
    legacy = evaluate_delayed_entry_contribution_decomposition(
        trade,
        outcome,
    )
    weighted = evaluate_delayed_entry_fill_weighted_outcome(
        trade,
        outcome,
    )
    corrected = (
        evaluate_delayed_entry_funding_corrected_fill_weighted_outcome(
            trade,
            outcome,
            weighted,
            funding_loader,
            delay_ms=delay_ms,
        )
    )
    funding_effect = corrected.funding_timing_delta_pnl
    corrected_delta = (
        legacy.total_delta_pnl + funding_effect
    )
    if (
        corrected_delta != corrected.corrected_delta_net_pnl
        or corrected.corrected_candidate_net_pnl
        != trade.net_pnl + corrected_delta
    ):
        raise DelayedEntryFundingDecompositionError(
            "corrected decomposition does not match corrected candidate"
        )
    risk = trade.initial_risk_amount
    if risk <= ZERO:
        raise DelayedEntryFundingDecompositionError(
            "initial risk must be positive"
        )

    funding_effect_r = funding_effect / risk
    corrected_total_r = corrected_delta / risk
    return DelayedEntryFundingDecompositionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        capacity_cause=legacy.capacity_cause,
        fill_fraction=legacy.fill_fraction,
        actual_net_pnl=trade.net_pnl,
        legacy_candidate_net_pnl=(
            legacy.candidate_net_pnl_estimate
        ),
        corrected_candidate_net_pnl=(
            corrected.corrected_candidate_net_pnl
        ),
        price_effect_pnl=legacy.price_effect_pnl,
        entry_fee_effect_pnl=legacy.entry_fee_effect_pnl,
        exposure_effect_pnl=legacy.exposure_effect_pnl,
        funding_timing_effect_pnl=funding_effect,
        legacy_total_delta_pnl=legacy.total_delta_pnl,
        corrected_total_delta_pnl=corrected_delta,
        price_effect_r=legacy.price_effect_r,
        entry_fee_effect_r=legacy.entry_fee_effect_r,
        exposure_effect_r=legacy.exposure_effect_r,
        funding_timing_effect_r=funding_effect_r,
        corrected_total_delta_r=corrected_total_r,
    )


def _summary(
    items: tuple[DelayedEntryFundingDecompositionOutcome, ...],
) -> dict[str, object]:
    count = len(items)
    price = sum(
        (item.price_effect_pnl for item in items),
        ZERO,
    )
    entry_fee = sum(
        (item.entry_fee_effect_pnl for item in items),
        ZERO,
    )
    exposure = sum(
        (item.exposure_effect_pnl for item in items),
        ZERO,
    )
    funding = sum(
        (item.funding_timing_effect_pnl for item in items),
        ZERO,
    )
    legacy_delta = sum(
        (item.legacy_total_delta_pnl for item in items),
        ZERO,
    )
    corrected_delta = sum(
        (item.corrected_total_delta_pnl for item in items),
        ZERO,
    )
    actual = sum(
        (item.actual_net_pnl for item in items),
        ZERO,
    )
    corrected_candidate = sum(
        (item.corrected_candidate_net_pnl for item in items),
        ZERO,
    )
    if (
        price + entry_fee + exposure + funding
        != corrected_delta
        or legacy_delta + funding != corrected_delta
        or actual + corrected_delta != corrected_candidate
    ):
        raise DelayedEntryFundingDecompositionError(
            "funding decomposition summary does not reconcile"
        )

    return {
        "trades": count,
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
        "price_effect_pnl": str(price),
        "entry_fee_effect_pnl": str(entry_fee),
        "exposure_effect_pnl": str(exposure),
        "funding_timing_effect_pnl": str(funding),
        "legacy_total_delta_pnl": str(legacy_delta),
        "corrected_total_delta_pnl": str(corrected_delta),
        "actual_net_pnl": str(actual),
        "corrected_candidate_net_pnl": str(
            corrected_candidate
        ),
        "mean_price_effect_r": (
            None
            if count == 0
            else str(
                sum(
                    (item.price_effect_r for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_entry_fee_effect_r": (
            None
            if count == 0
            else str(
                sum(
                    (item.entry_fee_effect_r for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_exposure_effect_r": (
            None
            if count == 0
            else str(
                sum(
                    (item.exposure_effect_r for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_funding_timing_effect_r": (
            None
            if count == 0
            else str(
                sum(
                    (item.funding_timing_effect_r for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "mean_corrected_total_delta_r": (
            None
            if count == 0
            else str(
                sum(
                    (item.corrected_total_delta_r for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "funding_correction_positive": sum(
            1
            for item in items
            if item.funding_timing_effect_pnl > ZERO
        ),
        "funding_correction_negative": sum(
            1
            for item in items
            if item.funding_timing_effect_pnl < ZERO
        ),
        "funding_correction_zero": sum(
            1
            for item in items
            if item.funding_timing_effect_pnl == ZERO
        ),
    }


def delayed_entry_funding_decomposition(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    funding_loader: FundingLoader,
    *,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")

    trades = _trade_map(journal)
    evaluated: list[DelayedEntryFundingDecompositionOutcome] = []
    missing_journal = 0
    missing_funding_events = 0
    lineage_mismatches = 0

    for outcome in outcomes:
        if outcome.source not in EVALUABLE_SOURCES:
            continue
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        try:
            evaluated.append(
                evaluate_delayed_entry_funding_decomposition(
                    trade,
                    outcome,
                    funding_loader,
                    delay_ms=delay_ms,
                )
            )
        except DelayedEntryFundingMissingError:
            missing_funding_events += 1
        except (
            DelayedEntryContributionDecompositionError,
            DelayedEntryFillWeightedError,
            DelayedEntryFundingCorrectedFillError,
            DelayedEntryFundingError,
            DelayedEntryFundingDecompositionError,
            ValueError,
        ):
            lineage_mismatches += 1

    items = tuple(evaluated)
    causes = sorted(
        {item.capacity_cause for item in items}
    )
    ready = (
        len(outcomes) >= MIN_CLOSED_ELIGIBLE_TRADES
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
            "funding_corrected_fill_weighted_same_exit_delta_decomposition"
        ),
        "identity": (
            "price_effect + entry_fee_effect + exposure_effect + "
            "funding_timing_effect = corrected_total_delta"
        ),
        "legacy_identity": (
            "price_effect + entry_fee_effect + exposure_effect = "
            "legacy_total_delta"
        ),
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_delayed_attempts": len(items),
        "missing_journal_trades": missing_journal,
        "missing_funding_events": missing_funding_events,
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
        "by_source": {
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
        },
        "by_capacity_cause": {
            cause: _summary(
                tuple(
                    item
                    for item in items
                    if item.capacity_cause == cause
                )
            )
            for cause in causes
        },
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": (
                MIN_CLOSED_ELIGIBLE_TRADES
            ),
            "min_evaluated_delayed_attempts": (
                MIN_EVALUATED_DELAYED_ATTEMPTS
            ),
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_ELIGIBLE_TRADES - len(outcomes),
            ),
            "missing_evaluated_delayed_attempts": max(
                0,
                MIN_EVALUATED_DELAYED_ATTEMPTS - len(items),
            ),
        },
    }
