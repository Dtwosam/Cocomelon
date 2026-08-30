from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import FundingRate, MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide

ZERO = Decimal("0")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
FUNDING_INTERVAL_MS = 3_600_000
FUNDING_BOUNDARY_POST_TIMESTAMP_TOLERANCE_MS = 1_000


def funding_boundary_for_record_time(time_ms: int) -> int | None:
    """Map bounded post-hour exchange timestamp jitter to its canonical boundary."""
    if time_ms < 0:
        raise ValueError("funding record time must be non-negative")
    boundary_ms = time_ms - (time_ms % FUNDING_INTERVAL_MS)
    if time_ms - boundary_ms <= FUNDING_BOUNDARY_POST_TIMESTAMP_TOLERANCE_MS:
        return boundary_ms
    return None


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _receive_time_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def funding_cash_delta(
    signed_quantity: Decimal,
    oracle_price: Decimal,
    funding_rate: Decimal,
) -> Decimal:
    for field, value in (
        ("signed_quantity", signed_quantity),
        ("oracle_price", oracle_price),
        ("funding_rate", funding_rate),
    ):
        if not value.is_finite():
            raise ValueError(f"{field} must be finite")
    if signed_quantity == ZERO:
        raise ValueError("signed_quantity must be non-zero")
    if oracle_price <= ZERO:
        raise ValueError("oracle_price must be positive")
    with localcontext(AUTHORITATIVE_CONTEXT):
        return -(signed_quantity * oracle_price * funding_rate)


@dataclass(frozen=True, slots=True)
class FundingAccrual:
    market: MarketId
    boundary_ms: int
    position_id: str
    signed_quantity: Decimal
    oracle_price: Decimal
    funding_rate: Decimal
    cash_delta: Decimal
    oracle_event_key: str
    funding_source: str
    funding_received_at_ms: int

    def __post_init__(self) -> None:
        if self.boundary_ms < 0 or self.funding_received_at_ms < 0:
            raise ValueError("funding timestamps must be non-negative")
        if not self.position_id.strip():
            raise ValueError("position_id must not be empty")
        if not self.signed_quantity.is_finite() or self.signed_quantity == ZERO:
            raise ValueError("signed_quantity must be finite and non-zero")
        if not self.oracle_price.is_finite() or self.oracle_price <= ZERO:
            raise ValueError("oracle_price must be positive and finite")
        if not self.funding_rate.is_finite() or not self.cash_delta.is_finite():
            raise ValueError("funding values must be finite")
        if not self.oracle_event_key.strip() or not self.funding_source.strip():
            raise ValueError("funding provenance must not be empty")

    @property
    def accrual_id(self) -> str:
        return _digest(
            {
                "market": self.market.canonical,
                "boundary_ms": self.boundary_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class FundingGap:
    market: MarketId
    boundary_ms: int
    position_id: str
    reason: str
    as_of_ms: int
    account_inconsistent: bool

    def __post_init__(self) -> None:
        if self.boundary_ms < 0 or self.as_of_ms < 0:
            raise ValueError("funding gap timestamps must be non-negative")
        if not self.position_id.strip() or not self.reason.strip():
            raise ValueError("funding gap identity must not be empty")

    @property
    def gap_id(self) -> str:
        return _digest(
            {
                "market": self.market.canonical,
                "boundary_ms": self.boundary_ms,
                "position_id": self.position_id,
                "reason": self.reason,
            }
        )


def _gap(
    position: PaperPosition,
    boundary_ms: int,
    now_ms: int,
    config: PaperExecutionConfig,
    reason: str,
) -> FundingGap:
    inconsistent = now_ms - boundary_ms >= config.funding_reconciliation_grace_ms
    return FundingGap(
        market=position.market,
        boundary_ms=boundary_ms,
        position_id=position.position_id,
        reason=reason,
        as_of_ms=now_ms,
        account_inconsistent=inconsistent,
    )


def reconcile_funding_boundary(
    position: PaperPosition,
    boundary_ms: int,
    oracle_ctx: StreamEvent | None,
    funding_record: FundingRate | None,
    *,
    now_ms: int,
    config: PaperExecutionConfig,
) -> FundingAccrual | FundingGap:
    if boundary_ms < 0:
        raise ValueError("boundary_ms must be non-negative")
    if now_ms < boundary_ms:
        raise ValueError("now_ms must be at or after boundary_ms")
    if position.opened_at_ms >= boundary_ms:
        return _gap(
            position,
            boundary_ms,
            now_ms,
            config,
            "POSITION_NOT_OPEN_ACROSS_BOUNDARY",
        )

    if oracle_ctx is None:
        return _gap(position, boundary_ms, now_ms, config, "ORACLE_CONTEXT_MISSING")
    if oracle_ctx.kind is not StreamKind.ACTIVE_ASSET_CTX:
        return _gap(position, boundary_ms, now_ms, config, "ORACLE_CONTEXT_WRONG_KIND")
    if oracle_ctx.market != position.market:
        return _gap(position, boundary_ms, now_ms, config, "ORACLE_MARKET_MISMATCH")
    oracle_received_ms = _receive_time_ms(oracle_ctx)
    if oracle_received_ms > boundary_ms:
        return _gap(position, boundary_ms, now_ms, config, "ORACLE_AFTER_BOUNDARY")
    if boundary_ms - oracle_received_ms > config.max_asset_ctx_age_ms:
        return _gap(position, boundary_ms, now_ms, config, "ORACLE_CONTEXT_STALE")
    oracle_price = oracle_ctx.payload.get("oracle_px")
    if (
        not isinstance(oracle_price, Decimal)
        or not oracle_price.is_finite()
        or oracle_price <= ZERO
    ):
        return _gap(position, boundary_ms, now_ms, config, "ORACLE_PRICE_INVALID")

    if funding_record is None:
        return _gap(position, boundary_ms, now_ms, config, "FUNDING_RECORD_MISSING")
    if funding_record.market != position.market:
        return _gap(position, boundary_ms, now_ms, config, "FUNDING_MARKET_MISMATCH")
    if funding_boundary_for_record_time(funding_record.time_ms) != boundary_ms:
        return _gap(position, boundary_ms, now_ms, config, "FUNDING_TIME_MISMATCH")
    if funding_record.received_at_ms > now_ms:
        return _gap(position, boundary_ms, now_ms, config, "FUNDING_RECORD_FROM_FUTURE")
    if not funding_record.funding_rate.is_finite():
        return _gap(position, boundary_ms, now_ms, config, "FUNDING_RATE_INVALID")
    if not funding_record.source.strip():
        return _gap(position, boundary_ms, now_ms, config, "FUNDING_SOURCE_INVALID")

    signed_quantity = (
        position.quantity if position.side is PositionSide.LONG else -position.quantity
    )
    cash_delta = funding_cash_delta(
        signed_quantity,
        oracle_price,
        funding_record.funding_rate,
    )
    return FundingAccrual(
        market=position.market,
        boundary_ms=boundary_ms,
        position_id=position.position_id,
        signed_quantity=signed_quantity,
        oracle_price=oracle_price,
        funding_rate=funding_record.funding_rate,
        cash_delta=cash_delta,
        oracle_event_key=oracle_ctx.event_key,
        funding_source=funding_record.source,
        funding_received_at_ms=funding_record.received_at_ms,
    )
