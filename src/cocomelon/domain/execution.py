from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum

from cocomelon.domain.market import MarketId

ZERO = Decimal("0")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


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


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _normalize_strings(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if any(not value.strip() for value in normalized):
        raise ValueError(f"{field} values must not be empty")
    return normalized


def _canonical_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKETABLE_IOC = "marketable_ioc"
    LIMIT_GTC = "limit_gtc"


class ExecutionResult(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    NO_FILL = "no_fill"
    REJECTED = "rejected"


class PositionActionType(StrEnum):
    HOLD = "hold"
    TIGHTEN_STOP = "tighten_stop"
    REDUCE = "reduce"
    EXIT_THESIS = "exit_thesis"
    EXIT_STOP = "exit_stop"
    EXIT_EMERGENCY = "exit_emergency"


@dataclass(frozen=True, slots=True)
class PaperExecutionConfig:
    config_version: str = "phase7-v1"
    latency_ms: int = 250
    max_book_age_ms: int = 1_000
    max_asset_ctx_age_ms: int = 5_000
    funding_reconciliation_grace_ms: int = 300_000
    max_ioc_slippage_bps: Decimal = Decimal("25")
    taker_fee_rate: Decimal = Decimal("0.00045")
    fee_schedule_id: str = "hyperliquid-native-base-2026-08-23"
    native_perp_min_notional: Decimal = Decimal("10")
    paper_max_gross_leverage: Decimal = Decimal("3")

    def __post_init__(self) -> None:
        _require_nonempty(self.config_version, "config_version")
        _require_nonempty(self.fee_schedule_id, "fee_schedule_id")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if self.max_book_age_ms <= 0:
            raise ValueError("max_book_age_ms must be positive")
        if self.max_asset_ctx_age_ms <= 0:
            raise ValueError("max_asset_ctx_age_ms must be positive")
        if self.funding_reconciliation_grace_ms < 0:
            raise ValueError("funding_reconciliation_grace_ms must be non-negative")
        _require_positive(self.max_ioc_slippage_bps, "max_ioc_slippage_bps")
        _require_nonnegative(self.taker_fee_rate, "taker_fee_rate")
        _require_positive(self.native_perp_min_notional, "native_perp_min_notional")
        _require_positive(self.paper_max_gross_leverage, "paper_max_gross_leverage")


@dataclass(frozen=True, slots=True)
class InstrumentExecutionSpec:
    market: MarketId
    sz_decimals: int
    venue_max_leverage: Decimal
    minimum_order_notional: Decimal
    metadata_received_at_ms: int
    metadata_source: str

    def __post_init__(self) -> None:
        if self.sz_decimals < 0:
            raise ValueError("sz_decimals must be non-negative")
        _require_positive(self.venue_max_leverage, "venue_max_leverage")
        _require_positive(self.minimum_order_notional, "minimum_order_notional")
        if self.metadata_received_at_ms < 0:
            raise ValueError("metadata_received_at_ms must be non-negative")
        _require_nonempty(self.metadata_source, "metadata_source")

    @property
    def size_quantum(self) -> Decimal:
        return Decimal(f"1e-{self.sz_decimals}")

    @property
    def execution_supported(self) -> bool:
        return self.market.dex == ""

    @property
    def unsupported_reason(self) -> str | None:
        if self.execution_supported:
            return None
        return "UNSUPPORTED_NON_NATIVE_PERP_DEX"


@dataclass(frozen=True, slots=True)
class PaperOrderPlan:
    risk_decision_id: str
    strategy_decision_id: str
    market: MarketId
    side: OrderSide
    requested_quantity: Decimal
    order_type: OrderType
    reduce_only: bool
    execution_reference_price: Decimal
    max_slippage_bps: Decimal
    stop_price: Decimal | None
    approved_notional_ceiling: Decimal
    created_at_ms: int
    earliest_execution_ms: int
    execution_config_version: str
    instrument_metadata_received_at_ms: int
    approved_risk_amount_ceiling: Decimal | None = None
    stop_distance_fraction: Decimal | None = None
    effective_loss_fraction: Decimal | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.risk_decision_id, "risk_decision_id")
        _require_nonempty(self.strategy_decision_id, "strategy_decision_id")
        _require_positive(self.requested_quantity, "requested_quantity")
        _require_positive(self.execution_reference_price, "execution_reference_price")
        _require_positive(self.max_slippage_bps, "max_slippage_bps")
        if self.stop_price is not None:
            _require_positive(self.stop_price, "stop_price")
        _require_positive(self.approved_notional_ceiling, "approved_notional_ceiling")
        if self.created_at_ms < 0:
            raise ValueError("created_at_ms must be non-negative")
        if self.earliest_execution_ms < self.created_at_ms:
            raise ValueError("earliest_execution_ms must be >= created_at_ms")
        if self.instrument_metadata_received_at_ms < 0:
            raise ValueError("instrument_metadata_received_at_ms must be non-negative")
        _require_nonempty(self.execution_config_version, "execution_config_version")
        if self.order_type is not OrderType.MARKETABLE_IOC:
            raise ValueError("Phase 7 paper orders must use MARKETABLE_IOC")
        if not self.reduce_only:
            if self.stop_price is None:
                raise ValueError("opening paper orders require stop_price")
            if self.approved_risk_amount_ceiling is None:
                raise ValueError("opening paper orders require approved_risk_amount_ceiling")
            if self.stop_distance_fraction is None:
                raise ValueError("opening paper orders require stop_distance_fraction")
            if self.effective_loss_fraction is None:
                raise ValueError("opening paper orders require effective_loss_fraction")
            _require_positive(
                self.approved_risk_amount_ceiling,
                "approved_risk_amount_ceiling",
            )
            _require_positive(self.stop_distance_fraction, "stop_distance_fraction")
            _require_positive(self.effective_loss_fraction, "effective_loss_fraction")
            with localcontext(AUTHORITATIVE_CONTEXT):
                if self.effective_loss_fraction < self.stop_distance_fraction:
                    raise ValueError(
                        "effective_loss_fraction must be >= stop_distance_fraction"
                    )
        else:
            if self.approved_risk_amount_ceiling is not None:
                _require_nonnegative(
                    self.approved_risk_amount_ceiling,
                    "approved_risk_amount_ceiling",
                )
            if self.stop_distance_fraction is not None:
                _require_nonnegative(self.stop_distance_fraction, "stop_distance_fraction")
            if self.effective_loss_fraction is not None:
                _require_nonnegative(
                    self.effective_loss_fraction,
                    "effective_loss_fraction",
                )

    @property
    def cost_buffer_fraction(self) -> Decimal | None:
        if self.stop_distance_fraction is None or self.effective_loss_fraction is None:
            return None
        with localcontext(AUTHORITATIVE_CONTEXT):
            return self.effective_loss_fraction - self.stop_distance_fraction

    @property
    def plan_id(self) -> str:
        return _digest(
            {
                "risk_decision_id": self.risk_decision_id,
                "strategy_decision_id": self.strategy_decision_id,
                "market": self.market.canonical,
                "side": self.side.value,
                "requested_quantity": str(self.requested_quantity),
                "order_type": self.order_type.value,
                "reduce_only": self.reduce_only,
                "execution_reference_price": str(self.execution_reference_price),
                "max_slippage_bps": str(self.max_slippage_bps),
                "stop_price": _canonical_decimal(self.stop_price),
                "approved_notional_ceiling": str(self.approved_notional_ceiling),
                "approved_risk_amount_ceiling": _canonical_decimal(
                    self.approved_risk_amount_ceiling
                ),
                "stop_distance_fraction": _canonical_decimal(self.stop_distance_fraction),
                "effective_loss_fraction": _canonical_decimal(self.effective_loss_fraction),
                "created_at_ms": self.created_at_ms,
                "earliest_execution_ms": self.earliest_execution_ms,
                "execution_config_version": self.execution_config_version,
                "instrument_metadata_received_at_ms": self.instrument_metadata_received_at_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class PaperFill:
    plan_id: str
    attempt_id: str
    market: MarketId
    side: OrderSide
    price: Decimal
    quantity: Decimal
    notional: Decimal
    taker_fee: Decimal
    source_event_key: str
    timestamp_ms: int

    def __post_init__(self) -> None:
        _require_nonempty(self.plan_id, "plan_id")
        _require_nonempty(self.attempt_id, "attempt_id")
        _require_positive(self.price, "price")
        _require_positive(self.quantity, "quantity")
        _require_positive(self.notional, "notional")
        _require_nonnegative(self.taker_fee, "taker_fee")
        _require_nonempty(self.source_event_key, "source_event_key")
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")

    @property
    def fill_id(self) -> str:
        return _digest(
            {
                "plan_id": self.plan_id,
                "attempt_id": self.attempt_id,
                "market": self.market.canonical,
                "side": self.side.value,
                "price": str(self.price),
                "quantity": str(self.quantity),
                "notional": str(self.notional),
                "taker_fee": str(self.taker_fee),
                "source_event_key": self.source_event_key,
                "timestamp_ms": self.timestamp_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    plan_id: str
    source_event_key: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    average_fill_price: Decimal | None
    gross_fill_notional: Decimal
    fee: Decimal
    unfilled_quantity: Decimal
    result: ExecutionResult
    reason_codes: tuple[str, ...]
    snapshot_exchange_ms: int | None
    snapshot_received_ms: int
    attempt_timestamp_ms: int

    def __post_init__(self) -> None:
        _require_nonempty(self.plan_id, "plan_id")
        _require_nonempty(self.source_event_key, "source_event_key")
        _require_positive(self.requested_quantity, "requested_quantity")
        _require_nonnegative(self.filled_quantity, "filled_quantity")
        if self.filled_quantity > self.requested_quantity:
            raise ValueError("filled_quantity must not exceed requested_quantity")
        if self.average_fill_price is not None:
            _require_positive(self.average_fill_price, "average_fill_price")
        _require_nonnegative(self.gross_fill_notional, "gross_fill_notional")
        _require_nonnegative(self.fee, "fee")
        _require_nonnegative(self.unfilled_quantity, "unfilled_quantity")
        if self.filled_quantity + self.unfilled_quantity != self.requested_quantity:
            raise ValueError("filled and unfilled quantity must reconcile")
        if self.snapshot_exchange_ms is not None and self.snapshot_exchange_ms < 0:
            raise ValueError("snapshot_exchange_ms must be non-negative")
        if self.snapshot_received_ms < 0 or self.attempt_timestamp_ms < 0:
            raise ValueError("attempt timestamps must be non-negative")
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_strings(self.reason_codes, "reason_codes"),
        )
        if self.filled_quantity == ZERO and self.result in {
            ExecutionResult.FULL,
            ExecutionResult.PARTIAL,
        }:
            raise ValueError("filled result requires positive filled_quantity")
        if self.filled_quantity > ZERO and self.average_fill_price is None:
            raise ValueError("positive fill requires average_fill_price")

    @property
    def attempt_id(self) -> str:
        return _digest(
            {
                "plan_id": self.plan_id,
                "source_event_key": self.source_event_key,
                "requested_quantity": str(self.requested_quantity),
                "filled_quantity": str(self.filled_quantity),
                "average_fill_price": _canonical_decimal(self.average_fill_price),
                "gross_fill_notional": str(self.gross_fill_notional),
                "fee": str(self.fee),
                "unfilled_quantity": str(self.unfilled_quantity),
                "result": self.result.value,
                "reason_codes": self.reason_codes,
                "snapshot_exchange_ms": self.snapshot_exchange_ms,
                "snapshot_received_ms": self.snapshot_received_ms,
                "attempt_timestamp_ms": self.attempt_timestamp_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class PositionAction:
    action_type: PositionActionType
    market: MarketId
    quantity: Decimal | None
    new_stop_price: Decimal | None
    reason_codes: tuple[str, ...]
    timestamp_ms: int

    def __post_init__(self) -> None:
        if self.quantity is not None:
            _require_nonnegative(self.quantity, "quantity")
        if self.new_stop_price is not None:
            _require_positive(self.new_stop_price, "new_stop_price")
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_strings(self.reason_codes, "reason_codes"),
        )
        if self.action_type in {
            PositionActionType.REDUCE,
            PositionActionType.EXIT_THESIS,
            PositionActionType.EXIT_STOP,
            PositionActionType.EXIT_EMERGENCY,
        } and (self.quantity is None or self.quantity <= ZERO):
            raise ValueError("quantity must be positive for reduce/exit actions")
        if self.action_type is PositionActionType.TIGHTEN_STOP and self.new_stop_price is None:
            raise ValueError("TIGHTEN_STOP requires new_stop_price")
        if self.action_type is PositionActionType.HOLD and (
            self.quantity is not None or self.new_stop_price is not None
        ):
            raise ValueError("HOLD must not change quantity or stop")


# Phase 1 compatibility contracts. These remain non-authoritative placeholders
# until their call sites migrate to the Phase 7 Decimal contracts above.
@dataclass(frozen=True, slots=True)
class OrderIntent:
    intent_id: str
    market: MarketId
    side: OrderSide
    quantity: float
    order_type: OrderType
    reduce_only: bool
    limit_price: float | None
    created_at_ms: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    intent_id: str
    market: MarketId
    side: OrderSide
    price: float
    quantity: float
    fee: float
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class Position:
    market: MarketId
    signed_quantity: float
    average_entry_price: float
    stop_price: float | None
    realized_pnl: float = 0.0
