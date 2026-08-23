from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategyDecision

ZERO = Decimal("0")
ONE = Decimal("1")


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


def _require_fraction(value: Decimal, field: str, *, allow_zero: bool = False) -> None:
    _require_finite(value, field)
    lower_ok = value >= ZERO if allow_zero else value > ZERO
    if not lower_ok or value > ONE:
        qualifier = "between 0 and 1" if allow_zero else "greater than 0 and at most 1"
        raise ValueError(f"{field} must be {qualifier}")


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


@dataclass(frozen=True, slots=True)
class RiskLimits:
    risk_per_trade: Decimal = Decimal("0.0025")
    max_open_risk: Decimal = Decimal("0.0075")
    daily_loss_limit: Decimal = Decimal("0.01")
    weekly_drawdown_limit: Decimal = Decimal("0.03")
    consecutive_loss_cooldown: int = 3
    cooldown_ms: int = 3_600_000
    correlation_bucket_risk_limit: Decimal = Decimal("0.005")
    max_gross_leverage: Decimal = Decimal("3")
    max_available_margin_fraction: Decimal = Decimal("0.50")
    max_visible_depth_fraction: Decimal = Decimal("0.10")
    min_liquidation_stop_multiple: Decimal = Decimal("2")
    max_state_age_ms: int = 5_000

    def __post_init__(self) -> None:
        _require_fraction(self.risk_per_trade, "risk_per_trade")
        _require_fraction(self.max_open_risk, "max_open_risk")
        _require_fraction(self.daily_loss_limit, "daily_loss_limit")
        _require_fraction(self.weekly_drawdown_limit, "weekly_drawdown_limit")
        _require_fraction(
            self.correlation_bucket_risk_limit,
            "correlation_bucket_risk_limit",
        )
        _require_positive(self.max_gross_leverage, "max_gross_leverage")
        _require_fraction(
            self.max_available_margin_fraction,
            "max_available_margin_fraction",
        )
        _require_fraction(self.max_visible_depth_fraction, "max_visible_depth_fraction")
        _require_positive(
            self.min_liquidation_stop_multiple,
            "min_liquidation_stop_multiple",
        )
        if self.consecutive_loss_cooldown <= 0:
            raise ValueError("consecutive_loss_cooldown must be positive")
        if self.cooldown_ms <= 0:
            raise ValueError("cooldown_ms must be positive")
        if self.max_state_age_ms <= 0:
            raise ValueError("max_state_age_ms must be positive")


