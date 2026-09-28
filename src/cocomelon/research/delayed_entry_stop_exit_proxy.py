from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.execution.funding import funding_cash_delta
from cocomelon.journal.store import JournalStore
from cocomelon.research.continuous_paper_trade_paths import (
    ContinuousPaperTradePathStore,
)
from cocomelon.research.delayed_entry_execution_shadow import (
    DELAY_MS,
    DelayedEntryOutcome,
)
from cocomelon.research.delayed_entry_fill_weighted import (
    EVALUABLE_SOURCES,
    DelayedEntryFillWeightedError,
    DelayedEntryFillWeightedOutcome,
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
    trade_funding_accruals,
)
from cocomelon.research.delayed_entry_stop_survivability import (
    DelayedEntryStopSurvivabilityError,
    DelayedEntryStopTimingError,
    evaluate_delayed_entry_stop_outcome,
)

ZERO: Final = Decimal("0")
ONE: Final = Decimal("1")
BPS: Final = Decimal("10000")
MIN_CLOSED_SHADOW_OUTCOMES: Final = 30
MIN_EVALUATED_FILLED_CANDIDATES: Final = 20


class DelayedEntryStopExitProxyError(RuntimeError):
    pass


class DelayedEntryStopExitTimingAmbiguityError(
    DelayedEntryStopExitProxyError
):
    pass


@dataclass(frozen=True, slots=True)
class DelayedEntryStopExitProxyOutcome:
    trade_id: str
    market: str
    direction: str
    source: str
    stop_hit: bool
    actual_net_pnl: Decimal
    same_exit_candidate_net_pnl: Decimal
    candidate_open_ms: int
    stop_hit_ms: int | None
    delayed_entry_price: Decimal
    delayed_filled_quantity: Decimal
    original_stop: Decimal
    first_crossing_mark: Decimal | None
    ioc_slippage_boundary_price: Decimal | None
    funding_through_stop: Decimal | None
    stop_price_proxy_net_pnl: Decimal | None
    crossing_mark_proxy_net_pnl: Decimal | None
    ioc_boundary_proxy_net_pnl: Decimal | None

    def __post_init__(self) -> None:
        for identity in (
            self.trade_id,
            self.market,
            self.direction,
            self.source,
        ):
            if not identity.strip():
                raise ValueError(
                    "stop-exit proxy identity must not be empty"
                )
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.candidate_open_ms < 0:
            raise ValueError("candidate_open_ms must be non-negative")
        for metric in (
            self.actual_net_pnl,
            self.same_exit_candidate_net_pnl,
            self.delayed_entry_price,
            self.delayed_filled_quantity,
            self.original_stop,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "stop-exit proxy economics must be finite"
                )
        if (
            self.delayed_entry_price <= ZERO
            or self.delayed_filled_quantity <= ZERO
            or self.original_stop <= ZERO
        ):
            raise ValueError(
                "stop-exit proxy prices and quantity must be positive"
            )

        optional_values = (
            self.stop_hit_ms,
            self.first_crossing_mark,
            self.ioc_slippage_boundary_price,
            self.funding_through_stop,
            self.stop_price_proxy_net_pnl,
            self.crossing_mark_proxy_net_pnl,
            self.ioc_boundary_proxy_net_pnl,
        )
        present = tuple(value is not None for value in optional_values)
        if self.stop_hit and not all(present):
            raise ValueError(
                "stop-hit proxy outcome requires all stop economics"
            )
        if not self.stop_hit and any(present):
            raise ValueError(
                "surviving proxy outcome must not contain stop economics"
            )

        if not self.stop_hit:
            return

        stop_hit_ms = self.stop_hit_ms
        crossing = self.first_crossing_mark
        boundary = self.ioc_slippage_boundary_price
        stop_net = self.stop_price_proxy_net_pnl
        mark_net = self.crossing_mark_proxy_net_pnl
        boundary_net = self.ioc_boundary_proxy_net_pnl
        funding = self.funding_through_stop
        if (
            stop_hit_ms is None
            or crossing is None
            or boundary is None
            or stop_net is None
            or mark_net is None
            or boundary_net is None
            or funding is None
        ):
            raise ValueError("stop-hit proxy outcome is incomplete")
        if stop_hit_ms <= self.candidate_open_ms:
            raise ValueError(
                "stop trigger must occur after delayed candidate open"
            )
        for metric in (
            crossing,
            boundary,
            stop_net,
            mark_net,
            boundary_net,
            funding,
        ):
            if not metric.is_finite():
                raise ValueError(
                    "stop-hit proxy economics must be finite"
                )
        if crossing <= ZERO or boundary <= ZERO:
            raise ValueError(
                "stop proxy exit prices must be positive"
            )

        if self.direction == "long":
            if not boundary <= crossing <= self.original_stop:
                raise ValueError(
                    "long stop proxy prices must worsen monotonically"
                )
        else:
            if not boundary >= crossing >= self.original_stop:
                raise ValueError(
                    "short stop proxy prices must worsen monotonically"
                )
        if not stop_net >= mark_net >= boundary_net:
            raise ValueError(
                "stop proxy net PnL must worsen monotonically"
            )


