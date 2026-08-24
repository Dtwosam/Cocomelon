from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext

from cocomelon.domain.journal import ExcursionMetric
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.domain.strategy import Direction

ZERO = Decimal("0")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class TradeAnalytics:
    net_pnl: Decimal
    net_r: Decimal
    entry_slippage_amount: Decimal
    exit_slippage_amount: Decimal
    entry_slippage_fraction: Decimal
    exit_slippage_fraction: Decimal
    mfe: ExcursionMetric
    mae: ExcursionMetric


def _positive(value: Decimal, field: str) -> None:
    if not value.is_finite() or value <= ZERO:
        raise ValueError(f"{field} must be positive and finite")


def _finite(value: Decimal, field: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")


def _mark_price(record: ReplayRecord) -> Decimal:
    if record.record_kind is not SourceRecordKind.NORMALIZED_EVENT:
        raise ValueError("mark observation must be a normalized event")
    if record.event_kind != "active_asset_ctx":
        raise ValueError("mark observation must be active_asset_ctx")
    payload = record.payload
    if not isinstance(payload, dict):
        raise ValueError("mark observation payload must be an object")
    raw = payload.get("mark_px")
    if not isinstance(raw, (str, int, float, Decimal)) or isinstance(raw, bool):
        raise ValueError("mark_px must be numeric")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("mark_px must be numeric") from exc
    _positive(value, "mark_px")
    return value


def _gap_intersects(
    opened_at_ms: int,
    closed_at_ms: int,
    gaps: Sequence[tuple[int, int | None]],
) -> bool:
    for started_ms, ended_ms in gaps:
        if started_ms < 0:
            raise ValueError("gap start must be non-negative")
        if ended_ms is not None and ended_ms < started_ms:
            raise ValueError("gap end must be >= gap start")
        effective_end = closed_at_ms if ended_ms is None else ended_ms
        if started_ms <= closed_at_ms and effective_end >= opened_at_ms:
            return True
    return False


def _validated_reductions(
    reductions: Sequence[tuple[int, Decimal]],
    *,
    opened_quantity: Decimal,
    opened_at_ms: int,
    closed_at_ms: int,
) -> tuple[tuple[int, Decimal], ...]:
    ordered = tuple(sorted(reductions, key=lambda item: (item[0], item[1])))
    reduced = ZERO
    with localcontext(AUTHORITATIVE_CONTEXT):
        for timestamp_ms, quantity in ordered:
            if timestamp_ms < opened_at_ms or timestamp_ms > closed_at_ms:
                raise ValueError("quantity reduction timestamp must be inside the trade lifecycle")
            _positive(quantity, "quantity reduction")
            reduced += quantity
            if reduced > opened_quantity:
                raise ValueError("quantity reductions must not exceed opened quantity")
    return ordered


def _quantity_at(
    record: ReplayRecord,
    *,
    opened_quantity: Decimal,
    reductions: Sequence[tuple[int, Decimal]],
) -> Decimal:
    with localcontext(AUTHORITATIVE_CONTEXT):
        reduced = sum(
            (
                quantity
                for timestamp_ms, quantity in reductions
                if timestamp_ms < record.available_at_ms
            ),
            ZERO,
        )
        remaining = opened_quantity - reduced
    if remaining <= ZERO:
        raise ValueError("mark observation has no open quantity remaining")
    return remaining


def _slippage_per_unit(
    *,
    direction: Direction,
    fill_price: Decimal,
    reference_price: Decimal,
    entry: bool,
) -> Decimal:
    if entry:
        if direction is Direction.LONG:
            return fill_price - reference_price
        return reference_price - fill_price
    if direction is Direction.LONG:
        return reference_price - fill_price
    return fill_price - reference_price


def _exit_slippage(
    *,
    direction: Direction,
    exit_price: Decimal,
    exit_reference_price: Decimal,
    opened_quantity: Decimal,
    legs: Sequence[tuple[Decimal, Decimal, Decimal]],
) -> tuple[Decimal, Decimal]:
    if not legs:
        with localcontext(AUTHORITATIVE_CONTEXT):
            amount = (
                _slippage_per_unit(
                    direction=direction,
                    fill_price=exit_price,
                    reference_price=exit_reference_price,
                    entry=False,
                )
                * opened_quantity
            )
            reference_notional = exit_reference_price * opened_quantity
            return amount, amount / reference_notional

    total_quantity = ZERO
    fill_notional = ZERO
    reference_notional = ZERO
    amount = ZERO
    with localcontext(AUTHORITATIVE_CONTEXT):
        for index, (fill_price, reference_price, quantity) in enumerate(legs):
            _positive(fill_price, f"exit_slippage_legs[{index}].fill_price")
            _positive(reference_price, f"exit_slippage_legs[{index}].reference_price")
            _positive(quantity, f"exit_slippage_legs[{index}].quantity")
            total_quantity += quantity
            fill_notional += fill_price * quantity
            reference_notional += reference_price * quantity
            amount += (
                _slippage_per_unit(
                    direction=direction,
                    fill_price=fill_price,
                    reference_price=reference_price,
                    entry=False,
                )
                * quantity
            )
        if total_quantity != opened_quantity:
            raise ValueError("exit slippage leg quantity must equal opened quantity")
        if fill_notional / total_quantity != exit_price:
            raise ValueError("exit slippage legs must reconcile to exit_price")
        if reference_notional / total_quantity != exit_reference_price:
            raise ValueError("exit slippage legs must reconcile to exit_reference_price")
        return amount, amount / reference_notional


def _excursion(
    *,
    kind: str,
    direction: Direction,
    entry_price: Decimal,
    quantity: Decimal,
    initial_risk_amount: Decimal,
    record: ReplayRecord,
    complete: bool,
) -> ExcursionMetric:
    price = _mark_price(record)
    with localcontext(AUTHORITATIVE_CONTEXT):
        if direction is Direction.LONG:
            raw = price - entry_price if kind == "mfe" else entry_price - price
        else:
            raw = entry_price - price if kind == "mfe" else price - entry_price
        per_unit = max(ZERO, raw)
        fraction = per_unit / entry_price
        currency = per_unit * quantity
        r_multiple = currency / initial_risk_amount
    return ExcursionMetric(
        kind=kind,
        price=price,
        per_unit=per_unit,
        fraction=fraction,
        currency=currency,
        r_multiple=r_multiple,
        timestamp_ms=record.available_at_ms,
        source_event_key=record.event_key or record.payload_json,
        complete=complete,
    )


def compute_trade_analytics(
    *,
    direction: Direction,
    entry_price: Decimal,
    entry_reference_price: Decimal,
    exit_price: Decimal,
    exit_reference_price: Decimal,
    opened_quantity: Decimal,
    gross_realized_pnl: Decimal,
    entry_fees: Decimal,
    exit_fees: Decimal,
    funding_cash_pnl: Decimal,
    initial_risk_amount: Decimal,
    opened_at_ms: int,
    closed_at_ms: int,
    mark_observations: Sequence[ReplayRecord],
    known_gap_intervals: Sequence[tuple[int, int | None]],
    quantity_reductions: Sequence[tuple[int, Decimal]] = (),
    exit_slippage_legs: Sequence[tuple[Decimal, Decimal, Decimal]] = (),
) -> TradeAnalytics:
    if direction is Direction.NO_TRADE:
        raise ValueError("trade analytics require LONG or SHORT")
    if opened_at_ms < 0 or closed_at_ms < opened_at_ms:
        raise ValueError("trade lifecycle timestamps are invalid")
    for field, value in (
        ("entry_price", entry_price),
        ("entry_reference_price", entry_reference_price),
        ("exit_price", exit_price),
        ("exit_reference_price", exit_reference_price),
        ("opened_quantity", opened_quantity),
        ("initial_risk_amount", initial_risk_amount),
    ):
        _positive(value, field)
    for field, value in (
        ("gross_realized_pnl", gross_realized_pnl),
        ("entry_fees", entry_fees),
        ("exit_fees", exit_fees),
        ("funding_cash_pnl", funding_cash_pnl),
    ):
        _finite(value, field)
    if entry_fees < ZERO or exit_fees < ZERO:
        raise ValueError("fees must be non-negative")

    reductions = _validated_reductions(
        quantity_reductions,
        opened_quantity=opened_quantity,
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
    )
    in_window = tuple(
        record
        for record in mark_observations
        if opened_at_ms <= record.available_at_ms <= closed_at_ms
    )
    if not in_window:
        raise ValueError("at least one in-lifecycle mark observation is required")
    prices = tuple((record, _mark_price(record)) for record in in_window)
    if direction is Direction.LONG:
        mfe_record = max(prices, key=lambda item: (item[1], item[0].sort_key))[0]
        mae_record = min(prices, key=lambda item: (item[1], item[0].sort_key))[0]
    else:
        mfe_record = min(prices, key=lambda item: (item[1], item[0].sort_key))[0]
        mae_record = max(prices, key=lambda item: (item[1], item[0].sort_key))[0]

    mfe_quantity = _quantity_at(
        mfe_record,
        opened_quantity=opened_quantity,
        reductions=reductions,
    )
    mae_quantity = _quantity_at(
        mae_record,
        opened_quantity=opened_quantity,
        reductions=reductions,
    )
    complete = not _gap_intersects(opened_at_ms, closed_at_ms, known_gap_intervals)
    with localcontext(AUTHORITATIVE_CONTEXT):
        net_pnl = gross_realized_pnl - entry_fees - exit_fees + funding_cash_pnl
        net_r = net_pnl / initial_risk_amount
        entry_slippage_amount = (
            _slippage_per_unit(
                direction=direction,
                fill_price=entry_price,
                reference_price=entry_reference_price,
                entry=True,
            )
            * opened_quantity
        )
        entry_reference_notional = entry_reference_price * opened_quantity
        entry_slippage_fraction = entry_slippage_amount / entry_reference_notional
    exit_slippage_amount, exit_slippage_fraction = _exit_slippage(
        direction=direction,
        exit_price=exit_price,
        exit_reference_price=exit_reference_price,
        opened_quantity=opened_quantity,
        legs=exit_slippage_legs,
    )

    return TradeAnalytics(
        net_pnl=net_pnl,
        net_r=net_r,
        entry_slippage_amount=entry_slippage_amount,
        exit_slippage_amount=exit_slippage_amount,
        entry_slippage_fraction=entry_slippage_fraction,
        exit_slippage_fraction=exit_slippage_fraction,
        mfe=_excursion(
            kind="mfe",
            direction=direction,
            entry_price=entry_price,
            quantity=mfe_quantity,
            initial_risk_amount=initial_risk_amount,
            record=mfe_record,
            complete=complete,
        ),
        mae=_excursion(
            kind="mae",
            direction=direction,
            entry_price=entry_price,
            quantity=mae_quantity,
            initial_risk_amount=initial_risk_amount,
            record=mae_record,
            complete=complete,
        ),
    )
