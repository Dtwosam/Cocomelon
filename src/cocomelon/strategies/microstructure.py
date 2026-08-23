from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import MicrostructureWindow
from cocomelon.domain.stream import StreamEvent, StreamKind

ZERO = Decimal("0")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ALLOWED_KINDS = frozenset({StreamKind.TRADE, StreamKind.L2_BOOK})


def _receive_ms(value: datetime) -> int:
    delta = value.astimezone(UTC) - EPOCH
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    if positive and value <= ZERO:
        raise ValueError(f"{field} must be positive")
    if not positive and value < ZERO:
        raise ValueError(f"{field} must be non-negative")
    return value


def _book_side_size(raw_side: object, field: str) -> Decimal:
    if not isinstance(raw_side, (tuple, list)):
        raise ValueError(f"{field} must be a sequence of book levels")
    total = ZERO
    for raw_level in raw_side:
        if not isinstance(raw_level, Mapping):
            raise ValueError(f"{field} level must be a mapping")
        total += _decimal(raw_level.get("sz"), f"{field}.sz")
    return total


def _book_imbalance(event: StreamEvent) -> Decimal | None:
    bids = _book_side_size(event.payload.get("bids"), "bids")
    asks = _book_side_size(event.payload.get("asks"), "asks")
    total = bids + asks
    if total == ZERO:
        return None
    return (bids - asks) / total


def build_microstructure_window(
    events: Sequence[StreamEvent],
    *,
    market: MarketId,
    as_of_ms: int,
    window_ms: int = 60_000,
) -> MicrostructureWindow:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if window_ms <= 0:
        raise ValueError("window_ms must be positive")

    for event in events:
        if event.kind not in ALLOWED_KINDS:
            raise ValueError("microstructure input accepts only TRADE or L2_BOOK events")
        if event.market != market:
            raise ValueError("microstructure event market must match requested market")

    start_ms = max(0, as_of_ms - window_ms)
    included: list[tuple[int, StreamEvent]] = []
    for event in events:
        receive_ms = _receive_ms(event.receive_time)
        if receive_ms < start_ms or receive_ms > as_of_ms:
            continue
        if event.exchange_time_ms is None or event.exchange_time_ms > as_of_ms:
            continue
        included.append((receive_ms, event))

    included.sort(
        key=lambda item: (
            item[0],
            -1 if item[1].exchange_time_ms is None else item[1].exchange_time_ms,
            item[1].event_key,
        )
    )

    buy_notional = ZERO
    sell_notional = ZERO
    trade_count = 0
    book_imbalances: list[Decimal] = []
    event_keys: list[str] = []

    for _, event in included:
        event_keys.append(event.event_key)
        if event.kind is StreamKind.TRADE:
            side = event.payload.get("side")
            price = _decimal(event.payload.get("price"), "trade.price", positive=True)
            size = _decimal(event.payload.get("size"), "trade.size", positive=True)
            notional = price * size
            if side == "B":
                buy_notional += notional
            elif side == "A":
                sell_notional += notional
            else:
                raise ValueError("trade.side must be 'B' or 'A'")
            trade_count += 1
        else:
            imbalance = _book_imbalance(event)
            if imbalance is not None:
                book_imbalances.append(imbalance)

    total_notional = buy_notional + sell_notional
    flow_imbalance = (
        None if total_notional == ZERO else (buy_notional - sell_notional) / total_notional
    )
    latest_book_imbalance = book_imbalances[-1] if book_imbalances else None
    book_change = (
        book_imbalances[-1] - book_imbalances[0] if len(book_imbalances) >= 2 else None
    )
    latest_event_age_ms = (
        as_of_ms - max(receive_ms for receive_ms, _ in included) if included else None
    )

    return MicrostructureWindow(
        market=market,
        start_ms=start_ms,
        as_of_ms=as_of_ms,
        trade_count=trade_count,
        buy_notional=buy_notional,
        sell_notional=sell_notional,
        trade_flow_imbalance=flow_imbalance,
        latest_book_imbalance=latest_book_imbalance,
        book_imbalance_change=book_change,
        latest_event_age_ms=latest_event_age_ms,
        event_keys=tuple(event_keys),
    )