def _trade_map(
    journal: JournalStore,
) -> dict[str, TradeJournalEntry]:
    trades = tuple(journal.iter_trades())
    by_id = {trade.trade_id: trade for trade in trades}
    if len(by_id) != len(trades):
        raise DelayedEntryStopExitProxyError(
            "journal contains duplicate trade ids"
        )
    return by_id


def _path_map(
    store: ContinuousPaperTradePathStore,
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in store.iter_payloads():
        trade_id = raw.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id.strip():
            raise DelayedEntryStopExitProxyError(
                "trade path trade_id must be non-empty"
            )
        if trade_id in result:
            raise DelayedEntryStopExitProxyError(
                "duplicate exact trade path"
            )
        result[trade_id] = raw
    return result


def _funding_through_stop(
    trade: TradeJournalEntry,
    weighted: DelayedEntryFillWeightedOutcome,
    funding_loader: FundingLoader,
    *,
    candidate_open_ms: int,
    stop_hit_ms: int,
) -> Decimal:
    accruals = trade_funding_accruals(
        trade,
        funding_loader,
    )
    if any(
        accrual.boundary_ms == stop_hit_ms
        for accrual in accruals
    ):
        raise DelayedEntryStopExitTimingAmbiguityError(
            "funding boundary coincides with stop trigger"
        )

    return sum(
        (
            funding_cash_delta(
                accrual.signed_quantity
                * weighted.fill_fraction,
                accrual.oracle_price,
                accrual.funding_rate,
            )
            for accrual in accruals
            if (
                candidate_open_ms
                < accrual.boundary_ms
                < stop_hit_ms
            )
        ),
        ZERO,
    )


def _gross_pnl(
    *,
    direction: str,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    if direction == "long":
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def _net_proxy(
    *,
    direction: str,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    entry_fee: Decimal,
    funding: Decimal,
    taker_fee_rate: Decimal,
) -> Decimal:
    exit_fee = exit_price * quantity * taker_fee_rate
    return (
        _gross_pnl(
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
        )
        - entry_fee
        - exit_fee
        + funding
    )


def _ioc_boundary_price(
    *,
    direction: str,
    reference_price: Decimal,
    max_ioc_slippage_bps: Decimal,
) -> Decimal:
    fraction = max_ioc_slippage_bps / BPS
    if direction == "long":
        return reference_price * (ONE - fraction)
    return reference_price * (ONE + fraction)


def evaluate_delayed_entry_stop_exit_proxy(
    trade: TradeJournalEntry,
    outcome: DelayedEntryOutcome,
    weighted: DelayedEntryFillWeightedOutcome,
    raw_path: Mapping[str, object],
    funding_loader: FundingLoader,
    config: PaperExecutionConfig,
    *,
    delay_ms: int = DELAY_MS,
) -> DelayedEntryStopExitProxyOutcome | None:
    if weighted.delayed_filled_quantity == ZERO:
        return None

    corrected = (
        evaluate_delayed_entry_funding_corrected_fill_weighted_outcome(
            trade,
            outcome,
            weighted,
            funding_loader,
            delay_ms=delay_ms,
        )
    )
    stop = evaluate_delayed_entry_stop_outcome(
        trade,
        outcome,
        weighted,
        raw_path,
        delay_ms=delay_ms,
    )
    if stop is None:
        raise DelayedEntryStopExitProxyError(
            "filled delayed candidate has no stop outcome"
        )

    if not stop.stop_hit:
        return DelayedEntryStopExitProxyOutcome(
            trade_id=trade.trade_id,
            market=trade.market.canonical,
            direction=trade.direction.value,
            source=outcome.source,
            stop_hit=False,
            actual_net_pnl=trade.net_pnl,
            same_exit_candidate_net_pnl=(
                corrected.corrected_candidate_net_pnl
            ),
            candidate_open_ms=stop.candidate_open_ms,
            stop_hit_ms=None,
            delayed_entry_price=stop.delayed_entry_price,
            delayed_filled_quantity=(
                stop.delayed_filled_quantity
            ),
            original_stop=stop.original_stop,
            first_crossing_mark=None,
            ioc_slippage_boundary_price=None,
            funding_through_stop=None,
            stop_price_proxy_net_pnl=None,
            crossing_mark_proxy_net_pnl=None,
            ioc_boundary_proxy_net_pnl=None,
        )

    stop_hit_ms = stop.first_stop_hit_ms
    crossing_mark = stop.first_stop_mark_px
    if stop_hit_ms is None or crossing_mark is None:
        raise DelayedEntryStopExitProxyError(
            "stop crossing is missing trigger evidence"
        )

    funding = _funding_through_stop(
        trade,
        weighted,
        funding_loader,
        candidate_open_ms=stop.candidate_open_ms,
        stop_hit_ms=stop_hit_ms,
    )
    boundary = _ioc_boundary_price(
        direction=trade.direction.value,
        reference_price=crossing_mark,
        max_ioc_slippage_bps=config.max_ioc_slippage_bps,
    )
    quantity = weighted.delayed_filled_quantity
    entry_price = stop.delayed_entry_price
    entry_fee = weighted.delayed_entry_fee

    stop_net = _net_proxy(
        direction=trade.direction.value,
        entry_price=entry_price,
        exit_price=stop.original_stop,
        quantity=quantity,
        entry_fee=entry_fee,
        funding=funding,
        taker_fee_rate=config.taker_fee_rate,
    )
    mark_net = _net_proxy(
        direction=trade.direction.value,
        entry_price=entry_price,
        exit_price=crossing_mark,
        quantity=quantity,
        entry_fee=entry_fee,
        funding=funding,
        taker_fee_rate=config.taker_fee_rate,
    )
    boundary_net = _net_proxy(
        direction=trade.direction.value,
        entry_price=entry_price,
        exit_price=boundary,
        quantity=quantity,
        entry_fee=entry_fee,
        funding=funding,
        taker_fee_rate=config.taker_fee_rate,
    )

    return DelayedEntryStopExitProxyOutcome(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        source=outcome.source,
        stop_hit=True,
        actual_net_pnl=trade.net_pnl,
        same_exit_candidate_net_pnl=(
            corrected.corrected_candidate_net_pnl
        ),
        candidate_open_ms=stop.candidate_open_ms,
        stop_hit_ms=stop_hit_ms,
        delayed_entry_price=entry_price,
        delayed_filled_quantity=quantity,
        original_stop=stop.original_stop,
        first_crossing_mark=crossing_mark,
        ioc_slippage_boundary_price=boundary,
        funding_through_stop=funding,
        stop_price_proxy_net_pnl=stop_net,
        crossing_mark_proxy_net_pnl=mark_net,
        ioc_boundary_proxy_net_pnl=boundary_net,
    )


def _sum_proxy(
    values: Sequence[DelayedEntryStopExitProxyOutcome],
    field: str,
) -> Decimal:
    total = ZERO
    for item in values:
        proxy = getattr(item, field)
        if not isinstance(proxy, Decimal):
            raise DelayedEntryStopExitProxyError(
                f"{field} is missing on stop-crossed outcome"
            )
        total += proxy
    return total


def _summary(
    items: Sequence[DelayedEntryStopExitProxyOutcome],
) -> dict[str, object]:
    values = tuple(items)
    crossed = tuple(item for item in values if item.stop_hit)
    survived = tuple(item for item in values if not item.stop_hit)

    actual = sum(
        (item.actual_net_pnl for item in values),
        ZERO,
    )
    same_exit = sum(
        (item.same_exit_candidate_net_pnl for item in values),
        ZERO,
    )
    survivor_same_exit = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in survived
        ),
        ZERO,
    )
    crossed_same_exit = sum(
        (
            item.same_exit_candidate_net_pnl
            for item in crossed
        ),
        ZERO,
    )
    crossed_stop = _sum_proxy(
        crossed,
        "stop_price_proxy_net_pnl",
    )
    crossed_mark = _sum_proxy(
        crossed,
        "crossing_mark_proxy_net_pnl",
    )
    crossed_boundary = _sum_proxy(
        crossed,
        "ioc_boundary_proxy_net_pnl",
    )

    stop_total = survivor_same_exit + crossed_stop
    mark_total = survivor_same_exit + crossed_mark
    boundary_total = survivor_same_exit + crossed_boundary

    return {
        "filled_candidates": len(values),
        "definite_original_stop_crossings": len(crossed),
        "survived_observed_path_to_actual_close": len(survived),
        "actual_net_pnl": str(actual),
        "same_exit_candidate_net_pnl": str(same_exit),
        "same_exit_candidate_pnl_on_stop_crossings": str(
            crossed_same_exit
        ),
        "stop_price_proxy_pnl_on_stop_crossings": str(
            crossed_stop
        ),
        "crossing_mark_proxy_pnl_on_stop_crossings": str(
            crossed_mark
        ),
        "ioc_boundary_proxy_pnl_on_stop_crossings": str(
            crossed_boundary
        ),
        "stop_price_proxy_cohort_net_pnl": str(stop_total),
        "crossing_mark_proxy_cohort_net_pnl": str(mark_total),
        "ioc_boundary_proxy_cohort_net_pnl": str(
            boundary_total
        ),
        "same_exit_delta_vs_actual": str(same_exit - actual),
        "stop_price_proxy_delta_vs_actual": str(
            stop_total - actual
        ),
        "crossing_mark_proxy_delta_vs_actual": str(
            mark_total - actual
        ),
        "ioc_boundary_proxy_delta_vs_actual": str(
            boundary_total - actual
        ),
        "same_exit_minus_ioc_boundary_proxy_pnl": str(
            same_exit - boundary_total
        ),
        "positive_same_exit_crossings_to_nonpositive_boundary": sum(
            1
            for item in crossed
            if (
                item.same_exit_candidate_net_pnl > ZERO
                and item.ioc_boundary_proxy_net_pnl is not None
                and item.ioc_boundary_proxy_net_pnl <= ZERO
            )
        ),
        "ioc_boundary_proxy_positive_crossings": sum(
            1
            for item in crossed
            if (
                item.ioc_boundary_proxy_net_pnl is not None
                and item.ioc_boundary_proxy_net_pnl > ZERO
            )
        ),
        "mean_stop_to_ioc_boundary_proxy_spread": (
            None
            if not crossed
            else str(
                sum(
                    (
                        item.stop_price_proxy_net_pnl
                        - item.ioc_boundary_proxy_net_pnl
                        for item in crossed
                        if (
                            item.stop_price_proxy_net_pnl
                            is not None
                            and item.ioc_boundary_proxy_net_pnl
                            is not None
                        )
                    ),
                    ZERO,
                )
                / Decimal(len(crossed))
            )
        ),
    }


