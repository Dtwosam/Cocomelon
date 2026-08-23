from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.stream import StreamEvent, StreamKind

BPS = Decimal("10000")
ZERO = Decimal("0")
TWO = Decimal("2")


@dataclass(frozen=True, slots=True)
class MicrostructureFeatureValues:
    source_received_at_ms: int
    best_bid_px: Decimal
    best_ask_px: Decimal
    mid_px: Decimal
    spread_bps: Decimal
    bid_depth_25bps: Decimal
    ask_depth_25bps: Decimal
    book_imbalance: Decimal | None
    book_age_ms: int


def _levels(payload: Mapping[str, object], key: str) -> tuple[tuple[Decimal, Decimal], ...]:
    raw = payload.get(key)
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"L2 payload {key} must be a sequence")

    levels: list[tuple[Decimal, Decimal]] = []
    for value in raw:
        if not isinstance(value, Mapping):
            raise ValueError(f"L2 {key} level must be a mapping")
        px = value.get("px")
        sz = value.get("sz")
        if not isinstance(px, Decimal) or not isinstance(sz, Decimal):
            raise ValueError(f"L2 {key} px and sz must be Decimal")
        if not px.is_finite() or not sz.is_finite() or px <= ZERO or sz <= ZERO:
            raise ValueError(f"L2 {key} px and sz must be finite and positive")
        levels.append((px, sz))
    if not levels:
        raise ValueError(f"L2 {key} book side must not be empty")
    return tuple(levels)


def calculate_microstructure_features(
    event: StreamEvent,
    *,
    as_of_ms: int,
    depth_band_bps: Decimal = Decimal("25"),
) -> MicrostructureFeatureValues:
    if event.kind is not StreamKind.L2_BOOK:
        raise ValueError("microstructure features require an L2 book event")
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if not depth_band_bps.is_finite() or depth_band_bps <= ZERO:
        raise ValueError("depth_band_bps must be finite and positive")
    if event.exchange_time_ms is None:
        raise ValueError("L2 event exchange_time_ms is required")
    if event.exchange_time_ms > as_of_ms:
        raise ValueError("L2 exchange timestamp is in the future")

    bids = _levels(event.payload, "bids")
    asks = _levels(event.payload, "asks")
    best_bid = max(px for px, _ in bids)
    best_ask = min(px for px, _ in asks)
    if best_bid >= best_ask:
        raise ValueError("L2 book is crossed or locked")

    mid = (best_bid + best_ask) / TWO
    spread_bps = (best_ask - best_bid) / mid * BPS
    band_fraction = depth_band_bps / BPS
    minimum_bid_px = mid * (Decimal("1") - band_fraction)
    maximum_ask_px = mid * (Decimal("1") + band_fraction)
    bid_depth = sum((px * sz for px, sz in bids if px >= minimum_bid_px), ZERO)
    ask_depth = sum((px * sz for px, sz in asks if px <= maximum_ask_px), ZERO)
    total_depth = bid_depth + ask_depth
    imbalance = None if total_depth <= ZERO else (bid_depth - ask_depth) / total_depth
    source_received_at_ms = int(event.receive_time.timestamp() * 1000)
    if source_received_at_ms > as_of_ms:
        raise ValueError("L2 event was received after as_of_ms")

    return MicrostructureFeatureValues(
        source_received_at_ms=source_received_at_ms,
        best_bid_px=best_bid,
        best_ask_px=best_ask,
        mid_px=mid,
        spread_bps=spread_bps,
        bid_depth_25bps=bid_depth,
        ask_depth_25bps=ask_depth,
        book_imbalance=imbalance,
        book_age_ms=as_of_ms - event.exchange_time_ms,
    )
