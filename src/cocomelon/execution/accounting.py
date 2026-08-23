from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum

from cocomelon.domain.execution import OrderSide, PaperFill, PaperOrderPlan
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import OpenPositionRisk, RiskAccountState
from cocomelon.domain.strategy import Direction

ZERO = Decimal("0")
THREE = Decimal("3")
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"


def _require_finite(value: Decimal, field: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")


def _require_positive(value: Decimal, field: str) -> None:
    _require_finite(value, field)
    if value <= ZERO:
        raise ValueError(f"{field} must be positive")


def _require_nonnegative(value: Decimal, field: str) -> None:
    _require_finite(value, field)
    if value < ZERO:
        raise ValueError(f"{field} must be non-negative")


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class RollingPeakCandidate:
    timestamp_ms: int
    equity: Decimal

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        _require_positive(self.equity, "equity")


def update_rolling_peak(
    candidates: Sequence[RollingPeakCandidate],
    timestamp_ms: int,
    equity: Decimal,
) -> tuple[RollingPeakCandidate, ...]:
    if timestamp_ms < 0:
        raise ValueError("timestamp_ms must be non-negative")
    _require_positive(equity, "equity")
    queue = list(candidates)
    if queue and timestamp_ms < queue[-1].timestamp_ms:
        raise ValueError("rolling peak timestamp must not move backward")
    while queue and queue[-1].equity <= equity:
        queue.pop()
    queue.append(RollingPeakCandidate(timestamp_ms, equity))
    cutoff = timestamp_ms - WEEK_MS
    while queue and queue[0].timestamp_ms < cutoff:
        queue.pop(0)
    return tuple(queue)


@dataclass(frozen=True, slots=True)
class PaperPosition:
    market: MarketId
    side: PositionSide
    quantity: Decimal
    average_entry_price: Decimal
    stop_price: Decimal
    opening_plan_id: str
    opened_at_ms: int
    updated_at_ms: int
    initial_risk_decision_id: str = "legacy-paper-risk"
    correlation_bucket: str = "uncategorized"
    cost_buffer_fraction: Decimal = ZERO
    planned_risk: Decimal = ZERO
    cumulative_realized_gross_pnl: Decimal = ZERO
    cumulative_fees: Decimal = ZERO
    cumulative_funding: Decimal = ZERO
    venue_max_leverage: Decimal = Decimal("20")
    latest_mark: Decimal | None = None

    def __post_init__(self) -> None:
        _require_positive(self.quantity, "quantity")
        _require_positive(self.average_entry_price, "average_entry_price")
        _require_positive(self.stop_price, "stop_price")
        if not self.opening_plan_id.strip():
            raise ValueError("opening_plan_id must not be empty")
        if not self.initial_risk_decision_id.strip():
            raise ValueError("initial_risk_decision_id must not be empty")
        if not self.correlation_bucket.strip():
            raise ValueError("correlation_bucket must not be empty")
        _require_nonnegative(self.cost_buffer_fraction, "cost_buffer_fraction")
        _require_nonnegative(self.planned_risk, "planned_risk")
        _require_finite(self.cumulative_realized_gross_pnl, "cumulative_realized_gross_pnl")
        _require_nonnegative(self.cumulative_fees, "cumulative_fees")
        _require_finite(self.cumulative_funding, "cumulative_funding")
        _require_positive(self.venue_max_leverage, "venue_max_leverage")
        if self.latest_mark is not None:
            _require_positive(self.latest_mark, "latest_mark")
        if self.opened_at_ms < 0 or self.updated_at_ms < self.opened_at_ms:
            raise ValueError("position timestamps are invalid")

    @property
    def realized_gross_pnl(self) -> Decimal:
        return self.cumulative_realized_gross_pnl

    @property
    def position_id(self) -> str:
        return _digest(
            {
                "market": self.market.canonical,
                "side": self.side.value,
                "quantity": str(self.quantity),
                "average_entry_price": str(self.average_entry_price),
                "stop_price": str(self.stop_price),
                "opening_plan_id": self.opening_plan_id,
                "opened_at_ms": self.opened_at_ms,
                "updated_at_ms": self.updated_at_ms,
                "initial_risk_decision_id": self.initial_risk_decision_id,
                "correlation_bucket": self.correlation_bucket,
                "cost_buffer_fraction": str(self.cost_buffer_fraction),
                "planned_risk": str(self.planned_risk),
                "cumulative_realized_gross_pnl": str(self.cumulative_realized_gross_pnl),
                "cumulative_fees": str(self.cumulative_fees),
                "cumulative_funding": str(self.cumulative_funding),
                "venue_max_leverage": str(self.venue_max_leverage),
                "latest_mark": None if self.latest_mark is None else str(self.latest_mark),
            }
        )


@dataclass(frozen=True, slots=True)
class PaperAccountState:
    starting_cash: Decimal
    cash: Decimal
    positions: tuple[PaperPosition, ...]
    realized_gross_pnl: Decimal
    cumulative_fees: Decimal
    cumulative_funding: Decimal
    unrealized_pnl: Decimal
    equity: Decimal
    gross_open_notional: Decimal
    updated_at_ms: int
    reserved_margin: Decimal = ZERO
    available_margin: Decimal = ZERO
    daily_realized_pnl: Decimal = ZERO
    day_start_equity: Decimal = ZERO
    day_start_ms: int = 0
    rolling_peak_candidates: tuple[RollingPeakCandidate, ...] = ()
    consecutive_losses: int = 0
    last_closed_trade_ms: int | None = None

    def __post_init__(self) -> None:
        _require_positive(self.starting_cash, "starting_cash")
        for field, value in (
            ("cash", self.cash),
            ("realized_gross_pnl", self.realized_gross_pnl),
            ("cumulative_funding", self.cumulative_funding),
            ("unrealized_pnl", self.unrealized_pnl),
            ("equity", self.equity),
            ("gross_open_notional", self.gross_open_notional),
            ("cumulative_fees", self.cumulative_fees),
            ("reserved_margin", self.reserved_margin),
            ("available_margin", self.available_margin),
            ("daily_realized_pnl", self.daily_realized_pnl),
        ):
            _require_finite(value, field)
        if self.day_start_equity == ZERO:
            object.__setattr__(self, "day_start_equity", self.starting_cash)
        _require_positive(self.day_start_equity, "day_start_equity")
        if self.cumulative_fees < ZERO:
            raise ValueError("cumulative_fees must be non-negative")
        if self.gross_open_notional < ZERO or self.reserved_margin < ZERO:
            raise ValueError("open notional and reserved margin must be non-negative")
        if self.available_margin < ZERO:
            raise ValueError("available_margin must be non-negative")
        if self.updated_at_ms < 0 or self.day_start_ms < 0:
            raise ValueError("account timestamps must be non-negative")
        if self.consecutive_losses < 0:
            raise ValueError("consecutive_losses must be non-negative")
        if self.last_closed_trade_ms is not None and self.last_closed_trade_ms < 0:
            raise ValueError("last_closed_trade_ms must be non-negative")
        canonical = tuple(sorted(self.positions, key=lambda position: position.market.canonical))
        if canonical != self.positions:
            raise ValueError("positions must be sorted by market")
        markets = tuple(position.market.canonical for position in self.positions)
        if len(set(markets)) != len(markets):
            raise ValueError("positions must contain at most one position per market")
        if not self.rolling_peak_candidates:
            object.__setattr__(
                self,
                "rolling_peak_candidates",
                (RollingPeakCandidate(self.updated_at_ms, self.equity),),
            )

    @property
    def rolling_7d_peak_equity(self) -> Decimal:
        return self.rolling_peak_candidates[0].equity

    @property
    def state_id(self) -> str:
        return _digest(
            {
                "starting_cash": str(self.starting_cash),
                "cash": str(self.cash),
                "positions": tuple(position.position_id for position in self.positions),
                "realized_gross_pnl": str(self.realized_gross_pnl),
                "cumulative_fees": str(self.cumulative_fees),
                "cumulative_funding": str(self.cumulative_funding),
                "unrealized_pnl": str(self.unrealized_pnl),
                "equity": str(self.equity),
                "gross_open_notional": str(self.gross_open_notional),
                "reserved_margin": str(self.reserved_margin),
                "available_margin": str(self.available_margin),
                "daily_realized_pnl": str(self.daily_realized_pnl),
                "day_start_equity": str(self.day_start_equity),
                "day_start_ms": self.day_start_ms,
                "rolling_peak_candidates": tuple(
                    (point.timestamp_ms, str(point.equity))
                    for point in self.rolling_peak_candidates
                ),
                "consecutive_losses": self.consecutive_losses,
                "last_closed_trade_ms": self.last_closed_trade_ms,
                "updated_at_ms": self.updated_at_ms,
            }
        )


def empty_account(starting_cash: Decimal, timestamp_ms: int) -> PaperAccountState:
    _require_positive(starting_cash, "starting_cash")
    if timestamp_ms < 0:
        raise ValueError("timestamp_ms must be non-negative")
    day_start_ms = (timestamp_ms // DAY_MS) * DAY_MS
    candidates = (RollingPeakCandidate(timestamp_ms, starting_cash),)
    return PaperAccountState(
        starting_cash=starting_cash,
        cash=starting_cash,
        positions=(),
        realized_gross_pnl=ZERO,
        cumulative_fees=ZERO,
        cumulative_funding=ZERO,
        unrealized_pnl=ZERO,
        equity=starting_cash,
        gross_open_notional=ZERO,
        updated_at_ms=timestamp_ms,
        reserved_margin=ZERO,
        available_margin=starting_cash,
        daily_realized_pnl=ZERO,
        day_start_equity=starting_cash,
        day_start_ms=day_start_ms,
        rolling_peak_candidates=candidates,
    )


def _state_with_equity(
    account: PaperAccountState,
    *,
    cash: Decimal,
    positions: tuple[PaperPosition, ...],
    realized_gross_pnl: Decimal,
    cumulative_fees: Decimal,
    cumulative_funding: Decimal,
    unrealized_pnl: Decimal,
    gross_open_notional: Decimal,
    reserved_margin: Decimal,
    daily_realized_pnl: Decimal,
    timestamp_ms: int,
    consecutive_losses: int | None = None,
    last_closed_trade_ms: int | None | object = ...,
) -> PaperAccountState:
    equity = cash + unrealized_pnl
    candidates = update_rolling_peak(account.rolling_peak_candidates, timestamp_ms, equity)
    if consecutive_losses is None:
        consecutive_losses = account.consecutive_losses
    if last_closed_trade_ms is ...:
        resolved_last_closed = account.last_closed_trade_ms
    else:
        resolved_last_closed = last_closed_trade_ms
    return PaperAccountState(
        starting_cash=account.starting_cash,
        cash=cash,
        positions=tuple(sorted(positions, key=lambda position: position.market.canonical)),
        realized_gross_pnl=realized_gross_pnl,
        cumulative_fees=cumulative_fees,
        cumulative_funding=cumulative_funding,
        unrealized_pnl=unrealized_pnl,
        equity=equity,
        gross_open_notional=gross_open_notional,
        updated_at_ms=timestamp_ms,
        reserved_margin=reserved_margin,
        available_margin=max(ZERO, equity - reserved_margin),
        daily_realized_pnl=daily_realized_pnl,
        day_start_equity=account.day_start_equity,
        day_start_ms=account.day_start_ms,
        rolling_peak_candidates=candidates,
        consecutive_losses=consecutive_losses,
        last_closed_trade_ms=resolved_last_closed,
    )


def apply_opening_fills(
    account: PaperAccountState,
    plan: PaperOrderPlan,
    fills: Sequence[PaperFill],
    *,
    correlation_bucket: str = "uncategorized",
    venue_max_leverage: Decimal = Decimal("20"),
) -> PaperAccountState:
    if plan.reduce_only:
        raise ValueError("opening fills require a non-reduce-only plan")
    if any(position.market == plan.market for position in account.positions):
        raise ValueError("opening fills cannot average into an existing position")
    if not fills:
        raise ValueError("opening fills must not be empty")
    if plan.stop_price is None or plan.cost_buffer_fraction is None:
        raise ValueError("opening plan requires stop and loss envelope")
    if not correlation_bucket.strip():
        raise ValueError("correlation_bucket must not be empty")
    _require_positive(venue_max_leverage, "venue_max_leverage")

    with localcontext(AUTHORITATIVE_CONTEXT):
        quantity = ZERO
        notional = ZERO
        fees = ZERO
        latest_ms = account.updated_at_ms
        for fill in fills:
            if fill.market != plan.market:
                raise ValueError("opening fill market mismatch")
            if fill.side is not plan.side:
                raise ValueError("opening fill side mismatch")
            if fill.plan_id != plan.plan_id:
                raise ValueError("opening fill plan mismatch")
            quantity += fill.quantity
            notional += fill.notional
            fees += fill.taker_fee
            latest_ms = max(latest_ms, fill.timestamp_ms)
        if quantity > plan.requested_quantity:
            raise ValueError("opening fill quantity exceeds planned quantity")
        if notional > plan.approved_notional_ceiling:
            raise ValueError("opening fill notional exceeds approved ceiling")
        average_entry_price = notional / quantity
        stop_fraction = abs(average_entry_price - plan.stop_price) / average_entry_price
        planned_risk = notional * (stop_fraction + plan.cost_buffer_fraction)
        if (
            plan.approved_risk_amount_ceiling is not None
            and planned_risk > plan.approved_risk_amount_ceiling
        ):
            raise ValueError("opening fill risk exceeds approved ceiling")
        side = PositionSide.LONG if plan.side is OrderSide.BUY else PositionSide.SHORT
        position = PaperPosition(
            market=plan.market,
            side=side,
            quantity=quantity,
            average_entry_price=average_entry_price,
            stop_price=plan.stop_price,
            opening_plan_id=plan.plan_id,
            opened_at_ms=latest_ms,
            updated_at_ms=latest_ms,
            initial_risk_decision_id=plan.risk_decision_id,
            correlation_bucket=correlation_bucket,
            cost_buffer_fraction=plan.cost_buffer_fraction,
            planned_risk=planned_risk,
            cumulative_fees=fees,
            venue_max_leverage=venue_max_leverage,
            latest_mark=average_entry_price,
        )
        cash = account.cash - fees
        cumulative_fees = account.cumulative_fees + fees

    return _state_with_equity(
        account,
        cash=cash,
        positions=account.positions + (position,),
        realized_gross_pnl=account.realized_gross_pnl,
        cumulative_fees=cumulative_fees,
        cumulative_funding=account.cumulative_funding,
        unrealized_pnl=ZERO,
        gross_open_notional=ZERO,
        reserved_margin=ZERO,
        daily_realized_pnl=account.daily_realized_pnl - fees,
        timestamp_ms=latest_ms,
    )


def apply_reduce_only_fills(
    account: PaperAccountState,
    market: MarketId,
    fills: Sequence[PaperFill],
    timestamp_ms: int,
) -> PaperAccountState:
    if timestamp_ms < account.updated_at_ms:
        raise ValueError("timestamp_ms must not move backward")
    if not fills:
        raise ValueError("reduce-only fills must not be empty")
    matches = tuple(position for position in account.positions if position.market == market)
    if len(matches) != 1:
        raise ValueError("reduce-only fills require exactly one existing position")
    position = matches[0]
    expected_side = OrderSide.SELL if position.side is PositionSide.LONG else OrderSide.BUY

    with localcontext(AUTHORITATIVE_CONTEXT):
        closed_quantity = ZERO
        realized = ZERO
        fees = ZERO
        for fill in fills:
            if fill.market != market:
                raise ValueError("reduce-only fill market mismatch")
            if fill.side is not expected_side:
                raise ValueError("reduce-only fill side does not reduce position")
            closed_quantity += fill.quantity
            if closed_quantity > position.quantity:
                raise ValueError("reduce-only fill would reverse position")
            if position.side is PositionSide.LONG:
                realized += (fill.price - position.average_entry_price) * fill.quantity
            else:
                realized += (position.average_entry_price - fill.price) * fill.quantity
            fees += fill.taker_fee
        remaining_quantity = position.quantity - closed_quantity
        cash = account.cash + realized - fees
        cumulative_fees = account.cumulative_fees + fees
        realized_gross_pnl = account.realized_gross_pnl + realized
        daily_realized_pnl = account.daily_realized_pnl + realized - fees

    remaining_positions = tuple(
        existing for existing in account.positions if existing.market != market
    )
    consecutive_losses = account.consecutive_losses
    last_closed_trade_ms = account.last_closed_trade_ms
    if remaining_quantity > ZERO:
        ratio = remaining_quantity / position.quantity
        remaining_positions += (
            replace(
                position,
                quantity=remaining_quantity,
                planned_risk=position.planned_risk * ratio,
                cumulative_realized_gross_pnl=(
                    position.cumulative_realized_gross_pnl + realized
                ),
                cumulative_fees=position.cumulative_fees + fees,
                updated_at_ms=timestamp_ms,
            ),
        )
    else:
        closed_net = (
            position.cumulative_realized_gross_pnl
            + realized
            - position.cumulative_fees
            - fees
            + position.cumulative_funding
        )
        consecutive_losses = (
            account.consecutive_losses + 1 if closed_net < ZERO else 0
        )
        last_closed_trade_ms = timestamp_ms

    return _state_with_equity(
        account,
        cash=cash,
        positions=remaining_positions,
        realized_gross_pnl=realized_gross_pnl,
        cumulative_fees=cumulative_fees,
        cumulative_funding=account.cumulative_funding,
        unrealized_pnl=ZERO,
        gross_open_notional=ZERO,
        reserved_margin=ZERO,
        daily_realized_pnl=daily_realized_pnl,
        timestamp_ms=timestamp_ms,
        consecutive_losses=consecutive_losses,
        last_closed_trade_ms=last_closed_trade_ms,
    )


def mark_to_market(
    account: PaperAccountState,
    marks: Mapping[MarketId, Decimal],
    timestamp_ms: int,
    *,
    paper_max_gross_leverage: Decimal = THREE,
) -> PaperAccountState:
    if timestamp_ms < account.updated_at_ms:
        raise ValueError("timestamp_ms must not move backward")
    _require_positive(paper_max_gross_leverage, "paper_max_gross_leverage")
    with localcontext(AUTHORITATIVE_CONTEXT):
        unrealized = ZERO
        gross_notional = ZERO
        reserved_margin = ZERO
        updated_positions: list[PaperPosition] = []
        for position in account.positions:
            mark = marks.get(position.market)
            if mark is None or not mark.is_finite() or mark <= ZERO:
                raise ValueError(f"missing or invalid mark for {position.market.canonical}")
            mark_notional = mark * position.quantity
            gross_notional += mark_notional
            leverage = min(paper_max_gross_leverage, position.venue_max_leverage)
            reserved_margin += mark_notional / leverage
            if position.side is PositionSide.LONG:
                unrealized += (mark - position.average_entry_price) * position.quantity
            else:
                unrealized += (position.average_entry_price - mark) * position.quantity
            updated_positions.append(
                replace(position, latest_mark=mark, updated_at_ms=timestamp_ms)
            )

    return _state_with_equity(
        account,
        cash=account.cash,
        positions=tuple(updated_positions),
        realized_gross_pnl=account.realized_gross_pnl,
        cumulative_fees=account.cumulative_fees,
        cumulative_funding=account.cumulative_funding,
        unrealized_pnl=unrealized,
        gross_open_notional=gross_notional,
        reserved_margin=reserved_margin,
        daily_realized_pnl=account.daily_realized_pnl,
        timestamp_ms=timestamp_ms,
    )


def replace_loss_state(
    account: PaperAccountState,
    *,
    consecutive_losses: int,
    last_closed_trade_ms: int | None,
) -> PaperAccountState:
    if consecutive_losses < 0:
        raise ValueError("consecutive_losses must be non-negative")
    return replace(
        account,
        consecutive_losses=consecutive_losses,
        last_closed_trade_ms=last_closed_trade_ms,
    )


def roll_account_day(account: PaperAccountState, timestamp_ms: int) -> PaperAccountState:
    if timestamp_ms < account.updated_at_ms:
        raise ValueError("timestamp_ms must not move backward")
    day_start_ms = (timestamp_ms // DAY_MS) * DAY_MS
    if day_start_ms <= account.day_start_ms:
        return replace(account, updated_at_ms=timestamp_ms)
    candidates = update_rolling_peak(
        account.rolling_peak_candidates,
        timestamp_ms,
        account.equity,
    )
    return replace(
        account,
        day_start_ms=day_start_ms,
        day_start_equity=account.equity,
        daily_realized_pnl=ZERO,
        rolling_peak_candidates=candidates,
        updated_at_ms=timestamp_ms,
    )


def risk_state_from_paper(
    account: PaperAccountState,
) -> tuple[RiskAccountState, tuple[OpenPositionRisk, ...]]:
    risk_account = RiskAccountState(
        equity=account.equity,
        day_start_equity=account.day_start_equity,
        daily_realized_pnl=account.daily_realized_pnl,
        rolling_7d_peak_equity=max(account.rolling_7d_peak_equity, account.equity),
        available_margin=account.available_margin,
        gross_open_notional=account.gross_open_notional,
        consecutive_losses=account.consecutive_losses,
        last_closed_trade_ms=account.last_closed_trade_ms,
        as_of_ms=account.updated_at_ms,
    )
    open_positions: list[OpenPositionRisk] = []
    for position in account.positions:
        mark = position.latest_mark or position.average_entry_price
        direction = (
            Direction.LONG if position.side is PositionSide.LONG else Direction.SHORT
        )
        open_positions.append(
            OpenPositionRisk(
                market=position.market,
                direction=direction,
                planned_risk=position.planned_risk,
                notional=mark * position.quantity,
                correlation_bucket=position.correlation_bucket,
                entry_price=position.average_entry_price,
                stop_price=position.stop_price,
            )
        )
    return risk_account, tuple(
        sorted(open_positions, key=lambda item: item.market.canonical)
    )
