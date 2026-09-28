from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from cocomelon.domain.execution import (
    InstrumentExecutionSpec,
    PaperOrderPlan,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.accounting import PaperPosition, PositionSide

SCHEMA_VERSION: Final = 1
ZERO: Final = Decimal("0")


class OriginalStopBookEvidenceError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise OriginalStopBookEvidenceError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise OriginalStopBookEvidenceError(
            f"{field} must be finite"
        )
    return resolved


def _receive_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


@dataclass(frozen=True, slots=True)
class StopBookLevel:
    price: Decimal
    quantity: Decimal
    order_count: int

    def __post_init__(self) -> None:
        if (
            not self.price.is_finite()
            or not self.quantity.is_finite()
            or self.price <= ZERO
            or self.quantity <= ZERO
        ):
            raise ValueError(
                "stop-book levels require positive finite price/quantity"
            )
        if self.order_count < 0:
            raise ValueError("order_count must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "px": str(self.price),
            "sz": str(self.quantity),
            "n": self.order_count,
        }

    @classmethod
    def from_dict(cls, raw: object) -> StopBookLevel:
        if not isinstance(raw, dict) or set(raw) != {"px", "sz", "n"}:
            raise OriginalStopBookEvidenceError(
                "stop-book level fields are invalid"
            )
        count = raw["n"]
        if isinstance(count, bool) or not isinstance(count, int):
            raise OriginalStopBookEvidenceError(
                "stop-book level order count must be an integer"
            )
        return cls(
            price=_decimal(raw["px"], "level price"),
            quantity=_decimal(raw["sz"], "level quantity"),
            order_count=count,
        )


def _levels(value: object) -> tuple[StopBookLevel, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes),
    ):
        raise OriginalStopBookEvidenceError(
            "stop-book levels must be a sequence"
        )
    result: list[StopBookLevel] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise OriginalStopBookEvidenceError(
                "stop-book level must be an object"
            )
        count = raw.get("n", 0)
        if isinstance(count, bool) or not isinstance(count, int):
            raise OriginalStopBookEvidenceError(
                "stop-book level order count must be an integer"
            )
        result.append(
            StopBookLevel(
                price=_decimal(raw.get("px"), "level price"),
                quantity=_decimal(raw.get("sz"), "level quantity"),
                order_count=count,
            )
        )
    if not result:
        raise OriginalStopBookEvidenceError(
            "stop-book side must not be empty"
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class OriginalStopCrossing:
    opening_plan_id: str
    market: str
    direction: str
    opened_at_ms: int
    original_stop: Decimal
    crossing_mark_event_key: str
    crossing_mark_price: Decimal
    crossing_mark_received_ms: int
    crossing_mark_exchange_ms: int | None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.opening_plan_id, "opening_plan_id"),
            (self.market, "market"),
            (self.direction, "direction"),
            (self.crossing_mark_event_key, "crossing_mark_event_key"),
        ):
            if not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.opened_at_ms < 0 or self.crossing_mark_received_ms < 0:
            raise ValueError("stop crossing timestamps must be non-negative")
        if (
            self.crossing_mark_exchange_ms is not None
            and self.crossing_mark_exchange_ms < 0
        ):
            raise ValueError(
                "crossing_mark_exchange_ms must be non-negative"
            )
        if self.crossing_mark_received_ms < self.opened_at_ms:
            raise ValueError(
                "stop crossing must not precede position opening"
            )
        for value, field in (
            (self.original_stop, "original_stop"),
            (self.crossing_mark_price, "crossing_mark_price"),
        ):
            if not value.is_finite() or value <= ZERO:
                raise ValueError(f"{field} must be positive and finite")
        if self.direction == "long":
            if self.crossing_mark_price > self.original_stop:
                raise ValueError(
                    "long crossing mark must be at/below original stop"
                )
        elif self.crossing_mark_price < self.original_stop:
            raise ValueError(
                "short crossing mark must be at/above original stop"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported stop-crossing schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "opening_plan_id": self.opening_plan_id,
            "market": self.market,
            "direction": self.direction,
            "opened_at_ms": self.opened_at_ms,
            "original_stop": str(self.original_stop),
            "crossing_mark_event_key": self.crossing_mark_event_key,
            "crossing_mark_price": str(self.crossing_mark_price),
            "crossing_mark_received_ms": self.crossing_mark_received_ms,
            "crossing_mark_exchange_ms": self.crossing_mark_exchange_ms,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: object) -> OriginalStopCrossing:
        if not isinstance(raw, dict):
            raise OriginalStopBookEvidenceError(
                "stop crossing must be an object"
            )
        expected = {
            "opening_plan_id",
            "market",
            "direction",
            "opened_at_ms",
            "original_stop",
            "crossing_mark_event_key",
            "crossing_mark_price",
            "crossing_mark_received_ms",
            "crossing_mark_exchange_ms",
            "schema_version",
        }
        if set(raw) != expected:
            raise OriginalStopBookEvidenceError(
                "stop crossing fields are invalid"
            )
        exchange_ms = raw["crossing_mark_exchange_ms"]
        return cls(
            opening_plan_id=str(raw["opening_plan_id"]),
            market=str(raw["market"]),
            direction=str(raw["direction"]),
            opened_at_ms=int(raw["opened_at_ms"]),
            original_stop=_decimal(
                raw["original_stop"],
                "original_stop",
            ),
            crossing_mark_event_key=str(
                raw["crossing_mark_event_key"]
            ),
            crossing_mark_price=_decimal(
                raw["crossing_mark_price"],
                "crossing_mark_price",
            ),
            crossing_mark_received_ms=int(
                raw["crossing_mark_received_ms"]
            ),
            crossing_mark_exchange_ms=(
                None if exchange_ms is None else int(exchange_ms)
            ),
            schema_version=int(raw["schema_version"]),
        )


