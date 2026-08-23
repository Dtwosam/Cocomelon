from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.market import PerpMarketSnapshot

BPS = Decimal("10000")
ONE = Decimal("1")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BroadFeatureValues:
    source_received_at_ms: int
    day_return: Decimal | None
    funding: Decimal
    open_interest: Decimal
    day_notional_volume: Decimal
    oi_change_fraction: Decimal | None
    funding_change: Decimal | None
    mark_oracle_dislocation_bps: Decimal | None


def _positive(value: Decimal | None) -> bool:
    return value is not None and value.is_finite() and value > ZERO


def calculate_broad_features(
    current: PerpMarketSnapshot,
    previous: PerpMarketSnapshot | None,
    *,
    as_of_ms: int,
) -> BroadFeatureValues:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if current.received_at_ms > as_of_ms:
        raise ValueError("current snapshot was received after as_of_ms")
    if previous is not None:
        if previous.received_at_ms > as_of_ms:
            raise ValueError("previous snapshot was received after as_of_ms")
        if previous.meta.market != current.meta.market:
            raise ValueError("previous snapshot must represent the same market")

    context = current.context
    reference_price = context.mid_px if _positive(context.mid_px) else context.mark_px
    day_return: Decimal | None = None
    if _positive(reference_price) and _positive(context.prev_day_px):
        assert reference_price is not None
        assert context.prev_day_px is not None
        day_return = reference_price / context.prev_day_px - ONE

    oi_change_fraction: Decimal | None = None
    funding_change: Decimal | None = None
    if previous is not None:
        previous_context = previous.context
        if _positive(previous_context.open_interest):
            oi_change_fraction = context.open_interest / previous_context.open_interest - ONE
        funding_change = context.funding - previous_context.funding

    mark_oracle_dislocation_bps: Decimal | None = None
    if _positive(context.mark_px) and _positive(context.oracle_px):
        assert context.mark_px is not None
        assert context.oracle_px is not None
        mark_oracle_dislocation_bps = (
            abs(context.mark_px - context.oracle_px) / context.oracle_px * BPS
        )

    return BroadFeatureValues(
        source_received_at_ms=current.received_at_ms,
        day_return=day_return,
        funding=context.funding,
        open_interest=context.open_interest,
        day_notional_volume=context.day_ntl_vlm,
        oi_change_fraction=oi_change_fraction,
        funding_change=funding_change,
        mark_oracle_dislocation_bps=mark_oracle_dislocation_bps,
    )