def delayed_entry_stop_exit_proxy_range(
    journal: JournalStore,
    outcomes: tuple[DelayedEntryOutcome, ...],
    path_store: ContinuousPaperTradePathStore,
    funding_loader: FundingLoader,
    config: PaperExecutionConfig,
    *,
    delay_ms: int = DELAY_MS,
) -> dict[str, object]:
    if delay_ms <= 0:
        raise ValueError("delay_ms must be positive")

    trades = _trade_map(journal)
    if len({outcome.trade_id for outcome in outcomes}) != len(
        outcomes
    ):
        raise DelayedEntryStopExitProxyError(
            "delayed shadow contains duplicate trade ids"
        )
    paths = _path_map(path_store)

    evaluated: list[DelayedEntryStopExitProxyOutcome] = []
    unresolved_outcomes = 0
    candidate_no_fill = 0
    missing_journal = 0
    missing_paths = 0
    incomplete_or_gapped_paths = 0
    missing_funding_events = 0
    ambiguous_stop_funding_timing = 0
    lineage_mismatches = 0
    invalid_candidate_timing = 0

    for outcome in outcomes:
        if outcome.source not in EVALUABLE_SOURCES:
            unresolved_outcomes += 1
            continue
        trade = trades.get(outcome.trade_id)
        if trade is None:
            missing_journal += 1
            continue
        try:
            weighted = evaluate_delayed_entry_fill_weighted_outcome(
                trade,
                outcome,
            )
        except DelayedEntryFillWeightedError:
            lineage_mismatches += 1
            continue

        if weighted.delayed_filled_quantity == ZERO:
            candidate_no_fill += 1
            continue

        raw_path = paths.get(trade.trade_id)
        if raw_path is None:
            missing_paths += 1
            continue
        if (
            raw_path.get("path_complete") is not True
            or raw_path.get("known_gap_intervals") != []
        ):
            incomplete_or_gapped_paths += 1
            continue

        try:
            proxy = evaluate_delayed_entry_stop_exit_proxy(
                trade,
                outcome,
                weighted,
                raw_path,
                funding_loader,
                config,
                delay_ms=delay_ms,
            )
        except DelayedEntryFundingMissingError:
            missing_funding_events += 1
            continue
        except DelayedEntryStopTimingError:
            invalid_candidate_timing += 1
            continue
        except DelayedEntryStopExitTimingAmbiguityError:
            ambiguous_stop_funding_timing += 1
            continue
        except (
            DelayedEntryFundingCorrectedFillError,
            DelayedEntryFundingError,
            DelayedEntryStopSurvivabilityError,
            DelayedEntryStopExitProxyError,
            ValueError,
        ):
            lineage_mismatches += 1
            continue

        if proxy is None:
            lineage_mismatches += 1
            continue
        evaluated.append(proxy)

    items = tuple(evaluated)
    ready = (
        len(outcomes) >= MIN_CLOSED_SHADOW_OUTCOMES
        and len(items) >= MIN_EVALUATED_FILLED_CANDIDATES
        and unresolved_outcomes == 0
        and missing_journal == 0
        and missing_paths == 0
        and incomplete_or_gapped_paths == 0
        and missing_funding_events == 0
        and ambiguous_stop_funding_timing == 0
        and lineage_mismatches == 0
        and invalid_candidate_timing == 0
    )

    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "claim_scope": (
            "delayed_entry_stop_exit_full_quantity_proxy_range_only"
        ),
        "delay_ms": delay_ms,
        "stop_price_proxy": (
            "idealized_full_exit_at_immutable_original_stop"
        ),
        "crossing_mark_proxy": (
            "full_exit_at_first_observed_stop_crossing_mark"
        ),
        "ioc_boundary_proxy": (
            "full_exit_at_first_crossing_mark_plus_configured_"
            "max_ioc_slippage_boundary"
        ),
        "visible_exit_depth_modeled": False,
        "partial_stop_fill_modeled": False,
        "exact_stop_fill_price_modeled": False,
        "funding_at_exact_stop_timestamp_modeled": False,
        "taker_fee_rate": str(config.taker_fee_rate),
        "max_ioc_slippage_bps": str(
            config.max_ioc_slippage_bps
        ),
        "closed_shadow_outcomes": len(outcomes),
        "evaluated_filled_candidates": len(items),
        "candidate_no_fill_trades": candidate_no_fill,
        "unresolved_outcomes": unresolved_outcomes,
        "missing_journal_trades": missing_journal,
        "missing_exact_paths": missing_paths,
        "incomplete_or_gapped_paths": (
            incomplete_or_gapped_paths
        ),
        "missing_funding_events": missing_funding_events,
        "ambiguous_stop_funding_timing": (
            ambiguous_stop_funding_timing
        ),
        "lineage_mismatches": lineage_mismatches,
        "invalid_candidate_timing": invalid_candidate_timing,
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
            )
        },
        "readiness": {
            "ready_for_review": ready,
            "min_closed_shadow_outcomes": (
                MIN_CLOSED_SHADOW_OUTCOMES
            ),
            "min_evaluated_filled_candidates": (
                MIN_EVALUATED_FILLED_CANDIDATES
            ),
            "missing_closed_shadow_outcomes": max(
                0,
                MIN_CLOSED_SHADOW_OUTCOMES - len(outcomes),
            ),
            "missing_evaluated_filled_candidates": max(
                0,
                MIN_EVALUATED_FILLED_CANDIDATES - len(items),
            ),
        },
    }
