from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import OrderSide, PaperOrderPlan
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.strategy import Direction
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
    ContinuousPaperOpeningRankStore,
)
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
CANDIDATE_ID: Final = "prospective-top10-price-confirm-v1"
TOP10_MAX_ORDINAL: Final = 10
MAX_ACCEPTED_RANK_AGE_MS: Final = 300_000
DELAY_MS: Final = 60_000
MIN_PROSPECTIVE_EVALUATED_TRADES: Final = 30
MIN_ADMITTED_TRADES: Final = 10
MIN_SKIPPED_TRADES: Final = 10
MIN_LONG_TRADES: Final = 5
MIN_SHORT_TRADES: Final = 5


class ProspectiveTradeQualityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProspectiveTradeQualityState:
    started_at_ms: int
    schema_version: int = STATE_SCHEMA_VERSION
    candidate_id: str = CANDIDATE_ID

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError("unsupported trade-quality state schema")
        if self.candidate_id != CANDIDATE_ID:
            raise ValueError("unsupported trade-quality candidate")

    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "started_at_ms": self.started_at_ms,
            "rule": {
                "max_admitted_ordinal": TOP10_MAX_ORDINAL,
                "max_rank_age_ms": MAX_ACCEPTED_RANK_AGE_MS,
                "delay_ms": DELAY_MS,
                "minimum_signed_improvement_bps": "0",
                "direction_policy": "same_rule_for_long_and_short",
                "on_pass": "take_delayed_visible_book_ioc",
                "on_fail": "skip_trade_contribution",
            },
        }

    @classmethod
    def from_payload(
        cls,
        raw: object,
    ) -> ProspectiveTradeQualityState:
        if not isinstance(raw, dict):
            raise ProspectiveTradeQualityError(
                "trade-quality state must be an object"
            )
        expected_rule = {
            "max_admitted_ordinal": TOP10_MAX_ORDINAL,
            "max_rank_age_ms": MAX_ACCEPTED_RANK_AGE_MS,
            "delay_ms": DELAY_MS,
            "minimum_signed_improvement_bps": "0",
            "direction_policy": "same_rule_for_long_and_short",
            "on_pass": "take_delayed_visible_book_ioc",
            "on_fail": "skip_trade_contribution",
        }
        if raw.get("rule") != expected_rule:
            raise ProspectiveTradeQualityError(
                "trade-quality rule does not match frozen candidate"
            )
        schema = raw.get("schema_version")
        started = raw.get("started_at_ms")
        candidate = raw.get("candidate_id")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ProspectiveTradeQualityError(
                "schema_version must be an integer"
            )
        if isinstance(started, bool) or not isinstance(started, int):
            raise ProspectiveTradeQualityError(
                "started_at_ms must be an integer"
            )
        if not isinstance(candidate, str):
            raise ProspectiveTradeQualityError(
                "candidate_id must be a string"
            )
        try:
            return cls(
                started_at_ms=started,
                schema_version=schema,
                candidate_id=candidate,
            )
        except ValueError as exc:
            raise ProspectiveTradeQualityError(str(exc)) from exc


@dataclass(slots=True)
class _DirectionAccumulator:
    evaluated: int = 0
    admitted: int = 0
    skipped: int = 0
    actual_net_pnl: Decimal = ZERO
    candidate_net_pnl: Decimal = ZERO
    actual_net_r: Decimal = ZERO
    candidate_net_r: Decimal = ZERO

    def payload(self) -> dict[str, object]:
        return {
            "evaluated": self.evaluated,
            "admitted": self.admitted,
            "skipped": self.skipped,
            "actual_net_pnl": str(self.actual_net_pnl),
            "candidate_net_pnl": str(self.candidate_net_pnl),
            "delta_net_pnl": str(
                self.candidate_net_pnl - self.actual_net_pnl
            ),
            "actual_mean_net_r": (
                None
                if self.evaluated == 0
                else str(
                    self.actual_net_r / Decimal(self.evaluated)
                )
            ),
            "candidate_mean_net_r_contribution": (
                None
                if self.evaluated == 0
                else str(
                    self.candidate_net_r / Decimal(self.evaluated)
                )
            ),
        }


