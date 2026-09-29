from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.journal.store import JournalStore
from cocomelon.research.delayed_entry_execution_shadow import (
    MIN_CLOSED_ELIGIBLE_TRADES,
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_capacity import (
    delayed_entry_capacity_cause,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    MIN_EVALUATED_DELAYED_ATTEMPTS,
    DelayedEntryFillWeightedError,
    evaluate_delayed_entry_fill_weighted_outcome,
)
from cocomelon.research.exact_decimal_aggregation import (
    exact_decimal_sum,
)

ZERO: Final = Decimal("0")


class DelayedEntryContributionDecompositionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryContributionDecompositionOutcome:
    trade_id: str
    opening_plan_id: str
    market: str
    direction: str
    source: str
    capacity_cause: str
    fill_fraction: Decimal
    actual_net_pnl: Decimal
    scaled_actual_net_pnl: Decimal
    candidate_net_pnl_estimate: Decimal
    price_effect_pnl: Decimal
    entry_fee_effect_pnl: Decimal
    exposure_effect_pnl: Decimal
    total_delta_pnl: Decimal
    price_effect_r: Decimal
    entry_fee_effect_r: Decimal
    exposure_effect_r: Decimal
    total_delta_r: Decimal

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
                    "decomposition identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if not ZERO <= self.fill_fraction <= Decimal("1"):
            raise ValueError(
                "fill_fraction must be between zero and one"
            )
        for metric in (
            self.actual_net_pnl,
            self.scaled_actual_net_pnl,
            self.candidate_net_pnl_estimate,
            self.price_effect_pnl,
            self.entry_fee_effect_pnl,
            self.exposure_effect_pnl,
            self.total_delta_pnl,
            self.price_effect_r,
            self.entry_fee_effect_r,
            self.exposure_effect_r,
            self.total_delta_r,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "decomposition economics must be finite"
                )
        if (
            self.price_effect_pnl
            + self.entry_fee_effect_pnl
            + self.exposure_effect_pnl
            != self.total_delta_pnl
        ):
            raise ValueError(
                "decomposition PnL effects must reconcile"
            )
        if (
            self.price_effect_r
            + self.entry_fee_effect_r
            + self.exposure_effect_r
            != self.total_delta_r
        ):
            raise ValueError(
                "decomposition R effects must reconcile"
            )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryContributionDecompositionError(
            "journal contains duplicate trade ids"
        )
    return by_id


def evaluate_delayed_entry_contribution_decomposition(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
) -> DelayedEntryContributionDecompositionOutcome:
    weighted = evaluate_delayed_entry_fill_weighted_outcome(
        trade,
        outcome,
    )
    fill_fraction = weighted.fill_fraction
    scaled_actual_net = trade.net_pnl * fill_fraction
    scaled_actual_gross = (
        trade.gross_realized_pnl * fill_fraction
    )
    scaled_actual_entry_fee = (
        trade.entry_fees * fill_fraction
    )

    quantity = weighted.delayed_filled_quantity
    if quantity == ZERO:
        candidate_gross = ZERO
    else:
        delayed_price = weighted.delayed_average_fill_price
        if delayed_price is None:
            raise DelayedEntryContributionDecompositionError(
                "filled delayed attempt is missing average fill price"
            )
        candidate_gross = (
            (trade.exit_price - delayed_price) * quantity
            if trade.direction.value == "long"
            else (delayed_price - trade.exit_price) * quantity
        )

    price_effect = candidate_gross - scaled_actual_gross
    entry_fee_effect = (
        scaled_actual_entry_fee
        - weighted.delayed_entry_fee
    )
    exposure_effect = scaled_actual_net - trade.net_pnl
    total_delta = (
        weighted.candidate_net_pnl_estimate
        - trade.net_pnl
    )
    if (
        price_effect
        + entry_fee_effect
        + exposure_effect
        != total_delta
    ):
        raise DelayedEntryContributionDecompositionError(
            "delayed-entry contribution decomposition does not reconcile"
        )

    risk = trade.initial_risk_amount
    if risk <= ZERO:
        raise DelayedEntryContributionDecompositionError(
            "initial risk must be positive"
        )
    price_effect_r = price_effect / risk
    entry_fee_effect_r = entry_fee_effect / risk
    exposure_effect_r = exposure_effect / risk
    total_delta_r = (
        price_effect_r
        + entry_fee_effect_r
        + exposure_effect_r
    )
    return DelayedEntryContributionDecompositionOutcome(
        trade_id=trade.trade_id,
        opening_plan_id=trade.opening_plan_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        capacity_cause=delayed_entry_capacity_cause(outcome),
        fill_fraction=fill_fraction,
        actual_net_pnl=trade.net_pnl,
        scaled_actual_net_pnl=scaled_actual_net,
        candidate_net_pnl_estimate=(
            weighted.candidate_net_pnl_estimate
        ),
        price_effect_pnl=price_effect,
        entry_fee_effect_pnl=entry_fee_effect,
        exposure_effect_pnl=exposure_effect,
        total_delta_pnl=total_delta,
        price_effect_r=price_effect_r,
        entry_fee_effect_r=entry_fee_effect_r,
        exposure_effect_r=exposure_effect_r,
        total_delta_r=total_delta_r,
    )


def _summary(
    items: tuple[
        DelayedEntryContributionDecompositionOutcome,
        ...,
    ],
) -> dict[str, object]:
    count = len(items)
    price_effect = exact_decimal_sum(
        item.price_effect_pnl for item in items
    )
    fee_effect = exact_decimal_sum(
        item.entry_fee_effect_pnl for item in items
    )
    exposure_effect = exact_decimal_sum(
        item.exposure_effect_pnl for item in items
    )
    total_delta = exact_decimal_sum(
        item.total_delta_pnl for item in items
    )
    economic_components = exact_decimal_sum(
        (price_effect, fee_effect, exposure_effect)
    )
    rounding_residual = exact_decimal_sum(
        (total_delta, -economic_components)
    )
    if (
        exact_decimal_sum(
            (economic_components, rounding_residual)
        )
        != total_delta
    ):
        raise DelayedEntryContributionDecompositionError(
            "summary rounding bridge does not reconcile"
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
        "price_effect_pnl": str(price_effect),
        "entry_fee_effect_pnl": str(fee_effect),
        "exposure_effect_pnl": str(exposure_effect),
        "total_delta_pnl": str(total_delta),
        "decimal_rounding_residual_pnl": str(
            rounding_residual
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
        "mean_total_delta_r": (
            None
            if count == 0
            else str(
                sum(
                    (item.total_delta_r for item in items),
                    ZERO,
                )
                / Decimal(count)
            )
        ),
        "price_benefit_positive": sum(
            1 for item in items if item.price_effect_pnl > ZERO
        ),
        "price_benefit_negative": sum(
            1 for item in items if item.price_effect_pnl < ZERO
        ),
        "exposure_effect_positive": sum(
            1
            for item in items
            if item.exposure_effect_pnl > ZERO
        ),
        "exposure_effect_negative": sum(
            1
            for item in items
            if item.exposure_effect_pnl < ZERO
        ),
    }


def delayed_entry_contribution_decomposition(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
) -> dict[str, object]:
    trades = _trade_map(journal)
    evaluated: list[
        DelayedEntryContributionDecompositionOutcome
    ] = []
    missing_journal = 0
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
                evaluate_delayed_entry_contribution_decomposition(
                    trade,
                    outcome,
                )
            )
        except (
            DelayedEntryFillWeightedError,
            DelayedEntryContributionDecompositionError,
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
        and lineage_mismatches == 0
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "fill_weighted_same_exit_delta_decomposition"
        ),
        "identity": (
            "price_effect + entry_fee_effect + "
            "exposure_effect = total_delta"
        ),
        "summary_identity": (
            "price_effect + entry_fee_effect + exposure_effect + "
            "decimal_rounding_residual = total_delta"
        ),
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_delayed_attempts": len(items),
        "missing_journal_trades": missing_journal,
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
