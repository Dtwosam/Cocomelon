from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import OrderSide, PaperOrderPlan
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

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")
STATE_SCHEMA_VERSION: Final = 1
CANDIDATE_ID: Final = "prospective-60s-price-confirm-v1"
MIN_PROSPECTIVE_EVALUATED_TRADES: Final = 30
MIN_CONFIRMED_TRADES: Final = 10
MIN_SKIPPED_TRADES: Final = 10


class ProspectiveDelayedPriceConfirmationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveDelayedPriceConfirmationState:
    started_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported price-confirm state schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported price-confirm candidate")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "delay_ms": 60_000,
                "minimum_signed_improvement_bps": "0",
                "on_pass": "take_delayed_visible_book_ioc",
                "on_fail": "skip_trade_contribution",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveDelayedPriceConfirmationState:
        if not isinstance(raw, dict):
            raise ProspectiveDelayedPriceConfirmationError(
                "price-confirm state must be an object"
            )
        expected_rule = {
            "delay_ms": 60_000,
            "minimum_signed_improvement_bps": "0",
            "on_pass": "take_delayed_visible_book_ioc",
            "on_fail": "skip_trade_contribution",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveDelayedPriceConfirmationError(
                "price-confirm rule does not match frozen candidate"
            )
        schema = raw.get("schema_version")
        started = raw.get("started_at_ms")
        candidate = raw.get("candidate_id")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ProspectiveDelayedPriceConfirmationError(
                "schema_version must be an integer"
            )
        if isinstance(started, bool) or not isinstance(started, int):
            raise ProspectiveDelayedPriceConfirmationError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate, str):
            raise ProspectiveDelayedPriceConfirmationError(
                "candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started,
                schema_version=schema,
                candidate_id=candidate,
            )
        except ValueError as exc:
            raise ProspectiveDelayedPriceConfirmationError(
                str(exc)
            ) from exc


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise ProspectiveDelayedPriceConfirmationError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _outcome_map(
    outcomes: tuple[DelayedEntryOutcome, ...],
) -> dict[str, DelayedEntryOutcome]:
    by_id = {outcome.trade_id: outcome for outcome in outcomes}
    if len(by_id) != len(outcomes):
        raise ProspectiveDelayedPriceConfirmationError(
            "delayed shadow contains duplicate trade ids"
        )
    return by_id


def _signed_improvement_bps(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    plan: PaperOrderPlan,
) -> Decimal | None:
    price = outcome.delayed_average_fill_price
    if price is None:
        return None
    reference = plan.execution_reference_price
    if reference <= ZERO or not reference.is_finite():
        raise ProspectiveDelayedPriceConfirmationError(
            "opening plan reference price is invalid"
        )
    if plan.side is OrderSide.BUY:
        signed = reference - price
    else:
        signed = price - reference
    return signed / reference * BPS


def prospective_delayed_price_confirmation_summary(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    plan_loader: Callable[[str], PaperOrderPlan | None],
    state: ProspectiveDelayedPriceConfirmationState,
) -> dict[str, object]:
    trades = _trade_map(journal)
    outcome_by_id = _outcome_map(outcomes)

    prospective_trades = tuple(
        trade
        for trade in trades.values()
        if trade.opened_at_ms >= state.started_at_ms
    )
    evaluated = 0
    confirmed = 0
    skipped = 0
    no_fill_skips = 0
    worse_price_skips = 0
    actual_net = ZERO
    candidate_net = ZERO
    confirmed_improvement = ZERO
    confirmed_improvement_count = 0
    missing_outcome = 0
    missing_plan = 0
    lineage_mismatch = 0
    unresolved_outcome = 0

    for trade in sorted(
        prospective_trades,
        key=lambda item: (
            item.opened_at_ms,
            item.trade_id,
        ),
    ):
        outcome = outcome_by_id.get(trade.trade_id)
        if outcome is None:
            missing_outcome += 1
            continue
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcome += 1
            continue
        if (
            outcome.opening_plan_id != trade.opening_plan_id
            or outcome.market != trade.market.canonical
            or outcome.direction != trade.direction.value
        ):
            lineage_mismatch += 1
            continue
        plan = plan_loader(trade.opening_plan_id)
        if plan is None:
            missing_plan += 1
            continue
        expected_side = (
            OrderSide.BUY
            if trade.direction.value == "long"
            else OrderSide.SELL
        )
        if (
            plan.market != trade.market
            or plan.side is not expected_side
            or plan.reduce_only
        ):
            lineage_mismatch += 1
            continue

        evaluated += 1
        actual_net += trade.net_pnl

        improvement = _signed_improvement_bps(
            trade,
            outcome,
            plan,
        )
        if outcome.source == "no_fill":
            skipped += 1
            no_fill_skips += 1
            continue
        if improvement is None:
            lineage_mismatch += 1
            evaluated -= 1
            actual_net -= trade.net_pnl
            continue
        if improvement < ZERO:
            skipped += 1
            worse_price_skips += 1
            continue

        try:
            weighted = evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                outcome,
            )
        except DelayedEntryFillWeightedError:
            lineage_mismatch += 1
            evaluated -= 1
            actual_net -= trade.net_pnl
            continue

        confirmed += 1
        candidate_net += weighted.candidate_net_pnl_estimate
        confirmed_improvement += improvement
        confirmed_improvement_count += 1

    missing_total = max(
        0,
        MIN_PROSPECTIVE_EVALUATED_TRADES - evaluated,
    )
    missing_confirmed = max(
        0,
        MIN_CONFIRMED_TRADES - confirmed,
    )
    missing_skipped = max(
        0,
        MIN_SKIPPED_TRADES - skipped,
    )
    ready = (
        missing_total == 0
        and missing_confirmed == 0
        and missing_skipped == 0
        and missing_outcome == 0
        and missing_plan == 0
        and lineage_mismatch == 0
        and unresolved_outcome == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "claim_scope": "closed_trade_contribution_only",
        "portfolio_counterfactual": False,
        "rule": state.payload()["rule"],
        "prospective_closed_trades": len(prospective_trades),
        "evaluated_trades": evaluated,
        "confirmed_trades": confirmed,
        "skipped_trades": skipped,
        "no_fill_skips": no_fill_skips,
        "worse_price_skips": worse_price_skips,
        "missing_outcomes": missing_outcome,
        "missing_opening_plans": missing_plan,
        "lineage_mismatches": lineage_mismatch,
        "unresolved_outcomes": unresolved_outcome,
        "actual_net_pnl": str(actual_net),
        "candidate_trade_contribution_pnl": str(candidate_net),
        "delta_trade_contribution_pnl": str(
            candidate_net - actual_net
        ),
        "mean_confirmed_signed_improvement_bps": (
            None
            if confirmed_improvement_count == 0
            else str(
                confirmed_improvement
                / Decimal(confirmed_improvement_count)
            )
        ),
        "readiness": {
            "ready_for_review": ready,
            "min_prospective_evaluated_trades": (
                MIN_PROSPECTIVE_EVALUATED_TRADES
            ),
            "min_confirmed_trades": MIN_CONFIRMED_TRADES,
            "min_skipped_trades": MIN_SKIPPED_TRADES,
            "missing_prospective_evaluated_trades": missing_total,
            "missing_confirmed_trades": missing_confirmed,
            "missing_skipped_trades": missing_skipped,
        },
    }