@dataclass(frozen=True, slots=True)
class RiskAccountState:
    equity: Decimal
    day_start_equity: Decimal
    daily_realized_pnl: Decimal
    rolling_7d_peak_equity: Decimal
    available_margin: Decimal
    gross_open_notional: Decimal
    consecutive_losses: int
    last_closed_trade_ms: int | None
    as_of_ms: int

    def __post_init__(self) -> None:
        _require_positive(self.equity, "equity")
        _require_positive(self.day_start_equity, "day_start_equity")
        _require_finite(self.daily_realized_pnl, "daily_realized_pnl")
        _require_positive(self.rolling_7d_peak_equity, "rolling_7d_peak_equity")
        if self.rolling_7d_peak_equity < self.equity:
            raise ValueError("rolling_7d_peak_equity must be >= equity")
        _require_nonnegative(self.available_margin, "available_margin")
        _require_nonnegative(self.gross_open_notional, "gross_open_notional")
        if self.consecutive_losses < 0:
            raise ValueError("consecutive_losses must be non-negative")
        if self.last_closed_trade_ms is not None and self.last_closed_trade_ms < 0:
            raise ValueError("last_closed_trade_ms must be non-negative")
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")

    @property
    def state_id(self) -> str:
        return _digest(
            {
                "equity": str(self.equity),
                "day_start_equity": str(self.day_start_equity),
                "daily_realized_pnl": str(self.daily_realized_pnl),
                "rolling_7d_peak_equity": str(self.rolling_7d_peak_equity),
                "available_margin": str(self.available_margin),
                "gross_open_notional": str(self.gross_open_notional),
                "consecutive_losses": self.consecutive_losses,
                "last_closed_trade_ms": self.last_closed_trade_ms,
                "as_of_ms": self.as_of_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class OpenPositionRisk:
    market: MarketId
    direction: Direction
    planned_risk: Decimal
    notional: Decimal
    correlation_bucket: str
    entry_price: Decimal
    stop_price: Decimal

    def __post_init__(self) -> None:
        if self.direction is Direction.NO_TRADE:
            raise ValueError("direction must be LONG or SHORT")
        _require_nonnegative(self.planned_risk, "planned_risk")
        _require_positive(self.notional, "notional")
        if not self.correlation_bucket.strip():
            raise ValueError("correlation_bucket must not be empty")
        _require_positive(self.entry_price, "entry_price")
        _require_positive(self.stop_price, "stop_price")


@dataclass(frozen=True, slots=True)
class RiskHealthState:
    market_data_fresh: bool
    account_state_fresh: bool
    execution_health_ok: bool
    state_consistent: bool
    as_of_ms: int

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class ExecutionCostEstimate:
    entry_slippage_fraction: Decimal
    stop_slippage_fraction: Decimal
    round_trip_fee_fraction: Decimal

    def __post_init__(self) -> None:
        _require_nonnegative(self.entry_slippage_fraction, "entry_slippage_fraction")
        _require_nonnegative(self.stop_slippage_fraction, "stop_slippage_fraction")
        _require_nonnegative(self.round_trip_fee_fraction, "round_trip_fee_fraction")


@dataclass(frozen=True, slots=True)
class LiquidityRiskState:
    entry_side_visible_notional_25bps: Decimal
    exit_side_visible_notional_25bps: Decimal
    venue_max_leverage: Decimal
    liquidation_price: Decimal | None
    venue_min_notional: Decimal | None
    as_of_ms: int

    def __post_init__(self) -> None:
        _require_nonnegative(
            self.entry_side_visible_notional_25bps,
            "entry_side_visible_notional_25bps",
        )
        _require_nonnegative(
            self.exit_side_visible_notional_25bps,
            "exit_side_visible_notional_25bps",
        )
        _require_positive(self.venue_max_leverage, "venue_max_leverage")
        if self.liquidation_price is not None:
            _require_positive(self.liquidation_price, "liquidation_price")
        if self.venue_min_notional is not None:
            _require_positive(self.venue_min_notional, "venue_min_notional")
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class RiskRequest:
    strategy_decision: StrategyDecision
    entry_reference_price: Decimal
    correlation_bucket: str
    account_state: RiskAccountState
    open_positions: tuple[OpenPositionRisk, ...]
    health_state: RiskHealthState
    cost_estimate: ExecutionCostEstimate
    liquidity_state: LiquidityRiskState
    limits: RiskLimits
    timestamp_ms: int

    def __post_init__(self) -> None:
        _require_positive(self.entry_reference_price, "entry_reference_price")
        if not self.correlation_bucket.strip():
            raise ValueError("correlation_bucket must not be empty")
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        normalized_positions = tuple(
            sorted(
                self.open_positions,
                key=lambda item: (
                    item.market.canonical,
                    item.direction.value,
                    str(item.planned_risk),
                    str(item.notional),
                ),
            )
        )
        object.__setattr__(self, "open_positions", normalized_positions)

    @property
    def strategy_decision_id(self) -> str:
        return self.strategy_decision.decision_id

    @property
    def feature_snapshot_id(self) -> str:
        return self.strategy_decision.feature_snapshot_id

    @property
    def market(self) -> MarketId:
        return self.strategy_decision.market

    @property
    def direction(self) -> Direction:
        return self.strategy_decision.direction


@dataclass(frozen=True, slots=True)
class RiskDecision:
    strategy_decision_id: str
    market: MarketId
    direction: Direction
    approved: bool
    reason_codes: tuple[str, ...]
    target_risk_amount: Decimal
    approved_risk_amount: Decimal
    approved_notional: Decimal
    entry_reference_price: Decimal
    stop_price: Decimal | None
    stop_distance_fraction: Decimal | None
    effective_loss_fraction: Decimal | None
    correlation_bucket: str
    binding_caps: tuple[str, ...]
    timestamp_ms: int

    def __post_init__(self) -> None:
        if not self.strategy_decision_id.strip():
            raise ValueError("strategy_decision_id must not be empty")
        object.__setattr__(
            self,
            "reason_codes",
            _normalize_strings(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "binding_caps",
            _normalize_strings(self.binding_caps, "binding_caps"),
        )
        _require_nonnegative(self.target_risk_amount, "target_risk_amount")
        _require_nonnegative(self.approved_risk_amount, "approved_risk_amount")
        _require_nonnegative(self.approved_notional, "approved_notional")
        _require_positive(self.entry_reference_price, "entry_reference_price")
        if self.stop_price is not None:
            _require_positive(self.stop_price, "stop_price")
        if self.stop_distance_fraction is not None:
            _require_positive(self.stop_distance_fraction, "stop_distance_fraction")
        if self.effective_loss_fraction is not None:
            _require_positive(self.effective_loss_fraction, "effective_loss_fraction")
        if not self.correlation_bucket.strip():
            raise ValueError("correlation_bucket must not be empty")
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")

        if not self.approved:
            if self.approved_risk_amount != ZERO or self.approved_notional != ZERO:
                raise ValueError("rejected risk decisions must have zero approved exposure")
        else:
            if self.direction is Direction.NO_TRADE:
                raise ValueError("approved risk decisions require LONG or SHORT direction")
            if self.approved_risk_amount <= ZERO or self.approved_notional <= ZERO:
                raise ValueError("approved risk decisions require positive approved exposure")
            if self.stop_price is None:
                raise ValueError("approved risk decisions require stop_price")
            if self.stop_distance_fraction is None:
                raise ValueError("approved risk decisions require stop_distance_fraction")
            if self.effective_loss_fraction is None:
                raise ValueError("approved risk decisions require effective_loss_fraction")

    @property
    def risk_decision_id(self) -> str:
        return _digest(
            {
                "strategy_decision_id": self.strategy_decision_id,
                "market": self.market.canonical,
                "direction": self.direction.value,
                "approved": self.approved,
                "reason_codes": self.reason_codes,
                "target_risk_amount": str(self.target_risk_amount),
                "approved_risk_amount": str(self.approved_risk_amount),
                "approved_notional": str(self.approved_notional),
                "entry_reference_price": str(self.entry_reference_price),
                "stop_price": _canonical_decimal(self.stop_price),
                "stop_distance_fraction": _canonical_decimal(self.stop_distance_fraction),
                "effective_loss_fraction": _canonical_decimal(self.effective_loss_fraction),
                "correlation_bucket": self.correlation_bucket,
                "binding_caps": self.binding_caps,
                "timestamp_ms": self.timestamp_ms,
            }
        )
