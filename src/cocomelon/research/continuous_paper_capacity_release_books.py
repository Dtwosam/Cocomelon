from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperExecutionConfig,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.openings import BaselineOpeningTrace
from cocomelon.execution.accounting import (
    PaperPosition,
    PositionSide,
)

SCHEMA_VERSION: Final = 1
CORRELATION_BUCKET_REASON: Final = "correlation_bucket_exhausted"
ZERO: Final = Decimal("0")


def paper_execution_config_payload(
    config: PaperExecutionConfig,
) -> dict[str, object]:
    return {
        "config_version": config.config_version,
        "latency_ms": config.latency_ms,
        "max_book_age_ms": config.max_book_age_ms,
        "max_ioc_slippage_bps": str(config.max_ioc_slippage_bps),
        "taker_fee_rate": str(config.taker_fee_rate),
        "fee_schedule_id": config.fee_schedule_id,
        "native_perp_min_notional": str(
            config.native_perp_min_notional
        ),
    }


def _validated_execution_config_payload(
    raw: object,
) -> dict[str, object] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CapacityReleaseBookEvidenceError(
            "execution config lineage must be an object"
        )
    required = {
        "config_version",
        "latency_ms",
        "max_book_age_ms",
        "max_ioc_slippage_bps",
        "taker_fee_rate",
        "fee_schedule_id",
        "native_perp_min_notional",
    }
    if set(raw) != required:
        raise CapacityReleaseBookEvidenceError(
            "execution config lineage fields are invalid"
        )
    config_version = _text(
        raw.get("config_version"),
        "execution config version",
    )
    latency_ms = _integer(
        raw.get("latency_ms"),
        "execution latency_ms",
    )
    max_book_age_ms = _integer(
        raw.get("max_book_age_ms"),
        "execution max_book_age_ms",
    )
    if max_book_age_ms <= 0:
        raise CapacityReleaseBookEvidenceError(
            "execution max_book_age_ms must be positive"
        )
    max_slippage = _decimal(
        raw.get("max_ioc_slippage_bps"),
        "execution max_ioc_slippage_bps",
    )
    taker_fee = _decimal(
        raw.get("taker_fee_rate"),
        "execution taker_fee_rate",
    )
    native_min = _decimal(
        raw.get("native_perp_min_notional"),
        "execution native_perp_min_notional",
    )
    if max_slippage < ZERO or taker_fee < ZERO or native_min <= ZERO:
        raise CapacityReleaseBookEvidenceError(
            "execution config economics are invalid"
        )
    return {
        "config_version": config_version,
        "latency_ms": latency_ms,
        "max_book_age_ms": max_book_age_ms,
        "max_ioc_slippage_bps": str(max_slippage),
        "taker_fee_rate": str(taker_fee),
        "fee_schedule_id": _text(
            raw.get("fee_schedule_id"),
            "execution fee_schedule_id",
        ),
        "native_perp_min_notional": str(native_min),
    }


class CapacityReleaseBookEvidenceError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CapacityReleaseBookEvidenceError(
            f"{field} must be a decimal"
        ) from exc
    if not result.is_finite():
        raise CapacityReleaseBookEvidenceError(
            f"{field} must be finite"
        )
    return result


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CapacityReleaseBookEvidenceError(
            f"{field} must be a non-negative integer"
        )
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CapacityReleaseBookEvidenceError(
            f"{field} must be a non-empty string"
        )
    return value


def _received_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def _market(value: str) -> MarketId:
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    return MarketId(dex, coin)


def _level_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CapacityReleaseBookEvidenceError(
            "book level must be an object"
        )
    px = _decimal(value.get("px"), "level px")
    sz = _decimal(value.get("sz"), "level sz")
    n = value.get("n", 0)
    if (
        px <= ZERO
        or sz <= ZERO
        or isinstance(n, bool)
        or not isinstance(n, int)
        or n < 0
    ):
        raise CapacityReleaseBookEvidenceError(
            "book level economics are invalid"
        )
    return {"px": str(px), "sz": str(sz), "n": n}


