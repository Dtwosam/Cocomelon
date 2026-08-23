from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum

from cocomelon.domain.execution import OrderSide, PaperFill, PaperOrderPlan
from cocomelon.domain.market import MarketId

ZERO = Decimal("0")
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


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


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

    def __post_init__(self) -> None:
        _require_positive(self.quantity, "quantity")
        _require_positive(self.average_entry_price, "average_entry_price")
        _require_positive(self.stop_price, "stop_price")
        if not self.opening_plan_id.strip():
            raise ValueError("opening_plan_id must not be empty")
        if self.opened_at_ms < 0 or self.updated_at_ms < self.opened_at_ms:
            raise ValueError("position timestamps are invalid")

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
        ):
            _require_finite(value, field)
        if self.cumulative_fees < ZERO:
            raise ValueError("cumulative_fees must be non-negative")
        if self.gross_open_notional < ZERO:
            raise ValueError("gross_open_notional must be non-negative")
        if self.updated_at_ms < 0:
            raise ValueError("updated_at_ms must be non-negative")
        canonical = tuple(sorted(self.positions, key=lambda position: position.market.canonical))
        if canonical != self.positions:
            raise ValueError("positions must be sorted by market")
        markets = tuple(position.market.canonical for position in self.positions)
        if len(set(markets)) != len(markets):
            raise ValueError("positions must contain at most one position per market")

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
                "updated_at_ms": self.updated_at_ms,
            }
        )


def empty_account(starting_cash: Decimal, timestamp_ms: int) -> PaperAccountState:
    _require_positive(starting_cash, "starting_cash")
    if timestamp_ms < 0:
        raise ValueError("timestamp_ms must be non-negative")
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
    )


def _replace_state(
    account: PaperAccountState,
    *,
    cash: Decimal,
    positions: tuple[PaperPosition, ...],
    realized_gross_pnl: Decimal,
    cumulative_fees: Decimal,
    timestamp_ms: int,
) -> PaperAccountState:
    sorted_positions = tuple(sorted(positions, key=lambda position: position.market.canonical))
    return PaperAccountState(
        starting_cash=account.starting_cash,
        cash=cash,
        positions=sorted_positions,
        realized_gross_pnl=realized_gross_pnl,
        cumulative_fees=cumulative_fees,
        cumulative_funding=account.cumulative_funding,
        unrealized_pnl=ZERO,
        equity=cash,
        gross_open_notional=ZERO,
        updated_at_ms=timestamp_ms,
    )


def apply_opening_fills(
    account: PaperAccountState,
    plan: PaperOrderPlan,
    fills: Sequence[PaperFill],
) -> PaperAccountState:
    if plan.reduce_only:
        raise ValueError("opening fills require a non-reduce-only plan")
    if any(position.market == plan.market for position in account.positions):
        raise ValueError("opening fills cannot average into an existing position")
    if not fills:
        raise ValueError("opening fills must not be empty")
    if plan.stop_price is None:
        raise ValueError("opening plan requires stop_price")

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
        )
        cash = account.cash - fees
        cumulative_fees = account.cumulative_fees + fees

    return _replace_state(
        account,
        cash=cash,
        positions=account.positions + (position,),
        realized_gross_pnl=account.realized_gross_pnl,
        cumulative_fees=cumulative_fees,
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

    remaining_positions = tuple(
        existing for existing in account.positions if existing.market != market
    )
    if remaining_quantity > ZERO:
        remaining_positions += (
            PaperPosition(
                market=position.market,
                side=position.side,
                quantity=remaining_quantity,
                average_entry_price=position.average_entry_price,
                stop_price=position.stop_price,
                opening_plan_id=position.opening_plan_id,
                opened_at_ms=position.opened_at_ms,
                updated_at_ms=timestamp_ms,
            ),
        )

    return _replace_state(
        account,
        cash=cash,
        positions=remaining_positions,
        realized_gross_pnl=realized_gross_pnl,
        cumulative_fees=cumulative_fees,
        timestamp_ms=timestamp_ms,
    )


def mark_to_market(
    account: PaperAccountState,
    marks: Mapping[MarketId, Decimal],
    timestamp_ms: int,
) -> PaperAccountState:
    if timestamp_ms < account.updated_at_ms:
        raise ValueError("timestamp_ms must not move backward")
    with localcontext(AUTHORITATIVE_CONTEXT):
        unrealized = ZERO
        gross_notional = ZERO
        for position in account.positions:
            mark = marks.get(position.market)
            if mark is None or not mark.is_finite() or mark <= ZERO:
                raise ValueError(f"missing or invalid mark for {position.market.canonical}")
            gross_notional += mark * position.quantity
            if position.side is PositionSide.LONG:
                unrealized += (mark - position.average_entry_price) * position.quantity
            else:
                unrealized += (position.average_entry_price - mark) * position.quantity
        equity = account.cash + unrealized

    return PaperAccountState(
        starting_cash=account.starting_cash,
        cash=account.cash,
        positions=account.positions,
        realized_gross_pnl=account.realized_gross_pnl,
        cumulative_fees=account.cumulative_fees,
        cumulative_funding=account.cumulative_funding,
        unrealized_pnl=unrealized,
        equity=equity,
        gross_open_notional=gross_notional,
        updated_at_ms=timestamp_ms,
    )