@dataclass(frozen=True, slots=True)
class OriginalStopBookEvidence:
    crossing: OriginalStopCrossing
    book_event_key: str
    book_received_ms: int
    book_exchange_ms: int | None
    book_source: str
    book_schema_version: int
    reference_price: Decimal
    instrument_sz_decimals: int
    instrument_venue_max_leverage: Decimal
    instrument_minimum_order_notional: Decimal
    instrument_metadata_received_at_ms: int
    instrument_metadata_source: str
    bids: tuple[StopBookLevel, ...]
    asks: tuple[StopBookLevel, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.book_event_key.strip():
            raise ValueError("book_event_key must not be empty")
        if not self.book_source.strip():
            raise ValueError("book_source must not be empty")
        if not self.instrument_metadata_source.strip():
            raise ValueError(
                "instrument_metadata_source must not be empty"
            )
        if self.book_schema_version <= 0:
            raise ValueError("book_schema_version must be positive")
        if self.instrument_sz_decimals < 0:
            raise ValueError(
                "instrument_sz_decimals must be non-negative"
            )
        if self.instrument_metadata_received_at_ms < 0:
            raise ValueError(
                "instrument metadata timestamp must be non-negative"
            )
        for value, field in (
            (
                self.instrument_venue_max_leverage,
                "instrument_venue_max_leverage",
            ),
            (
                self.instrument_minimum_order_notional,
                "instrument_minimum_order_notional",
            ),
        ):
            if not value.is_finite() or value <= ZERO:
                raise ValueError(f"{field} must be positive and finite")
        if self.book_received_ms < self.crossing.crossing_mark_received_ms:
            raise ValueError(
                "stop execution book must not precede crossing mark"
            )
        if (
            self.book_exchange_ms is not None
            and self.book_exchange_ms < 0
        ):
            raise ValueError("book_exchange_ms must be non-negative")
        if (
            not self.reference_price.is_finite()
            or self.reference_price <= ZERO
        ):
            raise ValueError(
                "reference_price must be positive and finite"
            )
        if not self.bids or not self.asks:
            raise ValueError("stop execution book must have both sides")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported stop-book evidence schema")

    @property
    def opening_plan_id(self) -> str:
        return self.crossing.opening_plan_id

    @property
    def evidence_id(self) -> str:
        return _digest(self.identity_payload())

    def identity_payload(self) -> dict[str, object]:
        return {
            "crossing": self.crossing.to_dict(),
            "book_event_key": self.book_event_key,
            "book_received_ms": self.book_received_ms,
            "book_exchange_ms": self.book_exchange_ms,
            "book_source": self.book_source,
            "book_schema_version": self.book_schema_version,
            "reference_price": str(self.reference_price),
            "instrument_sz_decimals": self.instrument_sz_decimals,
            "instrument_venue_max_leverage": str(
                self.instrument_venue_max_leverage
            ),
            "instrument_minimum_order_notional": str(
                self.instrument_minimum_order_notional
            ),
            "instrument_metadata_received_at_ms": (
                self.instrument_metadata_received_at_ms
            ),
            "instrument_metadata_source": (
                self.instrument_metadata_source
            ),
            "bids": [level.to_dict() for level in self.bids],
            "asks": [level.to_dict() for level in self.asks],
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "evidence_id": self.evidence_id,
        }

    @classmethod
    def from_dict(cls, raw: object) -> OriginalStopBookEvidence:
        if not isinstance(raw, dict):
            raise OriginalStopBookEvidenceError(
                "stop-book evidence must be an object"
            )
        expected = {
            "crossing",
            "book_event_key",
            "book_received_ms",
            "book_exchange_ms",
            "book_source",
            "book_schema_version",
            "reference_price",
            "instrument_sz_decimals",
            "instrument_venue_max_leverage",
            "instrument_minimum_order_notional",
            "instrument_metadata_received_at_ms",
            "instrument_metadata_source",
            "bids",
            "asks",
            "schema_version",
            "evidence_id",
        }
        if set(raw) != expected:
            raise OriginalStopBookEvidenceError(
                "stop-book evidence fields are invalid"
            )
        bids = raw["bids"]
        asks = raw["asks"]
        if not isinstance(bids, list) or not isinstance(asks, list):
            raise OriginalStopBookEvidenceError(
                "stop-book evidence sides must be lists"
            )
        exchange_ms = raw["book_exchange_ms"]
        evidence = cls(
            crossing=OriginalStopCrossing.from_dict(raw["crossing"]),
            book_event_key=str(raw["book_event_key"]),
            book_received_ms=int(raw["book_received_ms"]),
            book_exchange_ms=(
                None if exchange_ms is None else int(exchange_ms)
            ),
            book_source=str(raw["book_source"]),
            book_schema_version=int(raw["book_schema_version"]),
            reference_price=_decimal(
                raw["reference_price"],
                "reference_price",
            ),
            instrument_sz_decimals=int(
                raw["instrument_sz_decimals"]
            ),
            instrument_venue_max_leverage=_decimal(
                raw["instrument_venue_max_leverage"],
                "instrument_venue_max_leverage",
            ),
            instrument_minimum_order_notional=_decimal(
                raw["instrument_minimum_order_notional"],
                "instrument_minimum_order_notional",
            ),
            instrument_metadata_received_at_ms=int(
                raw["instrument_metadata_received_at_ms"]
            ),
            instrument_metadata_source=str(
                raw["instrument_metadata_source"]
            ),
            bids=tuple(StopBookLevel.from_dict(item) for item in bids),
            asks=tuple(StopBookLevel.from_dict(item) for item in asks),
            schema_version=int(raw["schema_version"]),
        )
        if raw["evidence_id"] != evidence.evidence_id:
            raise OriginalStopBookEvidenceError(
                "stop-book evidence digest mismatch"
            )
        return evidence

    def instrument_spec(self) -> InstrumentExecutionSpec:
        return InstrumentExecutionSpec(
            market=_market_from_canonical(self.crossing.market),
            sz_decimals=self.instrument_sz_decimals,
            venue_max_leverage=self.instrument_venue_max_leverage,
            minimum_order_notional=(
                self.instrument_minimum_order_notional
            ),
            metadata_received_at_ms=(
                self.instrument_metadata_received_at_ms
            ),
            metadata_source=self.instrument_metadata_source,
        )

    def book_event(self) -> StreamEvent:
        return StreamEvent(
            kind=StreamKind.L2_BOOK,
            market=_market_from_canonical(self.crossing.market),
            exchange_time_ms=self.book_exchange_ms,
            receive_time=datetime.fromtimestamp(
                self.book_received_ms / 1000,
                tz=UTC,
            ),
            schema_version=self.book_schema_version,
            source=self.book_source,
            event_key=self.book_event_key,
            payload={
                "bids": tuple(
                    {
                        "px": item.price,
                        "sz": item.quantity,
                        "n": item.order_count,
                    }
                    for item in self.bids
                ),
                "asks": tuple(
                    {
                        "px": item.price,
                        "sz": item.quantity,
                        "n": item.order_count,
                    }
                    for item in self.asks
                ),
            },
        )


def _market_from_canonical(value: str):
    from cocomelon.domain.market import MarketId

    if ":" in value:
        dex = value.split(":", 1)[0]
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


class OriginalStopBookEvidenceStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.pending_root = self.root / "pending"
        self.records_root.mkdir(parents=True, exist_ok=True)
        self.pending_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _name(opening_plan_id: str) -> str:
        if not opening_plan_id.strip():
            raise ValueError("opening_plan_id must not be empty")
        return hashlib.sha256(
            opening_plan_id.encode("utf-8")
        ).hexdigest() + ".json"

    def _record_path(self, opening_plan_id: str) -> Path:
        return self.records_root / self._name(opening_plan_id)

    def _pending_path(self, opening_plan_id: str) -> Path:
        return self.pending_root / self._name(opening_plan_id)

    @staticmethod
    def _write(path: Path, payload: object) -> None:
        encoded = _canonical_json(payload)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(encoded, encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _read(path: Path) -> object:
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise OriginalStopBookEvidenceError(
                "stop-book evidence file is unreadable"
            ) from exc
        if _canonical_json(parsed) != raw:
            raise OriginalStopBookEvidenceError(
                "stop-book evidence file is non-canonical"
            )
        return parsed

    def evidence_for(
        self,
        opening_plan_id: str,
    ) -> OriginalStopBookEvidence | None:
        path = self._record_path(opening_plan_id)
        if not path.exists():
            return None
        return OriginalStopBookEvidence.from_dict(self._read(path))

    def pending_for(
        self,
        opening_plan_id: str,
    ) -> OriginalStopCrossing | None:
        path = self._pending_path(opening_plan_id)
        if not path.exists():
            return None
        return OriginalStopCrossing.from_dict(self._read(path))

    def stage(self, crossing: OriginalStopCrossing) -> bool:
        if self.evidence_for(crossing.opening_plan_id) is not None:
            return False
        path = self._pending_path(crossing.opening_plan_id)
        existing = self.pending_for(crossing.opening_plan_id)
        if existing is not None:
            if existing != crossing:
                raise OriginalStopBookEvidenceError(
                    "conflicting original-stop crossing evidence"
                )
            return False
        self._write(path, crossing.to_dict())
        return True

    def capture_book(
        self,
        crossing: OriginalStopCrossing,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        instrument: InstrumentExecutionSpec,
    ) -> bool:
        if book.kind is not StreamKind.L2_BOOK:
            raise OriginalStopBookEvidenceError(
                "stop execution evidence requires L2 book"
            )
        if book.market.canonical != crossing.market:
            raise OriginalStopBookEvidenceError(
                "stop execution book market mismatch"
            )
        if instrument.market != book.market:
            raise OriginalStopBookEvidenceError(
                "stop execution instrument market mismatch"
            )
        evidence = OriginalStopBookEvidence(
            crossing=crossing,
            book_event_key=book.event_key,
            book_received_ms=_receive_ms(book),
            book_exchange_ms=book.exchange_time_ms,
            book_source=book.source,
            book_schema_version=book.schema_version,
            reference_price=reference_price,
            instrument_sz_decimals=instrument.sz_decimals,
            instrument_venue_max_leverage=(
                instrument.venue_max_leverage
            ),
            instrument_minimum_order_notional=(
                instrument.minimum_order_notional
            ),
            instrument_metadata_received_at_ms=(
                instrument.metadata_received_at_ms
            ),
            instrument_metadata_source=instrument.metadata_source,
            bids=_levels(book.payload.get("bids")),
            asks=_levels(book.payload.get("asks")),
        )
        path = self._record_path(crossing.opening_plan_id)
        existing = self.evidence_for(crossing.opening_plan_id)
        if existing is not None:
            if existing != evidence:
                raise OriginalStopBookEvidenceError(
                    "conflicting stop execution book evidence"
                )
            return False
        self._write(path, evidence.to_dict())
        pending = self._pending_path(crossing.opening_plan_id)
        if pending.exists():
            pending.unlink()
        return True

    @property
    def record_count(self) -> int:
        return sum(1 for _ in self.records_root.glob("*.json"))

    @property
    def pending_count(self) -> int:
        return sum(1 for _ in self.pending_root.glob("*.json"))

    @property
    def state_digest(self) -> str:
        rows = [
            OriginalStopBookEvidence.from_dict(
                self._read(path)
            ).to_dict()
            for path in sorted(self.records_root.glob("*.json"))
        ]
        pending = [
            OriginalStopCrossing.from_dict(
                self._read(path)
            ).to_dict()
            for path in sorted(self.pending_root.glob("*.json"))
        ]
        return _digest({"records": rows, "pending": pending})


class OriginalStopBookCapture:
    def __init__(
        self,
        store: OriginalStopBookEvidenceStore,
        *,
        opening_plan_loader: Callable[
            [str],
            PaperOrderPlan | None,
        ],
    ) -> None:
        self.store = store
        self._opening_plan_loader = opening_plan_loader
        self.error: str | None = None

    def _fail(self, exc: Exception) -> None:
        if self.error is None:
            self.error = f"{type(exc).__name__}: {exc}"

    def _plan_for(
        self,
        position: PaperPosition,
    ) -> PaperOrderPlan:
        plan = self._opening_plan_loader(position.opening_plan_id)
        if plan is None:
            raise OriginalStopBookEvidenceError(
                "original-stop opening plan is missing"
            )
        if (
            plan.reduce_only
            or plan.market != position.market
            or plan.stop_price is None
        ):
            raise OriginalStopBookEvidenceError(
                "original-stop opening plan lineage mismatch"
            )
        return plan

    def observe_mark(
        self,
        positions: Sequence[PaperPosition],
        mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        if self.error is not None:
            return
        try:
            if mark_event.kind is not StreamKind.ACTIVE_ASSET_CTX:
                return
            matching = tuple(
                position
                for position in positions
                if position.market == mark_event.market
            )
            if not matching:
                return
            if len(matching) != 1:
                raise OriginalStopBookEvidenceError(
                    "duplicate positions for original-stop capture"
                )
            position = matching[0]
            if self.store.evidence_for(position.opening_plan_id) is not None:
                return
            if self.store.pending_for(position.opening_plan_id) is not None:
                return
            plan = self._plan_for(position)
            raw_mark = mark_event.payload.get("mark_px")
            if not isinstance(raw_mark, Decimal):
                raise OriginalStopBookEvidenceError(
                    "original-stop mark price is not Decimal"
                )
            stop = plan.stop_price
            if stop is None:
                raise OriginalStopBookEvidenceError(
                    "original-stop opening plan lost stop"
                )
            crossed = (
                raw_mark <= stop
                if position.side is PositionSide.LONG
                else raw_mark >= stop
            )
            if not crossed:
                return
            received_ms = _receive_ms(mark_event)
            if now_ms < received_ms:
                raise OriginalStopBookEvidenceError(
                    "original-stop capture consumed future mark"
                )
            self.store.stage(
                OriginalStopCrossing(
                    opening_plan_id=position.opening_plan_id,
                    market=position.market.canonical,
                    direction=position.side.value,
                    opened_at_ms=position.opened_at_ms,
                    original_stop=stop,
                    crossing_mark_event_key=mark_event.event_key,
                    crossing_mark_price=raw_mark,
                    crossing_mark_received_ms=received_ms,
                    crossing_mark_exchange_ms=(
                        mark_event.exchange_time_ms
                    ),
                )
            )
        except Exception as exc:
            self._fail(exc)

    def observe_book(
        self,
        positions: Sequence[PaperPosition],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        now_ms: int,
    ) -> None:
        if self.error is not None:
            return
        try:
            matching = tuple(
                position
                for position in positions
                if position.market == book.market
            )
            if not matching:
                return
            if len(matching) != 1:
                raise OriginalStopBookEvidenceError(
                    "duplicate positions for original-stop book capture"
                )
            position = matching[0]
            crossing = self.store.pending_for(
                position.opening_plan_id
            )
            if crossing is None:
                return
            if now_ms < _receive_ms(book):
                raise OriginalStopBookEvidenceError(
                    "original-stop capture consumed future book"
                )
            self.store.capture_book(
                crossing,
                book,
                reference_price=reference_price,
                instrument=instrument,
            )
        except Exception as exc:
            self._fail(exc)

    def record_closed_trade(
        self,
        trade: TradeJournalEntry,
    ) -> None:
        del trade
