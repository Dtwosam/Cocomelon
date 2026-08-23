from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import Enum, StrEnum

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction

AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)
ZERO = Decimal("0")
JOURNAL_SCHEMA_VERSION = 1


class JournalEventType(StrEnum):
    SCANNER_OUTCOME = "scanner_outcome"
    FEATURE_SNAPSHOT = "feature_snapshot"
    STRATEGY_SIGNAL = "strategy_signal"
    STRATEGY_DECISION = "strategy_decision"
    RISK_DECISION = "risk_decision"
    ORDER_PLAN = "order_plan"
    ORDER_ATTEMPT = "order_attempt"
    FILL = "fill"
    NO_FILL = "no_fill"
    POSITION_OPEN = "position_open"
    POSITION_ACTION = "position_action"
    FUNDING = "funding"
    POSITION_REDUCTION = "position_reduction"
    POSITION_CLOSE = "position_close"
    ACCOUNT_SNAPSHOT = "account_snapshot"
    DATA_QUALITY = "data_quality"
    EXECUTION_HEALTH = "execution_health"


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


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        _require_finite(value, "Decimal payload value")
        return str(value)
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, MarketId):
        return value.canonical
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON mapping keys must be strings")
            normalized[key] = _canonical_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("float payload value must be finite")
        return value
    raise TypeError(f"unsupported canonical JSON value type: {type(value).__name__}")


def canonical_json(value: object) -> str:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class JournalEvent:
    journal_event_id: str
    event_type: JournalEventType
    occurred_at_ms: int
    schema_version: int
    code_version: str
    config_snapshot_id: str
    payload_json: str
    payload_sha256: str
    decision_id: str | None = None
    market: MarketId | None = None

    def __post_init__(self) -> None:
        if len(self.journal_event_id) != 64:
            raise ValueError("journal_event_id must be a SHA-256 hex digest")
        if self.occurred_at_ms < 0:
            raise ValueError("occurred_at_ms must be non-negative")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        _require_nonempty(self.code_version, "code_version")
        _require_nonempty(self.config_snapshot_id, "config_snapshot_id")
        if len(self.payload_sha256) != 64:
            raise ValueError("payload_sha256 must be a SHA-256 hex digest")
        if self.decision_id is not None:
            _require_nonempty(self.decision_id, "decision_id")

    @classmethod
    def create(
        cls,
        *,
        event_type: JournalEventType,
        occurred_at_ms: int,
        code_version: str,
        config_snapshot_id: str,
        payload: object,
        decision_id: str | None = None,
        market: MarketId | None = None,
        schema_version: int = JOURNAL_SCHEMA_VERSION,
    ) -> JournalEvent:
        payload_json = canonical_json(payload)
        payload_sha256 = sha256_text(payload_json)
        envelope = {
            "event_type": event_type.value,
            "occurred_at_ms": occurred_at_ms,
            "schema_version": schema_version,
            "code_version": code_version,
            "config_snapshot_id": config_snapshot_id,
            "decision_id": decision_id,
            "market": None if market is None else market.canonical,
            "payload_sha256": payload_sha256,
        }
        return cls(
            journal_event_id=sha256_text(canonical_json(envelope)),
            event_type=event_type,
            occurred_at_ms=occurred_at_ms,
            schema_version=schema_version,
            code_version=code_version,
            config_snapshot_id=config_snapshot_id,
            payload_json=payload_json,
            payload_sha256=payload_sha256,
            decision_id=decision_id,
            market=market,
        )


@dataclass(frozen=True, slots=True)
class TradeSummary:
    trade_id: str
    decision_id: str
    risk_decision_id: str
    opening_plan_id: str
    replay_run_id: str
    market: MarketId
    direction: Direction
    entry_timestamp_ms: int
    exit_timestamp_ms: int
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    initial_stop_price: Decimal
    approved_risk_amount: Decimal
    maximum_actual_notional: Decimal
    gross_pnl: Decimal
    fees: Decimal
    funding: Decimal
    entry_slippage: Decimal
    exit_slippage: Decimal
    net_pnl: Decimal
    mfe_pnl: Decimal
    mae_pnl: Decimal
    exit_reason: str
    reason_trace: tuple[str, ...]
    equity_before: Decimal
    equity_after: Decimal

    def __post_init__(self) -> None:
        for string_field, string_value in (
            ("trade_id", self.trade_id),
            ("decision_id", self.decision_id),
            ("risk_decision_id", self.risk_decision_id),
            ("opening_plan_id", self.opening_plan_id),
            ("replay_run_id", self.replay_run_id),
            ("exit_reason", self.exit_reason),
        ):
            _require_nonempty(string_value, string_field)
        if self.direction not in {Direction.LONG, Direction.SHORT}:
            raise ValueError("direction must be LONG or SHORT")
        if self.entry_timestamp_ms < 0:
            raise ValueError("entry_timestamp_ms must be non-negative")
        if self.exit_timestamp_ms < self.entry_timestamp_ms:
            raise ValueError("exit_timestamp_ms must be >= entry_timestamp_ms")
        for positive_field, positive_value in (
            ("entry_price", self.entry_price),
            ("exit_price", self.exit_price),
            ("quantity", self.quantity),
            ("initial_stop_price", self.initial_stop_price),
            ("approved_risk_amount", self.approved_risk_amount),
            ("maximum_actual_notional", self.maximum_actual_notional),
        ):
            _require_positive(positive_value, positive_field)
        for decimal_field, decimal_value in (
            ("gross_pnl", self.gross_pnl),
            ("fees", self.fees),
            ("funding", self.funding),
            ("entry_slippage", self.entry_slippage),
            ("exit_slippage", self.exit_slippage),
            ("net_pnl", self.net_pnl),
            ("mfe_pnl", self.mfe_pnl),
            ("mae_pnl", self.mae_pnl),
            ("equity_before", self.equity_before),
            ("equity_after", self.equity_after),
        ):
            _require_finite(decimal_value, decimal_field)
        if self.fees < ZERO:
            raise ValueError("fees must be non-negative")
        if self.entry_slippage < ZERO or self.exit_slippage < ZERO:
            raise ValueError("slippage attribution must be non-negative")
        if self.mfe_pnl < ZERO:
            raise ValueError("mfe_pnl must be non-negative")
        if self.mae_pnl > ZERO:
            raise ValueError("mae_pnl must be non-positive")
        if not self.reason_trace or any(not reason.strip() for reason in self.reason_trace):
            raise ValueError("reason_trace must contain non-empty reasons")

    @property
    def holding_ms(self) -> int:
        return self.exit_timestamp_ms - self.entry_timestamp_ms

    @property
    def net_r(self) -> Decimal:
        with localcontext(AUTHORITATIVE_CONTEXT):
            return self.net_pnl / self.approved_risk_amount

    @property
    def mfe_r(self) -> Decimal:
        with localcontext(AUTHORITATIVE_CONTEXT):
            return self.mfe_pnl / self.approved_risk_amount

    @property
    def mae_r(self) -> Decimal:
        with localcontext(AUTHORITATIVE_CONTEXT):
            return self.mae_pnl / self.approved_risk_amount
