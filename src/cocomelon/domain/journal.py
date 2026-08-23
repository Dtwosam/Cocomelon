from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction

ZERO = Decimal("0")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


class ObservationKind(StrEnum):
    SCANNER_SHORTLIST = "scanner_shortlist"
    STRATEGY_DECISION = "strategy_decision"
    RISK_DECISION = "risk_decision"
    EXECUTION_ATTEMPT = "execution_attempt"
    POSITION_ACTION = "position_action"
    FUNDING_EVENT = "funding_event"
    FUNDING_GAP = "funding_gap"
    ACCOUNT_STATE = "account_state"
    TRADE_CLOSED = "trade_closed"


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_finite(value: Decimal, field: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")


def _require_positive(value: Decimal, field: str) -> None:
    _require_finite(value, field)
    if value <= ZERO:
        raise ValueError(f"{field} must be positive")


def _canonical_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _dedupe(values: tuple[str, ...], field: str, *, sort: bool = False) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(values))
    if any(not value.strip() for value in normalized):
        raise ValueError(f"{field} values must not be empty")
    return tuple(sorted(normalized)) if sort else normalized


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class JournalObservation:
    kind: ObservationKind
    timestamp_ms: int
    market: MarketId | None
    feature_snapshot_id: str | None
    strategy_decision_id: str | None
    risk_decision_id: str | None
    plan_id: str | None
    attempt_id: str | None
    position_action_id: str | None
    account_state_id: str | None
    reason_codes: tuple[str, ...]
    health_refs: tuple[str, ...]
    replay_run_id: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for field in (
            "feature_snapshot_id",
            "strategy_decision_id",
            "risk_decision_id",
            "plan_id",
            "attempt_id",
            "position_action_id",
            "account_state_id",
            "replay_run_id",
        ):
            value = getattr(self, field)
            if value is not None:
                _require_nonempty(value, field)
        object.__setattr__(
            self,
            "reason_codes",
            _dedupe(self.reason_codes, "reason_codes"),
        )
        object.__setattr__(
            self,
            "health_refs",
            _dedupe(self.health_refs, "health_refs", sort=True),
        )

    @property
    def observation_id(self) -> str:
        return _digest(
            {
                "kind": self.kind.value,
                "timestamp_ms": self.timestamp_ms,
                "market": None if self.market is None else self.market.canonical,
                "feature_snapshot_id": self.feature_snapshot_id,
                "strategy_decision_id": self.strategy_decision_id,
                "risk_decision_id": self.risk_decision_id,
                "plan_id": self.plan_id,
                "attempt_id": self.attempt_id,
                "position_action_id": self.position_action_id,
                "account_state_id": self.account_state_id,
                "reason_codes": self.reason_codes,
                "health_refs": self.health_refs,
                "replay_run_id": self.replay_run_id,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class ExcursionMetric:
    kind: str
    price: Decimal
    per_unit: Decimal
    fraction: Decimal
    currency: Decimal
    r_multiple: Decimal | None
    timestamp_ms: int
    source_event_key: str
    complete: bool

    def __post_init__(self) -> None:
        if self.kind not in {"mfe", "mae"}:
            raise ValueError("kind must be mfe or mae")
        _require_positive(self.price, "price")
        for field in ("per_unit", "fraction", "currency"):
            value = getattr(self, field)
            _require_finite(value, field)
            if value < ZERO:
                raise ValueError(f"{field} must be non-negative")
        if self.r_multiple is not None:
            _require_finite(self.r_multiple, "r_multiple")
            if self.r_multiple < ZERO:
                raise ValueError("r_multiple must be non-negative")
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        _require_nonempty(self.source_event_key, "source_event_key")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "price": str(self.price),
            "per_unit": str(self.per_unit),
            "fraction": str(self.fraction),
            "currency": str(self.currency),
            "r_multiple": _canonical_decimal(self.r_multiple),
            "timestamp_ms": self.timestamp_ms,
            "source_event_key": self.source_event_key,
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class TradeJournalEntry:
    market: MarketId
    direction: Direction
    opened_at_ms: int
    closed_at_ms: int
    feature_snapshot_id: str
    strategy_decision_id: str
    risk_decision_id: str
    opening_plan_id: str
    opening_attempt_id: str
    exit_plan_ids: tuple[str, ...]
    exit_attempt_ids: tuple[str, ...]
    fill_ids: tuple[str, ...]
    position_action_ids: tuple[str, ...]
    funding_event_ids: tuple[str, ...]
    initial_stop: Decimal
    initial_risk_amount: Decimal
    entry_price: Decimal
    exit_price: Decimal
    filled_quantity: Decimal
    gross_realized_pnl: Decimal
    entry_fees: Decimal
    exit_fees: Decimal
    funding_cash_pnl: Decimal
    net_pnl: Decimal
    entry_slippage_fraction: Decimal
    exit_slippage_fraction: Decimal
    mfe: ExcursionMetric | None
    mae: ExcursionMetric | None
    net_r: Decimal
    equity_before: Decimal
    equity_after: Decimal
    exit_reason: str
    health_refs: tuple[str, ...]
    evidence_class: EvidenceClass
    replay_run_id: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.direction is Direction.NO_TRADE:
            raise ValueError("trade direction must be LONG or SHORT")
        if self.opened_at_ms < 0:
            raise ValueError("opened_at_ms must be non-negative")
        if self.closed_at_ms < self.opened_at_ms:
            raise ValueError("closed_at_ms must be >= opened_at_ms")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        for field in (
            "feature_snapshot_id",
            "strategy_decision_id",
            "risk_decision_id",
            "opening_plan_id",
            "opening_attempt_id",
            "exit_reason",
        ):
            _require_nonempty(getattr(self, field), field)
        if self.replay_run_id is not None:
            _require_nonempty(self.replay_run_id, "replay_run_id")
        for field in (
            "exit_plan_ids",
            "exit_attempt_ids",
            "fill_ids",
            "position_action_ids",
            "funding_event_ids",
        ):
            value = _dedupe(getattr(self, field), field)
            object.__setattr__(self, field, value)
        if not self.exit_plan_ids or not self.exit_attempt_ids or not self.fill_ids:
            raise ValueError("closed trade requires exit plans, exit attempts, and fills")
        object.__setattr__(
            self,
            "health_refs",
            _dedupe(self.health_refs, "health_refs", sort=True),
        )
        for field in (
            "initial_stop",
            "initial_risk_amount",
            "entry_price",
            "exit_price",
            "filled_quantity",
        ):
            _require_positive(getattr(self, field), field)
        for field in (
            "gross_realized_pnl",
            "entry_fees",
            "exit_fees",
            "funding_cash_pnl",
            "net_pnl",
            "entry_slippage_fraction",
            "exit_slippage_fraction",
            "net_r",
            "equity_before",
            "equity_after",
        ):
            _require_finite(getattr(self, field), field)
        for field in (
            "entry_fees",
            "exit_fees",
            "entry_slippage_fraction",
            "exit_slippage_fraction",
        ):
            if getattr(self, field) < ZERO:
                raise ValueError(f"{field} must be non-negative")
        if self.equity_before <= ZERO or self.equity_after <= ZERO:
            raise ValueError("equity values must be positive")
        with localcontext(AUTHORITATIVE_CONTEXT):
            expected_net = (
                self.gross_realized_pnl
                - self.entry_fees
                - self.exit_fees
                + self.funding_cash_pnl
            )
            if expected_net != self.net_pnl:
                raise ValueError("net_pnl must reconcile to trading PnL, fees, and funding")
            expected_r = self.net_pnl / self.initial_risk_amount
            if expected_r != self.net_r:
                raise ValueError("net_r must equal net_pnl / initial_risk_amount")

    @property
    def trade_id(self) -> str:
        return _digest(
            {
                "market": self.market.canonical,
                "direction": self.direction.value,
                "opened_at_ms": self.opened_at_ms,
                "closed_at_ms": self.closed_at_ms,
                "feature_snapshot_id": self.feature_snapshot_id,
                "strategy_decision_id": self.strategy_decision_id,
                "risk_decision_id": self.risk_decision_id,
                "opening_plan_id": self.opening_plan_id,
                "opening_attempt_id": self.opening_attempt_id,
                "exit_plan_ids": self.exit_plan_ids,
                "exit_attempt_ids": self.exit_attempt_ids,
                "fill_ids": self.fill_ids,
                "position_action_ids": self.position_action_ids,
                "funding_event_ids": self.funding_event_ids,
                "initial_stop": str(self.initial_stop),
                "initial_risk_amount": str(self.initial_risk_amount),
                "entry_price": str(self.entry_price),
                "exit_price": str(self.exit_price),
                "filled_quantity": str(self.filled_quantity),
                "gross_realized_pnl": str(self.gross_realized_pnl),
                "entry_fees": str(self.entry_fees),
                "exit_fees": str(self.exit_fees),
                "funding_cash_pnl": str(self.funding_cash_pnl),
                "net_pnl": str(self.net_pnl),
                "entry_slippage_fraction": str(self.entry_slippage_fraction),
                "exit_slippage_fraction": str(self.exit_slippage_fraction),
                "mfe": None if self.mfe is None else self.mfe.canonical_payload(),
                "mae": None if self.mae is None else self.mae.canonical_payload(),
                "net_r": str(self.net_r),
                "equity_before": str(self.equity_before),
                "equity_after": str(self.equity_after),
                "exit_reason": self.exit_reason,
                "health_refs": self.health_refs,
                "evidence_class": self.evidence_class.value,
                "replay_run_id": self.replay_run_id,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Phase 1 compatibility record; new Phase 8 code uses JournalObservation."""

    decision_id: str
    market: MarketId
    direction: Direction
    timestamp_ms: int
    regime: str
    strategy_names: tuple[str, ...]
    approved_by_risk: bool
    reason_codes: tuple[str, ...]