def _rank_for_trade(
    trade: TradeJournalEntry,
    store: ContinuousPaperOpeningRankStore,
) -> ContinuousPaperOpeningRankEvidence | None:
    evidence = store.load(trade.opening_plan_id)
    if evidence is None:
        return None
    if (
        evidence.market != trade.market.canonical
        or evidence.opened_at_ms != trade.opened_at_ms
    ):
        raise ProspectiveTradeQualityError(
            "trade-quality rank lineage does not match trade"
        )
    return evidence


def _outcome_map(
    outcomes: tuple[DelayedEntryOutcome, ...],
) -> dict[str, DelayedEntryOutcome]:
    by_id = {outcome.trade_id: outcome for outcome in outcomes}
    if len(by_id) != len(outcomes):
        raise ProspectiveTradeQualityError(
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
        raise ProspectiveTradeQualityError(
            "opening plan reference price is invalid"
        )
    expected_side = (
        OrderSide.BUY
        if trade.direction is Direction.LONG
        else OrderSide.SELL
    )
    if plan.side is not expected_side:
        raise ProspectiveTradeQualityError(
            "opening plan side does not match trade direction"
        )
    signed = (
        reference - price
        if plan.side is OrderSide.BUY
        else price - reference
    )
    return signed / reference * BPS


def prospective_trade_quality_summary(
    trades: tuple[TradeJournalEntry, ...],
    rank_store: ContinuousPaperOpeningRankStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    plan_loader: Callable[[str], PaperOrderPlan | None],
    state: ProspectiveTradeQualityState,
) -> dict[str, object]:
    prospective = tuple(
        sorted(
            (
                trade
                for trade in trades
                if trade.opened_at_ms >= state.started_at_ms
            ),
            key=lambda item: (item.opened_at_ms, item.trade_id),
        )
    )
    outcome_by_id = _outcome_map(outcomes)

    evaluated = 0
    admitted = 0
    skipped = 0
    rank_skips = 0
    worse_price_skips = 0
    no_fill_skips = 0
    missing_rank = 0
    stale_rank = 0
    missing_outcome = 0
    unresolved_outcome = 0
    missing_plan = 0
    lineage_mismatch = 0

    actual_net = ZERO
    candidate_net = ZERO
    actual_net_r = ZERO
    candidate_net_r = ZERO

    by_direction = {
        Direction.LONG.value: _DirectionAccumulator(),
        Direction.SHORT.value: _DirectionAccumulator(),
    }

    for trade in prospective:
        rank = _rank_for_trade(trade, rank_store)
        if rank is None:
            missing_rank += 1
            continue
        if rank.rank_age_ms > MAX_ACCEPTED_RANK_AGE_MS:
            stale_rank += 1
            continue

        direction_bucket = by_direction[trade.direction.value]

        if rank.ordinal > TOP10_MAX_ORDINAL:
            evaluated += 1
            skipped += 1
            rank_skips += 1
            actual_net += trade.net_pnl
            actual_net_r += trade.net_r
            direction_bucket.evaluated += 1
            direction_bucket.skipped += 1
            direction_bucket.actual_net_pnl += trade.net_pnl
            direction_bucket.actual_net_r += trade.net_r
            continue

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
        if plan.market != trade.market or plan.reduce_only:
            lineage_mismatch += 1
            continue

        evaluated += 1
        actual_net += trade.net_pnl
        actual_net_r += trade.net_r
        direction_bucket.evaluated += 1
        direction_bucket.actual_net_pnl += trade.net_pnl
        direction_bucket.actual_net_r += trade.net_r

        if outcome.source == "no_fill":
            skipped += 1
            no_fill_skips += 1
            direction_bucket.skipped += 1
            continue

        improvement = _signed_improvement_bps(
            trade,
            outcome,
            plan,
        )
        if improvement is None:
            lineage_mismatch += 1
            evaluated -= 1
            actual_net -= trade.net_pnl
            actual_net_r -= trade.net_r
            direction_bucket.evaluated -= 1
            direction_bucket.actual_net_pnl -= trade.net_pnl
            direction_bucket.actual_net_r -= trade.net_r
            continue
        if improvement < ZERO:
            skipped += 1
            worse_price_skips += 1
            direction_bucket.skipped += 1
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
            actual_net_r -= trade.net_r
            direction_bucket.evaluated -= 1
            direction_bucket.actual_net_pnl -= trade.net_pnl
            direction_bucket.actual_net_r -= trade.net_r
            continue

        admitted += 1
        candidate_net += weighted.candidate_net_pnl_estimate
        candidate_net_r += weighted.candidate_net_r_contribution
        direction_bucket.admitted += 1
        direction_bucket.candidate_net_pnl += (
            weighted.candidate_net_pnl_estimate
        )
        direction_bucket.candidate_net_r += (
            weighted.candidate_net_r_contribution
        )

    missing_total = max(
        0,
        MIN_PROSPECTIVE_EVALUATED_TRADES - evaluated,
    )
    missing_admitted = max(0, MIN_ADMITTED_TRADES - admitted)
    missing_skipped = max(0, MIN_SKIPPED_TRADES - skipped)
    long_evaluated = by_direction[Direction.LONG.value].evaluated
    short_evaluated = by_direction[Direction.SHORT.value].evaluated
    missing_long = max(0, MIN_LONG_TRADES - long_evaluated)
    missing_short = max(0, MIN_SHORT_TRADES - short_evaluated)

    integrity_clean = (
        missing_rank == 0
        and stale_rank == 0
        and missing_outcome == 0
        and unresolved_outcome == 0
        and missing_plan == 0
        and lineage_mismatch == 0
    )
    ready = (
        integrity_clean
        and missing_total == 0
        and missing_admitted == 0
        and missing_skipped == 0
        and missing_long == 0
        and missing_short == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "candidate_id": state.candidate_id,
        "started_at_ms": state.started_at_ms,
        "rule": state.payload()["rule"],
        "claim_scope": "prospective_closed_trade_contribution_only",
        "portfolio_counterfactual": False,
        "prospective_closed_trades": len(prospective),
        "evaluated_trades": evaluated,
        "admitted_trades": admitted,
        "skipped_trades": skipped,
        "rank_skips": rank_skips,
        "worse_price_skips": worse_price_skips,
        "no_fill_skips": no_fill_skips,
        "missing_rank_evidence": missing_rank,
        "stale_rank_evidence": stale_rank,
        "missing_delayed_outcomes": missing_outcome,
        "unresolved_delayed_outcomes": unresolved_outcome,
        "missing_opening_plans": missing_plan,
        "lineage_mismatches": lineage_mismatch,
        "actual_net_pnl": str(actual_net),
        "candidate_trade_contribution_pnl": str(candidate_net),
        "delta_trade_contribution_pnl": str(
            candidate_net - actual_net
        ),
        "actual_mean_net_r": (
            None
            if evaluated == 0
            else str(actual_net_r / Decimal(evaluated))
        ),
        "candidate_mean_net_r_contribution": (
            None
            if evaluated == 0
            else str(candidate_net_r / Decimal(evaluated))
        ),
        "by_direction": {
            direction: bucket.payload()
            for direction, bucket in by_direction.items()
        },
        "readiness": {
            "ready_for_review": ready,
            "integrity_clean": integrity_clean,
            "min_prospective_evaluated_trades": (
                MIN_PROSPECTIVE_EVALUATED_TRADES
            ),
            "min_admitted_trades": MIN_ADMITTED_TRADES,
            "min_skipped_trades": MIN_SKIPPED_TRADES,
            "min_long_trades": MIN_LONG_TRADES,
            "min_short_trades": MIN_SHORT_TRADES,
            "missing_prospective_evaluated_trades": missing_total,
            "missing_admitted_trades": missing_admitted,
            "missing_skipped_trades": missing_skipped,
            "missing_long_trades": missing_long,
            "missing_short_trades": missing_short,
        },
    }