def _book_payload(book: StreamEvent) -> dict[str, object]:
    if book.kind is not StreamKind.L2_BOOK:
        raise CapacityReleaseBookEvidenceError(
            "capacity release evidence requires L2 book"
        )
    if book.exchange_time_ms is None:
        raise CapacityReleaseBookEvidenceError(
            "capacity release book requires exchange timestamp"
        )
    bids = book.payload.get("bids")
    asks = book.payload.get("asks")
    if not isinstance(bids, (list, tuple)) or not isinstance(
        asks, (list, tuple)
    ):
        raise CapacityReleaseBookEvidenceError(
            "capacity release book sides are missing"
        )
    return {
        "market": book.market.canonical,
        "exchange_time_ms": book.exchange_time_ms,
        "received_at_ms": _received_ms(book),
        "schema_version": book.schema_version,
        "source": book.source,
        "event_key": book.event_key,
        "bids": [_level_payload(item) for item in bids],
        "asks": [_level_payload(item) for item in asks],
    }


def _book_from_payload(raw: object) -> StreamEvent:
    if not isinstance(raw, dict):
        raise CapacityReleaseBookEvidenceError(
            "capacity release book must be an object"
        )

    def levels(value: object) -> tuple[dict[str, object], ...]:
        if not isinstance(value, list):
            raise CapacityReleaseBookEvidenceError(
                "book levels must be an array"
            )
        output: list[dict[str, object]] = []
        for item in value:
            encoded = _level_payload(item)
            output.append(
                {
                    "px": Decimal(str(encoded["px"])),
                    "sz": Decimal(str(encoded["sz"])),
                    "n": encoded["n"],
                }
            )
        return tuple(output)

    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=_market(_text(raw.get("market"), "book market")),
        exchange_time_ms=_integer(
            raw.get("exchange_time_ms"),
            "exchange_time_ms",
        ),
        receive_time=datetime.fromtimestamp(
            _integer(raw.get("received_at_ms"), "received_at_ms")
            / 1000,
            tz=UTC,
        ),
        schema_version=_integer(
            raw.get("schema_version"),
            "schema_version",
        ),
        source=_text(raw.get("source"), "book source"),
        event_key=_text(raw.get("event_key"), "book event key"),
        payload={
            "bids": levels(raw.get("bids")),
            "asks": levels(raw.get("asks")),
        },
    )


def _instrument_payload(
    instrument: InstrumentExecutionSpec,
) -> dict[str, object]:
    return {
        "market": instrument.market.canonical,
        "sz_decimals": instrument.sz_decimals,
        "venue_max_leverage": str(instrument.venue_max_leverage),
        "minimum_order_notional": str(
            instrument.minimum_order_notional
        ),
        "metadata_received_at_ms": instrument.metadata_received_at_ms,
        "metadata_source": instrument.metadata_source,
    }


def _instrument_from_payload(
    raw: object,
) -> InstrumentExecutionSpec:
    if not isinstance(raw, dict):
        raise CapacityReleaseBookEvidenceError(
            "capacity release instrument must be an object"
        )
    try:
        return InstrumentExecutionSpec(
            market=_market(
                _text(raw.get("market"), "instrument market")
            ),
            sz_decimals=_integer(
                raw.get("sz_decimals"),
                "sz_decimals",
            ),
            venue_max_leverage=_decimal(
                raw.get("venue_max_leverage"),
                "venue_max_leverage",
            ),
            minimum_order_notional=_decimal(
                raw.get("minimum_order_notional"),
                "minimum_order_notional",
            ),
            metadata_received_at_ms=_integer(
                raw.get("metadata_received_at_ms"),
                "metadata_received_at_ms",
            ),
            metadata_source=_text(
                raw.get("metadata_source"),
                "metadata_source",
            ),
        )
    except ValueError as exc:
        raise CapacityReleaseBookEvidenceError(
            "capacity release instrument is invalid"
        ) from exc


