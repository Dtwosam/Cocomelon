"""Frozen exploratory PAPER policy; no execution or source-authentication authority.

``coverage_complete`` is an externally authenticated caller obligation covering the
entire original tape/window and its gaps. Neither that boolean, a source label,
nor the digest below proves venue completeness. Synthetic fixtures prove logic
only. This module neither admits a research campaign nor approves independent
risk, margin, minimum notional, account limits or actual execution.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.features import EligibilityDecision
from cocomelon.domain.market import FundingRate, MarketId
from cocomelon.domain.strategy import Direction, StrategyDecision
from cocomelon.domain.stream import StreamEvent, StreamKind

D = Decimal
ZERO = D("0")
BPS = D("10000")
POLICY = "temporary-pressure-visible-recovery-v1"
PROTOCOL_SHA256 = "c248746bbe4cd36fa63233b32bd643e368f2d20c63b0e973cf39ffd515873057"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FlowExhaustionWindow:
    market: MarketId
    decision_time_ms: int
    events: tuple[StreamEvent, ...]
    coverage_complete: bool
    eligibility: EligibilityDecision
    funding: FundingRate | None

    def __post_init__(self) -> None:
        if not _integer(self.decision_time_ms) or self.decision_time_ms < 0:
            raise ValueError("decision_time_ms must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class FlowExhaustionPlan:
    decision: StrategyDecision
    entry: Decimal | None
    target: Decimal | None
    stop: Decimal | None
    expires_at_ms: int
    cost_bps: Decimal
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class _Book:
    received: int
    exchange: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    bid: Decimal
    ask: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2


@dataclass(frozen=True, slots=True)
class _Trade:
    received: int
    side: str
    price: Decimal
    notional: Decimal


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError("invalid_positive_decimal")
    return value


def _received(event: StreamEvent) -> int:
    delta = event.receive_time - EPOCH
    if delta.microseconds % 1000:
        raise ValueError("non_millisecond_receipt")
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000


def _digest(window: FlowExhaustionWindow) -> str:
    payload = {
        "protocol": PROTOCOL_SHA256,
        "market": window.market.canonical,
        "decision_time_ms": window.decision_time_ms,
        "coverage_complete": window.coverage_complete,
        "eligibility": [
            window.eligibility.market.canonical,
            window.eligibility.rankable,
            window.eligibility.deep_ready,
            window.eligibility.reasons,
        ],
        "funding": None
        if window.funding is None
        else [
            window.funding.market.canonical,
            window.funding.time_ms,
            window.funding.received_at_ms,
            window.funding.funding_rate,
            window.funding.premium,
            window.funding.source,
            window.funding.schema_version,
        ],
        "events": [
            [
                e.kind,
                e.market.canonical,
                e.exchange_time_ms,
                e.receive_time.isoformat(),
                e.schema_version,
                e.source,
                e.event_key,
                dict(e.payload),
            ]
            for e in window.events
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _levels(payload: Mapping[str, object], side: str) -> tuple[tuple[Decimal, Decimal], ...]:
    raw = payload.get(side)
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError("invalid_book")
    result: list[tuple[Decimal, Decimal]] = []
    prices: set[Decimal] = set()
    for row in raw:
        if not isinstance(row, Mapping):
            raise ValueError("invalid_book")
        px, sz = _positive(row.get("px")), _positive(row.get("sz"))
        if px in prices:
            raise ValueError("duplicate_book_price")
        prices.add(px)
        result.append((px, sz))
    return tuple(result)


def _parse(window: FlowExhaustionWindow) -> tuple[list[_Book], list[_Trade]]:
    books: list[_Book] = []
    trades: list[_Trade] = []
    keys: set[str] = set()
    tids: set[tuple[int, int]] = set()
    book_ids: set[tuple[int, str]] = set()
    previous_receipt = -1
    exchange_clocks: dict[StreamKind, int] = {}
    for event in window.events:
        received = _received(event)
        if received < previous_receipt:
            raise ValueError("receipt_clock_regression")
        previous_receipt = received
        if received > window.decision_time_ms:
            raise ValueError("future_receipt")
        if received < window.decision_time_ms - 690_000:
            raise ValueError("event_outside_window")
        if (
            event.market != window.market
            or event.source != "hyperliquid-mainnet-ws"
            or event.schema_version != 1
            or event.kind not in (StreamKind.TRADE, StreamKind.L2_BOOK)
        ):
            raise ValueError("invalid_event_provenance")
        exchange = event.exchange_time_ms
        if not _integer(exchange) or exchange is None or not 0 <= received - exchange <= 2000:
            raise ValueError("invalid_exchange_clock")
        if exchange < exchange_clocks.get(event.kind, -1):
            raise ValueError("exchange_clock_regression")
        exchange_clocks[event.kind] = exchange
        if event.event_key in keys:
            raise ValueError("duplicate_event")
        keys.add(event.event_key)
        if event.kind is StreamKind.TRADE:
            tid = event.payload.get("tid")
            if not isinstance(tid, int) or isinstance(tid, bool) or tid < 0:
                raise ValueError("invalid_trade_identity")
            if (exchange, tid) in tids:
                raise ValueError("duplicate_trade")
            tids.add((exchange, tid))
            side = event.payload.get("side")
            if side not in ("B", "A") or not isinstance(side, str):
                raise ValueError("invalid_trade_side")
            price, size = (
                _positive(event.payload.get("price")),
                _positive(event.payload.get("size")),
            )
            trades.append(_Trade(received, side, price, price * size))
        else:
            bids, asks = _levels(event.payload, "bids"), _levels(event.payload, "asks")
            bid, ask = max(px for px, _ in bids), min(px for px, _ in asks)
            if bid >= ask:
                raise ValueError("crossed_book")
            identity = (
                exchange,
                json.dumps(dict(event.payload), sort_keys=True, default=str),
            )
            if identity in book_ids:
                raise ValueError("duplicate_book")
            book_ids.add(identity)
            books.append(_Book(received, exchange, bids, asks, bid, ask))
    return books, trades


def _room(
    direction: Direction,
    entry: Decimal,
    target: Decimal,
    stop: Decimal,
    cost_bps: Decimal,
) -> bool:
    distance = entry - stop if direction is Direction.LONG else stop - entry
    reward = target - entry if direction is Direction.LONG else entry - target
    return (
        distance > 0
        and distance / entry * BPS <= 100
        and reward >= 2 * distance
        and reward >= 2 * entry * cost_bps / BPS
    )


def evaluate_flow_exhaustion(window: FlowExhaustionWindow) -> FlowExhaustionPlan:
    """Evaluate with deterministic arithmetic independent of the caller context."""
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return _evaluate_flow_exhaustion(window)


def _evaluate_flow_exhaustion(window: FlowExhaustionWindow) -> FlowExhaustionPlan:
    """Evaluate original receipt order without sorting, repair or source certification."""
    digest = _digest(window)
    t = window.decision_time_ms

    def plan(
        reason: str,
        direction: Direction = Direction.NO_TRADE,
        entry: Decimal | None = None,
        target: Decimal | None = None,
        stop: Decimal | None = None,
        costs: Decimal = ZERO,
    ) -> FlowExhaustionPlan:
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
        return FlowExhaustionPlan(decision, entry, target, stop, t + 2000, costs, digest)

    if window.market.dex:
        return plan("native_market_required")
    if t % 30_000 or t < 690_000:
        return plan("off_decision_grid")
    if window.coverage_complete is not True:
        return plan("incomplete_external_coverage")
    if (
        window.eligibility.market != window.market
        or window.eligibility.rankable is not True
        or window.eligibility.deep_ready is not True
    ):
        return plan("ordinary_eligibility_failed")
    funding = window.funding
    if (
        funding is None
        or funding.market != window.market
        or funding.source != "hyperliquid-mainnet-info"
        or funding.schema_version != 1
        or not funding.funding_rate.is_finite()
        or not _integer(funding.time_ms)
        or not _integer(funding.received_at_ms)
        or not 0 <= funding.time_ms <= funding.received_at_ms <= t
        or funding.time_ms // 3_600_000 != t // 3_600_000
    ):
        return plan("funding_unavailable")
    try:
        books, trades = _parse(window)
    except ValueError as error:
        return plan(str(error))
    books = [b for b in books if b.received >= t - 90_000]
    if (
        not books
        or books[0].received > t - 89_000
        or t - books[-1].received > 1000
        or t - books[-1].exchange > 1000
        or any(b.received - a.received > 2000 for a, b in zip(books, books[1:], strict=False))
        or any(b.exchange - a.exchange > 2000 for a, b in zip(books, books[1:], strict=False))
    ):
        return plan("incomplete_book_coverage")
    baseline = [ZERO] * 10
    baseline_counts = [0] * 10
    for trade in trades:
        if t - 690_000 <= trade.received < t - 90_000:
            index = (trade.received - (t - 690_000)) // 60_000
            baseline[index] += trade.notional
            baseline_counts[index] += 1
    if not all(baseline_counts):
        return plan("baseline_minute_missing")
    pressure = [trade for trade in trades if t - 90_000 <= trade.received < t - 30_000]
    total = sum((trade.notional for trade in pressure), ZERO)
    if len(pressure) < 20 or total < 3 * sum(baseline, ZERO) / 10:
        return plan("pressure_insufficient")
    buys = sum((trade.notional for trade in pressure if trade.side == "B"), ZERO)
    if max(buys, total - buys) < D(".70") * total:
        return plan("pressure_not_dominant")
    long = buys < total / 2
    direction = Direction.LONG if long else Direction.SHORT
    original_side = "A" if long else "B"
    pressure_books = [b for b in books if b.received < t - 30_000]
    if not pressure_books:
        return plan("incomplete_book_coverage")
    anchor, pressure_last = pressure_books[0], pressure_books[-1]
    sign = D("-1") if long else D("1")
    if sign * (pressure_last.mid - anchor.mid) / anchor.mid * BPS < 40:
        return plan("displacement_insufficient")
    # min/max preserve the FIRST extreme on ties, using original receipt order.
    extreme = (
        min(pressure_books, key=lambda b: b.mid)
        if long
        else max(pressure_books, key=lambda b: b.mid)
    )
    latest = books[-1]
    confirmation_books = [b for b in books if b.received >= t - 30_000]
    if any(sign * (b.mid - extreme.mid) / extreme.mid * BPS > 5 for b in confirmation_books):
        return plan("confirmation_new_extreme")
    if -sign * (latest.mid - extreme.mid) / extreme.mid * BPS < 10:
        return plan("reversal_insufficient")
    low = extreme.bid * D(".999") if long else extreme.ask
    high = extreme.bid if long else extreme.ask * D("1.001")

    def depth(book: _Book) -> Decimal:
        return sum(
            (px * sz for px, sz in (book.bids if long else book.asks) if low <= px <= high),
            ZERO,
        )

    extreme_depth = depth(extreme)
    before_response = [b for b in books if b.received <= t - 10_000]
    recovery = before_response[-1]
    if t - 10_000 - recovery.received > 1000 or t - 10_000 - recovery.exchange > 1000:
        return plan("incomplete_book_coverage")
    if (
        extreme_depth <= 0
        or depth(latest) < D("1.5") * extreme_depth
        or depth(recovery) < D("1.5") * extreme_depth
    ):
        return plan("fixed_band_not_recovered")
    executed = sum(
        (
            trade.notional
            for trade in trades
            if t - 30_000 <= trade.received < t - 10_000
            and trade.side == original_side
            and low <= trade.price <= high
        ),
        ZERO,
    )
    if executed < extreme_depth:
        return plan("fixed_band_execution_insufficient")
    response = [trade for trade in trades if trade.received >= t - 10_000]
    response_total = sum((trade.notional for trade in response), ZERO)
    opposing = sum((trade.notional for trade in response if trade.side != original_side), ZERO)
    if len(response) < 5 or opposing < D(".55") * response_total:
        return plan("opposing_response_insufficient")
    spread = (latest.ask - latest.bid) / latest.mid * BPS
    if spread > 5:
        return plan("spread_too_wide")
    costs = D("19") + spread + 2 * abs(funding.funding_rate) * BPS
    entry = latest.ask if long else latest.bid
    stop = extreme.mid * (D(".999") if long else D("1.001"))
    target = anchor.mid
    if not _room(direction, entry, target, stop, costs):
        return plan("target_room_insufficient")
    return plan("flow_exhaustion_qualified", direction, entry, target, stop, costs)


def quantity_for_plan(
    plan: FlowExhaustionPlan,
    *,
    equity: Decimal,
    executable_entry: Decimal,
    contra_depth_25bp: Decimal,
    sz_decimals: int,
    now_ms: int,
) -> Decimal:
    """Return a deterministic cost-reserved cap; independent approvals remain required."""
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return _quantity_for_plan(
            plan,
            equity=equity,
            executable_entry=executable_entry,
            contra_depth_25bp=contra_depth_25bp,
            sz_decimals=sz_decimals,
            now_ms=now_ms,
        )


def _quantity_for_plan(
    plan: FlowExhaustionPlan,
    *,
    equity: Decimal,
    executable_entry: Decimal,
    contra_depth_25bp: Decimal,
    sz_decimals: int,
    now_ms: int,
) -> Decimal:
    """Cost-reserved cap only: independent risk/margin approvals can reduce or reject.

    Contra depth must be current authenticated executable quote notional within
    25bp, not a promise of fills. Expired entries are missed without chasing.
    """
    if (
        plan.decision.direction is Direction.NO_TRADE
        or plan.stop is None
        or plan.target is None
        or not _integer(now_ms)
        or not plan.decision.timestamp_ms <= now_ms < plan.expires_at_ms
        or not _integer(sz_decimals)
        or sz_decimals < 0
        or any(
            not value.is_finite() or value <= 0
            for value in (equity, executable_entry, contra_depth_25bp)
        )
        or not plan.cost_bps.is_finite()
        or plan.cost_bps < 0
        or not _room(
            plan.decision.direction,
            executable_entry,
            plan.target,
            plan.stop,
            plan.cost_bps,
        )
    ):
        return ZERO
    risk_per_unit = abs(executable_entry - plan.stop) + executable_entry * plan.cost_bps / BPS
    quantity = min(
        D(".001") * equity / risk_per_unit,
        D(".25") * equity / executable_entry,
        D(".05") * contra_depth_25bp / executable_entry,
    )
    return quantity.quantize(D(1).scaleb(-sz_decimals), rounding=ROUND_DOWN)


def exit_reason(
    plan: FlowExhaustionPlan,
    *,
    executable_price: Decimal | None,
    first_fill_ms: int,
    now_ms: int,
) -> str | None:
    """Exit INTENT only; stops win, then target, then 30min from actual first fill.

    An absent quote can trigger a time exit but never implies executable liquidity
    or a fill. Actual stops/reduce-only intents remain the execution stack's job.
    """
    if plan.decision.direction is Direction.NO_TRADE or plan.stop is None or plan.target is None:
        return None
    if (
        not _integer(first_fill_ms)
        or not _integer(now_ms)
        or not plan.decision.timestamp_ms <= first_fill_ms <= now_ms
    ):
        raise ValueError("invalid_fill_clock")
    if executable_price is not None:
        _positive(executable_price)
        long = plan.decision.direction is Direction.LONG
        if (long and executable_price <= plan.stop) or (not long and executable_price >= plan.stop):
            return "stop"
        if (long and executable_price >= plan.target) or (
            not long and executable_price <= plan.target
        ):
            return "target"
    return "max_hold" if now_ms - first_fill_ms >= 1_800_000 else None
