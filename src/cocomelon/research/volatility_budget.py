"""Frozen volatility-budget PAPER hypothesis, without source or execution authority.

Original receipts are required inputs, not proof of source custody. Warmup bars
retrieved now are available now, never retroactively. Missing source produces an
UNKNOWN signal distinct from a known noncrossing. Independent ordinary eligibility,
risk, accounting, durable cooldown and account locks remain caller obligations.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.features import EligibilityDecision
from cocomelon.domain.market import FundingRate, MarketId, PerpMarketSnapshot
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.features.microstructure import calculate_microstructure_features

D = Decimal
ZERO = D("0")
BPS = D("10000")
DAY_MS = 86_400_000
EIGHT_HOURS_MS = DAY_MS // 3
POLICY = "volatility-budget-adjustment-v1"
PROTOCOL_SHA256 = "eca2816e42a1a0409737e179b45761a8a4ad0ebb2149ee7ad956b6867caffdaa"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class Native8hBar:
    market: MarketId
    open_time_ms: int
    native_close_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trade_count: int
    received_at_ms: int
    source: str = "hyperliquid-mainnet-info"
    schema_version: int = 1
    interval: str = "8h"

    @property
    def canonical_close_time_ms(self) -> int:
        return self.native_close_time_ms + 1


@dataclass(frozen=True, slots=True)
class VolatilityBudgetWindow:
    market: MarketId
    decision_time_ms: int
    bars: tuple[Native8hBar, ...]
    book: StreamEvent | None
    eligibility: EligibilityDecision
    funding: FundingRate | None
    snapshot: PerpMarketSnapshot | None = None

    def __post_init__(self) -> None:
        if not _integer(self.decision_time_ms) or self.decision_time_ms < 0:
            raise ValueError("decision_time_ms must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class VolatilityBudgetPlan:
    decision: StrategyDecision
    entry: Decimal | None
    target: Decimal | None
    stop: Decimal | None
    expires_at_ms: int
    cost_bps: Decimal
    evidence_digest: str
    signal_direction: Direction | None
    sigma28: Decimal | None
    stop_distance_bps: Decimal | None
    current_eligible: bool = False


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _variance(values: tuple[Decimal, ...]) -> Decimal:
    mean = sum(values, ZERO) / len(values)
    return sum(((value - mean) ** 2 for value in values), ZERO) / (len(values) - 1)


def crossing_direction_from_variances(
    *,
    prior_variance7: Decimal,
    prior_variance28: Decimal,
    variance7: Decimal,
    variance28: Decimal,
) -> Direction | None:
    """Compare squared ratios using exact rational thresholds, never rounded q.

    None is UNKNOWN; NO_TRADE is a known absence of either crossing. Zero short
    variance is valid; either unknown/zero 28-return denominator is not.
    """
    values = (prior_variance7, prior_variance28, variance7, variance28)
    if any(not value.is_finite() or value < 0 for value in values):
        return None
    if prior_variance28 == 0 or variance28 == 0:
        return None

    # Integer ratios retain exact finite-Decimal comparisons even near a boundary,
    # independently of the ambient Decimal precision and exponent limits.
    def compare(left: Decimal, multiplier: int, right: Decimal, other: int) -> int:
        ln, ld = left.as_integer_ratio()
        rn, rd = right.as_integer_ratio()
        a, b = ln * multiplier * rd, rn * other * ld
        return (a > b) - (a < b)

    if (
        compare(prior_variance7, 4, prior_variance28, 9) < 0
        and compare(variance7, 4, variance28, 9) >= 0
    ):
        return Direction.SHORT
    if (
        compare(prior_variance7, 9, prior_variance28, 4) > 0
        and compare(variance7, 9, variance28, 4) <= 0
    ):
        return Direction.LONG
    return Direction.NO_TRADE


def _daily_closes(window: VolatilityBudgetWindow) -> tuple[Decimal, ...]:
    if len(window.bars) != 90:
        raise ValueError("invalid_bar_count")
    midnight = window.decision_time_ms - 30_000
    first_start = midnight - 30 * DAY_MS
    for index, bar in enumerate(window.bars):
        if (
            bar.market != window.market
            or bar.interval != "8h"
            or bar.source != "hyperliquid-mainnet-info"
            or not _integer(bar.schema_version)
            or bar.schema_version != 1
        ):
            raise ValueError("invalid_bar_provenance")
        if (
            not _integer(bar.open_time_ms)
            or not _integer(bar.native_close_time_ms)
            or bar.open_time_ms != first_start + index * EIGHT_HOURS_MS
            or bar.native_close_time_ms != bar.open_time_ms + EIGHT_HOURS_MS - 1
        ):
            raise ValueError("invalid_bar_grid")
        if (
            not _integer(bar.received_at_ms)
            or not bar.canonical_close_time_ms <= bar.received_at_ms < window.decision_time_ms
        ):
            raise ValueError("invalid_bar_receipt")
        if (
            not all(_positive(v) for v in (bar.open, bar.high, bar.low, bar.close, bar.volume))
            or not _integer(bar.trade_count)
            or bar.trade_count <= 0
            or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        ):
            raise ValueError("invalid_bar_values")
    return tuple(window.bars[index].close for index in range(2, 90, 3))


def _context_valid(window: VolatilityBudgetWindow) -> bool:
    snapshot = window.snapshot
    if snapshot is None:
        return False
    meta, context = snapshot.meta, snapshot.context
    return (
        snapshot.source == "hyperliquid-mainnet-info"
        and _integer(snapshot.schema_version)
        and snapshot.schema_version == 1
        and _integer(snapshot.received_at_ms)
        and 0 <= window.decision_time_ms - snapshot.received_at_ms <= 5000
        and meta.market == context.market == window.market
        and meta.wire_name == window.market.wire_name
        and meta.is_delisted is False
        and meta.only_isolated is False
        and meta.margin_mode in (None, "cross")
        and _integer(meta.max_leverage)
        and meta.max_leverage >= 1
        and (
            meta.margin_table_id is None
            or (_integer(meta.margin_table_id) and meta.margin_table_id >= 0)
        )
        and _integer(meta.sz_decimals)
        and 0 <= meta.sz_decimals <= 18
        and _positive(context.mark_px)
        and _positive(context.mid_px)
        and _positive(context.oracle_px)
        and _positive(context.day_ntl_vlm)
        and context.day_ntl_vlm >= D("10000000")
        and _positive(context.open_interest)
        and context.mark_px is not None
        and context.open_interest * context.mark_px >= D("5000000")
    )


def evaluate_volatility_budget(window: VolatilityBudgetWindow) -> VolatilityBudgetPlan:
    """Evaluate exact daily source in supplied order with deterministic Decimal logs."""
    with localcontext(_CONTEXT):
        return _evaluate(window)


def _evaluate(window: VolatilityBudgetWindow) -> VolatilityBudgetPlan:
    t = window.decision_time_ms
    digest = hashlib.sha256(
        json.dumps(
            {"protocol": PROTOCOL_SHA256, "window": asdict(window)},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    signal: Direction | None = None
    sigma28: Decimal | None = None
    distance: Decimal | None = None
    current_eligible = False

    def plan(
        reason: str,
        direction: Direction = Direction.NO_TRADE,
        entry: Decimal | None = None,
        target: Decimal | None = None,
        stop: Decimal | None = None,
        costs: Decimal = ZERO,
    ) -> VolatilityBudgetPlan:
        decision = StrategyDecision(
            window.market,
            direction,
            ZERO,
            t,
            digest,
            None if direction is Direction.NO_TRADE else POLICY,
            stop,
            (),
            (reason,),
        )
        return VolatilityBudgetPlan(
            decision,
            entry,
            target,
            stop,
            t + 2000,
            costs,
            digest,
            signal,
            sigma28,
            distance,
            current_eligible,
        )

    if window.market.dex or window.market.coin not in ("BTC", "ETH", "SOL", "BNB"):
        return plan("outside_frozen_scope")
    if t % DAY_MS != 30_000 or t < 30 * DAY_MS:
        return plan("off_decision_grid")
    try:
        closes = _daily_closes(window)
    except ValueError as error:
        return plan(str(error))
    returns = tuple((b / a).ln() for a, b in zip(closes, closes[1:], strict=False))
    variance28 = _variance(returns[-28:])
    signal = crossing_direction_from_variances(
        prior_variance7=_variance(returns[-8:-1]),
        prior_variance28=_variance(returns[:-1]),
        variance7=_variance(returns[-7:]),
        variance28=variance28,
    )
    if signal is None:
        return plan("volatility_unknown")
    sigma28 = variance28.sqrt()
    distance = max(D("100"), BPS * sigma28)
    if signal is Direction.NO_TRADE:
        return plan("no_crossing")
    if (
        window.eligibility.market != window.market
        or window.eligibility.rankable is not True
        or window.eligibility.deep_ready is not True
    ):
        return plan("ordinary_eligibility_failed")
    if not _context_valid(window):
        return plan("current_context_unavailable")
    book = window.book
    if book is None:
        return plan("book_unavailable")
    delta = book.receive_time - EPOCH
    received = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    if (
        book.market != window.market
        or book.kind is not StreamKind.L2_BOOK
        or book.source != "hyperliquid-mainnet-ws"
        or not _integer(book.schema_version)
        or book.schema_version != 1
        or delta.microseconds % 1000
        or not _integer(book.exchange_time_ms)
        or book.exchange_time_ms is None
        or not 0 <= t - received <= 1000
        or not 0 <= t - book.exchange_time_ms <= 1000
        or book.exchange_time_ms > received
    ):
        return plan("invalid_predecision_book")
    try:
        for side in ("bids", "asks"):
            raw = book.payload.get(side)
            if not isinstance(raw, (list, tuple)):
                raise ValueError("invalid_levels")
            prices = [value.get("px") for value in raw if isinstance(value, Mapping)]
            if len(set(prices)) != len(raw):
                raise ValueError("duplicate_levels")
        features = calculate_microstructure_features(book, as_of_ms=t)
    except (ValueError, TypeError):
        return plan("invalid_predecision_book")
    if features.spread_bps > 5:
        return plan("spread_too_wide")
    if min(features.bid_depth_25bps, features.ask_depth_25bps) < 10000:
        return plan("visible_depth_insufficient")
    current_eligible = True
    funding = window.funding
    if (
        funding is None
        or funding.market != window.market
        or funding.source != "hyperliquid-mainnet-info"
        or not _integer(funding.schema_version)
        or funding.schema_version != 1
        or not isinstance(funding.funding_rate, Decimal)
        or not funding.funding_rate.is_finite()
        or not _integer(funding.time_ms)
        or not _integer(funding.received_at_ms)
        or not 0 <= funding.time_ms <= funding.received_at_ms <= t
        or not 0 <= t - funding.received_at_ms <= 5000
        or not 0 <= t - funding.time_ms <= 5000
    ):
        return plan("funding_unavailable")
    costs = D("19") + features.spread_bps + 25 * abs(funding.funding_rate) * BPS
    if costs > 50:
        return plan("cost_reserve_exceeded", costs=costs)
    if 2 * distance < 4 * costs:
        return plan("target_room_insufficient", costs=costs)
    long = signal is Direction.LONG
    entry = features.best_ask_px if long else features.best_bid_px
    sign = D(1) if long else D(-1)
    stop = entry * (1 - sign * distance / BPS)
    target = entry * (1 + sign * 2 * distance / BPS)
    if not _positive(stop) or not _positive(target):
        return plan("nonpositive_geometry", costs=costs)
    return plan("volatility_budget_qualified", signal, entry, target, stop, costs)


def quantity_for_plan(
    plan: VolatilityBudgetPlan,
    *,
    equity: Decimal,
    executable_entry: Decimal,
    contra_depth_25bp: Decimal,
    sz_decimals: int,
    now_ms: int,
    independent_reserve_bps: Decimal = ZERO,
) -> Decimal:
    """Cap allocation; fixed geometry and independent risk may reduce/reject further.

    Use the greater of the frozen stop risk and actual executable stop risk, plus
    the greater cost reserve. Never reanchor a stop/target to a later quote.
    """
    with localcontext(_CONTEXT):
        if (
            plan.decision.direction is Direction.NO_TRADE
            or plan.entry is None
            or plan.stop is None
            or plan.target is None
            or plan.stop_distance_bps is None
            or not _integer(now_ms)
            or not plan.decision.timestamp_ms + 250 <= now_ms < plan.expires_at_ms
            or not _integer(sz_decimals)
            or not 0 <= sz_decimals <= 18
            or not all(_positive(v) for v in (equity, executable_entry, contra_depth_25bp))
            or equity <= 9950
            or not independent_reserve_bps.is_finite()
            or independent_reserve_bps < 0
            or not plan.cost_bps.is_finite()
            or plan.cost_bps < 0
        ):
            return ZERO
        long = plan.decision.direction is Direction.LONG
        if not (
            plan.stop < executable_entry < plan.target
            if long
            else plan.target < executable_entry < plan.stop
        ):
            return ZERO
        # IOC cap is adverse-only; a genuine favorable quote remains acceptable.
        if (long and executable_entry > plan.entry * D("1.0025")) or (
            not long and executable_entry < plan.entry * D(".9975")
        ):
            return ZERO
        reserve = max(plan.cost_bps, independent_reserve_bps)
        risk_bps = max(
            plan.stop_distance_bps,
            abs(executable_entry - plan.stop) / executable_entry * BPS,
        )
        notional = min(
            D(".001") * equity / ((risk_bps + reserve) / BPS),
            D(".25") * equity,
            D(".05") * contra_depth_25bp,
        )
        return (notional / executable_entry).quantize(
            D(1).scaleb(-sz_decimals), rounding=ROUND_DOWN
        )


def exit_reason(
    plan: VolatilityBudgetPlan,
    *,
    executable_price: Decimal | None,
    first_fill_ms: int,
    now_ms: int,
) -> str | None:
    """Protective stop, target, then 24h from first actual fill; intent is not a fill."""
    if plan.decision.direction is Direction.NO_TRADE or plan.stop is None or plan.target is None:
        return None
    if (
        not _integer(first_fill_ms)
        or not _integer(now_ms)
        or not plan.decision.timestamp_ms <= first_fill_ms <= now_ms
    ):
        raise ValueError("invalid_fill_clock")
    if executable_price is not None:
        if not _positive(executable_price):
            raise ValueError("invalid_executable_price")
        long = plan.decision.direction is Direction.LONG
        if (long and executable_price <= plan.stop) or (not long and executable_price >= plan.stop):
            return "stop"
        if (long and executable_price >= plan.target) or (
            not long and executable_price <= plan.target
        ):
            return "target"
    return "max_hold" if now_ms - first_fill_ms >= DAY_MS else None