def _position_payload(position: PaperPosition) -> dict[str, object]:
    return {
        "market": position.market.canonical,
        "side": position.side.value,
        "quantity": str(position.quantity),
        "average_entry_price": str(position.average_entry_price),
        "stop_price": str(position.stop_price),
        "opening_plan_id": position.opening_plan_id,
        "opened_at_ms": position.opened_at_ms,
        "updated_at_ms": position.updated_at_ms,
        "initial_risk_decision_id": position.initial_risk_decision_id,
        "correlation_bucket": position.correlation_bucket,
        "cost_buffer_fraction": str(position.cost_buffer_fraction),
        "planned_risk": str(position.planned_risk),
        "cumulative_realized_gross_pnl": str(
            position.cumulative_realized_gross_pnl
        ),
        "cumulative_fees": str(position.cumulative_fees),
        "cumulative_funding": str(position.cumulative_funding),
        "venue_max_leverage": str(position.venue_max_leverage),
        "latest_mark": (
            None
            if position.latest_mark is None
            else str(position.latest_mark)
        ),
    }


def _position_from_payload(raw: object) -> PaperPosition:
    if not isinstance(raw, dict):
        raise CapacityReleaseBookEvidenceError(
            "release position must be an object"
        )
    latest = raw.get("latest_mark")
    try:
        return PaperPosition(
            market=_market(_text(raw.get("market"), "position market")),
            side=PositionSide(
                _text(raw.get("side"), "position side")
            ),
            quantity=_decimal(raw.get("quantity"), "quantity"),
            average_entry_price=_decimal(
                raw.get("average_entry_price"),
                "average_entry_price",
            ),
            stop_price=_decimal(
                raw.get("stop_price"),
                "stop_price",
            ),
            opening_plan_id=_text(
                raw.get("opening_plan_id"),
                "opening_plan_id",
            ),
            opened_at_ms=_integer(
                raw.get("opened_at_ms"),
                "opened_at_ms",
            ),
            updated_at_ms=_integer(
                raw.get("updated_at_ms"),
                "updated_at_ms",
            ),
            initial_risk_decision_id=_text(
                raw.get("initial_risk_decision_id"),
                "initial_risk_decision_id",
            ),
            correlation_bucket=_text(
                raw.get("correlation_bucket"),
                "correlation_bucket",
            ),
            cost_buffer_fraction=_decimal(
                raw.get("cost_buffer_fraction"),
                "cost_buffer_fraction",
            ),
            planned_risk=_decimal(
                raw.get("planned_risk"),
                "planned_risk",
            ),
            cumulative_realized_gross_pnl=_decimal(
                raw.get("cumulative_realized_gross_pnl"),
                "cumulative_realized_gross_pnl",
            ),
            cumulative_fees=_decimal(
                raw.get("cumulative_fees"),
                "cumulative_fees",
            ),
            cumulative_funding=_decimal(
                raw.get("cumulative_funding"),
                "cumulative_funding",
            ),
            venue_max_leverage=_decimal(
                raw.get("venue_max_leverage"),
                "venue_max_leverage",
            ),
            latest_mark=(
                None
                if latest is None
                else _decimal(latest, "latest_mark")
            ),
        )
    except ValueError as exc:
        raise CapacityReleaseBookEvidenceError(
            "release position is invalid"
        ) from exc


@dataclass(frozen=True, slots=True)
class CapacityReleaseBookRegistration:
    opportunity_id: str
    opportunity_timestamp_ms: int
    opportunity_market: str
    opportunity_direction: str
    release_market: str
    release_direction: str
    release_correlation_bucket: str
    strategy_decision_id: str
    risk_decision_id: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.opportunity_id, "opportunity_id"),
            (self.opportunity_market, "opportunity_market"),
            (self.opportunity_direction, "opportunity_direction"),
            (self.release_market, "release_market"),
            (self.release_direction, "release_direction"),
            (
                self.release_correlation_bucket,
                "release_correlation_bucket",
            ),
            (self.strategy_decision_id, "strategy_decision_id"),
            (self.risk_decision_id, "risk_decision_id"),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.opportunity_timestamp_ms < 0:
            raise ValueError(
                "opportunity_timestamp_ms must be non-negative"
            )
        if self.opportunity_direction not in {"long", "short"}:
            raise ValueError("opportunity_direction must be directional")
        if self.release_direction not in {"long", "short"}:
            raise ValueError("release_direction must be directional")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported registration schema")

    @property
    def registration_id(self) -> str:
        return _digest(
            ":".join(
                (
                    self.opportunity_id,
                    self.release_market,
                    self.release_direction,
                )
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "opportunity_timestamp_ms": self.opportunity_timestamp_ms,
            "opportunity_market": self.opportunity_market,
            "opportunity_direction": self.opportunity_direction,
            "release_market": self.release_market,
            "release_direction": self.release_direction,
            "release_correlation_bucket": (
                self.release_correlation_bucket
            ),
            "strategy_decision_id": self.strategy_decision_id,
            "risk_decision_id": self.risk_decision_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> CapacityReleaseBookRegistration:
        if not isinstance(raw, dict):
            raise CapacityReleaseBookEvidenceError(
                "registration must be an object"
            )
        try:
            return cls(
                opportunity_id=_text(
                    raw.get("opportunity_id"),
                    "opportunity_id",
                ),
                opportunity_timestamp_ms=_integer(
                    raw.get("opportunity_timestamp_ms"),
                    "opportunity_timestamp_ms",
                ),
                opportunity_market=_text(
                    raw.get("opportunity_market"),
                    "opportunity_market",
                ),
                opportunity_direction=_text(
                    raw.get("opportunity_direction"),
                    "opportunity_direction",
                ),
                release_market=_text(
                    raw.get("release_market"),
                    "release_market",
                ),
                release_direction=_text(
                    raw.get("release_direction"),
                    "release_direction",
                ),
                release_correlation_bucket=_text(
                    raw.get("release_correlation_bucket"),
                    "release_correlation_bucket",
                ),
                strategy_decision_id=_text(
                    raw.get("strategy_decision_id"),
                    "strategy_decision_id",
                ),
                risk_decision_id=_text(
                    raw.get("risk_decision_id"),
                    "risk_decision_id",
                ),
                schema_version=_integer(
                    raw.get("schema_version"),
                    "schema_version",
                ),
            )
        except ValueError as exc:
            raise CapacityReleaseBookEvidenceError(
                "registration is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class PendingCapacityReleaseExecution:
    registration: CapacityReleaseBookRegistration
    release_position: PaperPosition
    plan_observed_at_ms: int
    plan_reference_price: Decimal
    plan_book_event: StreamEvent
    plan_instrument: InstrumentExecutionSpec
    execution_config: dict[str, object] | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.release_position.market.canonical
            != self.registration.release_market
        ):
            raise ValueError("pending release position market mismatch")
        if (
            self.release_position.side.value
            != self.registration.release_direction
        ):
            raise ValueError("pending release position direction mismatch")
        if (
            self.release_position.opened_at_ms
            > self.registration.opportunity_timestamp_ms
        ):
            raise ValueError("release position opened after opportunity")
        if self.plan_observed_at_ms < (
            self.registration.opportunity_timestamp_ms
        ):
            raise ValueError("release plan book precedes opportunity")
        if (
            not self.plan_reference_price.is_finite()
            or self.plan_reference_price <= ZERO
        ):
            raise ValueError(
                "plan_reference_price must be positive and finite"
            )
        if (
            self.plan_book_event.market.canonical
            != self.registration.release_market
            or self.plan_instrument.market.canonical
            != self.registration.release_market
        ):
            raise ValueError("release plan market mismatch")
        if (
            self.plan_book_event.exchange_time_ms is None
            or self.plan_book_event.exchange_time_ms
            < self.registration.opportunity_timestamp_ms
            or self.plan_book_event.exchange_time_ms
            > self.plan_observed_at_ms
        ):
            raise ValueError(
                "release plan book exchange timestamp is invalid"
            )
        if (
            self.plan_instrument.metadata_received_at_ms
            > self.plan_observed_at_ms
        ):
            raise ValueError(
                "release plan instrument metadata is from the future"
            )
        if self.execution_config is not None:
            validated = _validated_execution_config_payload(
                self.execution_config
            )
            if validated != self.execution_config:
                raise ValueError(
                    "pending execution config lineage is non-canonical"
                )
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported pending schema")

    @property
    def release_opening_plan_id(self) -> str:
        return self.release_position.opening_plan_id

    def to_dict(self) -> dict[str, object]:
        return {
            "registration": self.registration.to_dict(),
            "release_position": _position_payload(
                self.release_position
            ),
            "plan_observed_at_ms": self.plan_observed_at_ms,
            "plan_reference_price": str(
                self.plan_reference_price
            ),
            "plan_book": _book_payload(self.plan_book_event),
            "plan_instrument": _instrument_payload(
                self.plan_instrument
            ),
            "execution_config": self.execution_config,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> PendingCapacityReleaseExecution:
        if not isinstance(raw, dict):
            raise CapacityReleaseBookEvidenceError(
                "pending release execution must be an object"
            )
        try:
            return cls(
                registration=CapacityReleaseBookRegistration.from_dict(
                    raw.get("registration")
                ),
                release_position=_position_from_payload(
                    raw.get("release_position")
                ),
                plan_observed_at_ms=_integer(
                    raw.get("plan_observed_at_ms"),
                    "plan_observed_at_ms",
                ),
                plan_reference_price=_decimal(
                    raw.get("plan_reference_price"),
                    "plan_reference_price",
                ),
                plan_book_event=_book_from_payload(
                    raw.get("plan_book")
                ),
                plan_instrument=_instrument_from_payload(
                    raw.get("plan_instrument")
                ),
                execution_config=_validated_execution_config_payload(
                    raw.get("execution_config")
                ),
                schema_version=_integer(
                    raw.get("schema_version"),
                    "schema_version",
                ),
            )
        except ValueError as exc:
            raise CapacityReleaseBookEvidenceError(
                "pending release execution is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class CapacityReleaseBookEvidence:
    pending: PendingCapacityReleaseExecution
    execution_observed_at_ms: int
    execution_book_event: StreamEvent
    execution_instrument: InstrumentExecutionSpec
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            self.execution_book_event.market.canonical
            != self.pending.registration.release_market
            or self.execution_instrument.market.canonical
            != self.pending.registration.release_market
        ):
            raise ValueError("release execution market mismatch")
        if (
            self.execution_book_event.exchange_time_ms is None
            or self.execution_book_event.exchange_time_ms
            > self.execution_observed_at_ms
        ):
            raise ValueError(
                "release execution book exchange timestamp is invalid"
            )
        if (
            self.execution_instrument.metadata_received_at_ms
            > self.execution_observed_at_ms
        ):
            raise ValueError(
                "release execution instrument metadata is from future"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported evidence schema")

    @property
    def registration(self) -> CapacityReleaseBookRegistration:
        return self.pending.registration

    @property
    def release_position(self) -> PaperPosition:
        return self.pending.release_position

    @property
    def release_opening_plan_id(self) -> str:
        return self.pending.release_opening_plan_id

    def to_dict(self) -> dict[str, object]:
        return {
            "pending": self.pending.to_dict(),
            "execution_observed_at_ms": (
                self.execution_observed_at_ms
            ),
            "execution_book": _book_payload(
                self.execution_book_event
            ),
            "execution_instrument": _instrument_payload(
                self.execution_instrument
            ),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> CapacityReleaseBookEvidence:
        if not isinstance(raw, dict):
            raise CapacityReleaseBookEvidenceError(
                "capacity release evidence must be an object"
            )
        try:
            return cls(
                pending=PendingCapacityReleaseExecution.from_dict(
                    raw.get("pending")
                ),
                execution_observed_at_ms=_integer(
                    raw.get("execution_observed_at_ms"),
                    "execution_observed_at_ms",
                ),
                execution_book_event=_book_from_payload(
                    raw.get("execution_book")
                ),
                execution_instrument=_instrument_from_payload(
                    raw.get("execution_instrument")
                ),
                schema_version=_integer(
                    raw.get("schema_version"),
                    "schema_version",
                ),
            )
        except ValueError as exc:
            raise CapacityReleaseBookEvidenceError(
                "capacity release evidence is invalid"
            ) from exc


class CapacityReleaseBookStore:
    def __init__(
        self,
        root: str | Path,
        *,
        capture_started_at_ms: int,
        latency_ms: int,
        max_book_age_ms: int,
        execution_config: PaperExecutionConfig | None = None,
    ) -> None:
        if capture_started_at_ms < 0:
            raise ValueError(
                "capture_started_at_ms must be non-negative"
            )
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        if max_book_age_ms <= 0:
            raise ValueError("max_book_age_ms must be positive")
        self.root = Path(root)
        self.registrations_root = self.root / "registrations"
        self.pending_root = self.root / "pending"
        self.records_root = self.root / "records"
        self.protocol_path = self.root / "protocol.json"
        for path in (
            self.registrations_root,
            self.pending_root,
            self.records_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.latency_ms = latency_ms
        self.max_book_age_ms = max_book_age_ms
        self.execution_config = (
            None
            if execution_config is None
            else paper_execution_config_payload(execution_config)
        )
        if execution_config is not None and (
            execution_config.latency_ms != latency_ms
            or execution_config.max_book_age_ms != max_book_age_ms
        ):
            raise ValueError(
                "capacity release execution config timing mismatch"
            )
        self.capture_started_at_ms = self._load_or_create_protocol(
            capture_started_at_ms
        )

    @staticmethod
    def _write(path: Path, payload: object) -> None:
        encoded = _canonical_json(payload).encode("utf-8")
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _read(path: Path) -> object:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise CapacityReleaseBookEvidenceError(
                "capacity release evidence is unreadable"
            ) from exc
        if _canonical_json(payload) != raw:
            raise CapacityReleaseBookEvidenceError(
                "capacity release evidence is non-canonical"
            )
        return payload

    def _load_or_create_protocol(self, started_at_ms: int) -> int:
        candidate = {
            "schema_version": SCHEMA_VERSION,
            "capture_started_at_ms": started_at_ms,
            "latency_ms": self.latency_ms,
            "max_book_age_ms": self.max_book_age_ms,
        }
        if not self.protocol_path.exists():
            self._write(self.protocol_path, candidate)
            return started_at_ms
        raw = self._read(self.protocol_path)
        if (
            not isinstance(raw, dict)
            or set(raw) != set(candidate)
            or raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("latency_ms") != self.latency_ms
            or raw.get("max_book_age_ms") != self.max_book_age_ms
        ):
            raise CapacityReleaseBookEvidenceError(
                "capacity release protocol mismatch"
            )
        return _integer(
            raw.get("capture_started_at_ms"),
            "capture_started_at_ms",
        )

    @staticmethod
    def _file_name(registration_id: str) -> str:
        return f"{registration_id}.json"

    def _registration_path(self, registration_id: str) -> Path:
        return (
            self.registrations_root
            / self._file_name(registration_id)
        )

    def _pending_path(self, registration_id: str) -> Path:
        return self.pending_root / self._file_name(registration_id)

    def _record_path(self, registration_id: str) -> Path:
        return self.records_root / self._file_name(registration_id)

    def register(
        self,
        registration: CapacityReleaseBookRegistration,
    ) -> bool:
        if (
            registration.opportunity_timestamp_ms
            < self.capture_started_at_ms
        ):
            raise CapacityReleaseBookEvidenceError(
                "registration predates capture protocol"
            )
        path = self._registration_path(registration.registration_id)
        if path.exists():
            existing = CapacityReleaseBookRegistration.from_dict(
                self._read(path)
            )
            if existing != registration:
                raise CapacityReleaseBookEvidenceError(
                    "registration identity collision"
                )
            return False
        self._write(path, registration.to_dict())
        return True

    def _matching_position(
        self,
        registration: CapacityReleaseBookRegistration,
        positions: Sequence[PaperPosition],
    ) -> PaperPosition | None:
        matches = tuple(
            position
            for position in positions
            if position.market.canonical
            == registration.release_market
            and position.side.value
            == registration.release_direction
            and position.opened_at_ms
            <= registration.opportunity_timestamp_ms
        )
        return matches[0] if len(matches) == 1 else None

    def capture(
        self,
        *,
        positions: Sequence[PaperPosition],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        reference_price: Decimal,
        now_ms: int,
    ) -> int:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        if book.kind is not StreamKind.L2_BOOK:
            return 0
        observed_at_ms = _received_ms(book)
        captured = 0
        for registration in self.iter_registrations():
            registration_id = registration.registration_id
            record_path = self._record_path(registration_id)
            if record_path.exists():
                continue
            if registration.release_market != book.market.canonical:
                continue

            pending_path = self._pending_path(registration_id)
            if not pending_path.exists():
                if observed_at_ms < registration.opportunity_timestamp_ms:
                    continue
                if (
                    observed_at_ms
                    - registration.opportunity_timestamp_ms
                    > self.max_book_age_ms
                ):
                    continue
                if (
                    book.exchange_time_ms is None
                    or book.exchange_time_ms
                    < registration.opportunity_timestamp_ms
                ):
                    continue
                position = self._matching_position(
                    registration,
                    positions,
                )
                if position is None:
                    continue
                pending = PendingCapacityReleaseExecution(
                    registration=registration,
                    release_position=position,
                    plan_observed_at_ms=observed_at_ms,
                    plan_reference_price=reference_price,
                    plan_book_event=book,
                    plan_instrument=instrument,
                    execution_config=self.execution_config,
                )
                self._write(pending_path, pending.to_dict())
                continue

            pending = PendingCapacityReleaseExecution.from_dict(
                self._read(pending_path)
            )
            earliest_execution_ms = (
                pending.plan_observed_at_ms + self.latency_ms
            )
            if observed_at_ms < earliest_execution_ms:
                continue
            if (
                observed_at_ms - earliest_execution_ms
                > self.max_book_age_ms
            ):
                continue
            if (
                book.exchange_time_ms is None
                or book.exchange_time_ms < earliest_execution_ms
            ):
                continue
            evidence = CapacityReleaseBookEvidence(
                pending=pending,
                execution_observed_at_ms=observed_at_ms,
                execution_book_event=book,
                execution_instrument=instrument,
            )
            self._write(record_path, evidence.to_dict())
            pending_path.unlink(missing_ok=True)
            captured += 1
        return captured

    def iter_registrations(
        self,
    ) -> tuple[CapacityReleaseBookRegistration, ...]:
        return tuple(
            CapacityReleaseBookRegistration.from_dict(
                self._read(path)
            )
            for path in sorted(self.registrations_root.glob("*.json"))
        )

    def iter_pending(
        self,
    ) -> tuple[PendingCapacityReleaseExecution, ...]:
        return tuple(
            PendingCapacityReleaseExecution.from_dict(
                self._read(path)
            )
            for path in sorted(self.pending_root.glob("*.json"))
        )

    def iter_records(
        self,
    ) -> tuple[CapacityReleaseBookEvidence, ...]:
        return tuple(
            CapacityReleaseBookEvidence.from_dict(self._read(path))
            for path in sorted(self.records_root.glob("*.json"))
        )

    def summary(self, *, now_ms: int) -> dict[str, object]:
        registrations = self.iter_registrations()
        pending = self.iter_pending()
        records = self.iter_records()
        pending_ids = {
            item.registration.registration_id for item in pending
        }
        recorded_ids = {
            item.registration.registration_id for item in records
        }
        missed_plan = 0
        missed_execution = 0
        for registration in registrations:
            registration_id = registration.registration_id
            if registration_id in recorded_ids:
                continue
            if registration_id in pending_ids:
                staged = next(
                    item
                    for item in pending
                    if item.registration.registration_id
                    == registration_id
                )
                if now_ms > (
                    staged.plan_observed_at_ms
                    + self.latency_ms
                    + self.max_book_age_ms
                ):
                    missed_execution += 1
                continue
            if now_ms > (
                registration.opportunity_timestamp_ms
                + self.max_book_age_ms
            ):
                missed_plan += 1
        active_pending = (
            len(registrations)
            - len(records)
            - missed_plan
            - missed_execution
        )
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "changes_risk_limits": False,
            "changes_entry_priority": False,
            "capture_started_at_ms": self.capture_started_at_ms,
            "latency_ms": self.latency_ms,
            "max_book_age_ms": self.max_book_age_ms,
            "registrations": len(registrations),
            "plan_staged": len(pending),
            "captured": len(records),
            "execution_config_bound_captured": sum(
                item.pending.execution_config is not None
                for item in records
            ),
            "execution_config_unbound_captured": sum(
                item.pending.execution_config is None
                for item in records
            ),
            "pending": active_pending,
            "missed_plan": missed_plan,
            "missed_execution": missed_execution,
            "schema_version": SCHEMA_VERSION,
        }


class CapacityReleaseBookCapture:
    def __init__(self, store: CapacityReleaseBookStore) -> None:
        self.store = store
        self.error: str | None = None

    def register_from_trace(
        self,
        trace: BaselineOpeningTrace,
        *,
        opportunity_id: str,
    ) -> None:
        decision = trace.submission.risk_decision
        if decision.approved:
            return
        if CORRELATION_BUCKET_REASON not in decision.reason_codes:
            return
        request = trace.risk_request
        for position in request.open_positions:
            if position.correlation_bucket != request.correlation_bucket:
                continue
            if position.market == request.market:
                continue
            try:
                self.store.register(
                    CapacityReleaseBookRegistration(
                        opportunity_id=opportunity_id,
                        opportunity_timestamp_ms=request.timestamp_ms,
                        opportunity_market=request.market.canonical,
                        opportunity_direction=request.direction.value,
                        release_market=position.market.canonical,
                        release_direction=position.direction.value,
                        release_correlation_bucket=(
                            position.correlation_bucket
                        ),
                        strategy_decision_id=(
                            request.strategy_decision_id
                        ),
                        risk_decision_id=decision.risk_decision_id,
                    )
                )
            except Exception as exc:
                if self.error is None:
                    self.error = f"{type(exc).__name__}: {exc}"

    def observe_mark(
        self,
        positions: Sequence[PaperPosition],
        mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        del positions, mark_event, now_ms

    def observe_book(
        self,
        positions: Sequence[PaperPosition],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        now_ms: int,
    ) -> None:
        try:
            self.store.capture(
                positions=positions,
                instrument=instrument,
                book=book,
                reference_price=reference_price,
                now_ms=now_ms,
            )
        except Exception as exc:
            if self.error is None:
                self.error = f"{type(exc).__name__}: {exc}"

    def record_closed_trade(self, trade: TradeJournalEntry) -> None:
        del trade
