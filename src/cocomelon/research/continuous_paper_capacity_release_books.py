from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.evidence.openings import BaselineOpeningTrace
from cocomelon.execution.accounting import PaperPosition

SCHEMA_VERSION: Final = 1
CORRELATION_BUCKET_REASON: Final = "correlation_bucket_exhausted"
ZERO: Final = Decimal("0")


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


def _received_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


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
        or sz < ZERO
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
    required = {
        "market",
        "exchange_time_ms",
        "received_at_ms",
        "schema_version",
        "source",
        "event_key",
        "bids",
        "asks",
    }
    if set(raw) != required:
        raise CapacityReleaseBookEvidenceError(
            "capacity release book fields are invalid"
        )
    market_raw = raw["market"]
    if not isinstance(market_raw, str) or not market_raw:
        raise CapacityReleaseBookEvidenceError("book market is invalid")
    if ":" in market_raw:
        dex, coin = market_raw.split(":", 1)
    else:
        dex, coin = "", market_raw
    from cocomelon.domain.market import MarketId

    def levels(value: object) -> tuple[dict[str, object], ...]:
        if not isinstance(value, list):
            raise CapacityReleaseBookEvidenceError(
                "book levels must be an array"
            )
        return tuple(
            {
                "px": Decimal(str(_level_payload(item)["px"])),
                "sz": Decimal(str(_level_payload(item)["sz"])),
                "n": _level_payload(item)["n"],
            }
            for item in value
        )

    exchange_ms = raw["exchange_time_ms"]
    received_ms = raw["received_at_ms"]
    schema = raw["schema_version"]
    for value, field in (
        (exchange_ms, "exchange_time_ms"),
        (received_ms, "received_at_ms"),
        (schema, "schema_version"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CapacityReleaseBookEvidenceError(
                f"{field} must be a non-negative integer"
            )
    source = raw["source"]
    event_key = raw["event_key"]
    if not isinstance(source, str) or not source:
        raise CapacityReleaseBookEvidenceError("book source is invalid")
    if not isinstance(event_key, str) or not event_key:
        raise CapacityReleaseBookEvidenceError("book event key is invalid")
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=MarketId(dex=dex, coin=coin),
        exchange_time_ms=exchange_ms,
        receive_time=datetime.fromtimestamp(
            received_ms / 1000,
            tz=UTC,
        ),
        schema_version=schema,
        source=source,
        event_key=event_key,
        payload={
            "bids": levels(raw["bids"]),
            "asks": levels(raw["asks"]),
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
                opportunity_id=str(raw["opportunity_id"]),
                opportunity_timestamp_ms=int(
                    raw["opportunity_timestamp_ms"]
                ),
                opportunity_market=str(raw["opportunity_market"]),
                opportunity_direction=str(raw["opportunity_direction"]),
                release_market=str(raw["release_market"]),
                release_direction=str(raw["release_direction"]),
                release_correlation_bucket=str(
                    raw["release_correlation_bucket"]
                ),
                strategy_decision_id=str(raw["strategy_decision_id"]),
                risk_decision_id=str(raw["risk_decision_id"]),
                schema_version=int(raw["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CapacityReleaseBookEvidenceError(
                "registration is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class CapacityReleaseBookEvidence:
    registration: CapacityReleaseBookRegistration
    release_opening_plan_id: str
    release_opened_at_ms: int
    observed_at_ms: int
    observation_lag_ms: int
    book_event: StreamEvent
    instrument: InstrumentExecutionSpec
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.release_opening_plan_id.strip():
            raise ValueError(
                "release_opening_plan_id must not be empty"
            )
        if self.release_opened_at_ms < 0:
            raise ValueError("release_opened_at_ms must be non-negative")
        if self.observed_at_ms < self.registration.opportunity_timestamp_ms:
            raise ValueError("release book precedes opportunity")
        if self.observation_lag_ms != (
            self.observed_at_ms
            - self.registration.opportunity_timestamp_ms
        ):
            raise ValueError("observation_lag_ms mismatch")
        if (
            self.book_event.market.canonical
            != self.registration.release_market
        ):
            raise ValueError("release book market mismatch")
        if (
            self.instrument.market.canonical
            != self.registration.release_market
        ):
            raise ValueError("release instrument market mismatch")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported evidence schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "registration": self.registration.to_dict(),
            "release_opening_plan_id": self.release_opening_plan_id,
            "release_opened_at_ms": self.release_opened_at_ms,
            "observed_at_ms": self.observed_at_ms,
            "observation_lag_ms": self.observation_lag_ms,
            "book": _book_payload(self.book_event),
            "instrument": _instrument_payload(self.instrument),
            "schema_version": self.schema_version,
        }


class CapacityReleaseBookStore:
    def __init__(
        self,
        root: str | Path,
        *,
        capture_started_at_ms: int,
        max_capture_lag_ms: int,
    ) -> None:
        if capture_started_at_ms < 0:
            raise ValueError(
                "capture_started_at_ms must be non-negative"
            )
        if max_capture_lag_ms <= 0:
            raise ValueError("max_capture_lag_ms must be positive")
        self.root = Path(root)
        self.registrations_root = self.root / "registrations"
        self.records_root = self.root / "records"
        self.protocol_path = self.root / "protocol.json"
        self.registrations_root.mkdir(parents=True, exist_ok=True)
        self.records_root.mkdir(parents=True, exist_ok=True)
        self.max_capture_lag_ms = max_capture_lag_ms
        self.capture_started_at_ms = self._load_or_create_protocol(
            capture_started_at_ms
        )
        self._pending = {
            item.registration_id: item
            for item in self.iter_registrations()
            if not self._record_path(item.registration_id).exists()
        }

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
            "max_capture_lag_ms": self.max_capture_lag_ms,
        }
        if not self.protocol_path.exists():
            self._write(self.protocol_path, candidate)
            return started_at_ms
        raw = self._read(self.protocol_path)
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("max_capture_lag_ms") != self.max_capture_lag_ms
        ):
            raise CapacityReleaseBookEvidenceError(
                "capacity release protocol mismatch"
            )
        value = raw.get("capture_started_at_ms")
        if isinstance(value, bool) or not isinstance(value, int):
            raise CapacityReleaseBookEvidenceError(
                "capture_started_at_ms is invalid"
            )
        return value

    def _registration_path(self, registration_id: str) -> Path:
        return self.registrations_root / f"{registration_id}.json"

    def _record_path(self, registration_id: str) -> Path:
        return self.records_root / f"{registration_id}.json"

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
        if not self._record_path(registration.registration_id).exists():
            self._pending[registration.registration_id] = registration
        return True

    def capture(
        self,
        *,
        positions: tuple[PaperPosition, ...],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        now_ms: int,
    ) -> int:
        if book.kind is not StreamKind.L2_BOOK:
            return 0
        observed_at_ms = _received_ms(book)
        captured = 0
        for registration_id, registration in tuple(
            self._pending.items()
        ):
            if registration.release_market != book.market.canonical:
                continue
            if observed_at_ms < registration.opportunity_timestamp_ms:
                continue
            lag = observed_at_ms - registration.opportunity_timestamp_ms
            if lag > self.max_capture_lag_ms:
                continue
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
            if len(matches) != 1:
                continue
            position = matches[0]
            payload = CapacityReleaseBookEvidence(
                registration=registration,
                release_opening_plan_id=position.opening_plan_id,
                release_opened_at_ms=position.opened_at_ms,
                observed_at_ms=observed_at_ms,
                observation_lag_ms=lag,
                book_event=book,
                instrument=instrument,
            ).to_dict()
            self._write(self._record_path(registration_id), payload)
            del self._pending[registration_id]
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

    def iter_records(self) -> tuple[dict[str, object], ...]:
        values: list[dict[str, object]] = []
        for path in sorted(self.records_root.glob("*.json")):
            raw = self._read(path)
            if not isinstance(raw, dict):
                raise CapacityReleaseBookEvidenceError(
                    "capacity release record must be an object"
                )
            values.append(cast(dict[str, object], raw))
        return tuple(values)

    def summary(self, *, now_ms: int) -> dict[str, object]:
        registrations = self.iter_registrations()
        records = self.iter_records()
        expired = sum(
            registration.registration_id in self._pending
            and now_ms
            > registration.opportunity_timestamp_ms
            + self.max_capture_lag_ms
            for registration in registrations
        )
        return {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "changes_risk_limits": False,
            "changes_entry_priority": False,
            "capture_started_at_ms": self.capture_started_at_ms,
            "max_capture_lag_ms": self.max_capture_lag_ms,
            "registrations": len(registrations),
            "captured": len(records),
            "pending": len(self._pending) - expired,
            "missed": expired,
            "schema_version": SCHEMA_VERSION,
        }


class CapacityReleaseBookCapture:
    def __init__(self, store: CapacityReleaseBookStore) -> None:
        self.store = store
        self.error: str | None = None

    def record_opening_trace(self, trace: BaselineOpeningTrace) -> None:
        decision = trace.submission.risk_decision
        if decision.approved:
            return
        if CORRELATION_BUCKET_REASON not in decision.reason_codes:
            return
        request = trace.risk_request
        for position in request.open_positions:
            if position.correlation_bucket != request.correlation_bucket:
                continue
            try:
                self.store.register(
                    CapacityReleaseBookRegistration(
                        opportunity_id=trace.evaluation.decision.decision_id,
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
        positions: tuple[PaperPosition, ...],
        mark_event: StreamEvent,
        *,
        now_ms: int,
    ) -> None:
        del positions, mark_event, now_ms

    def observe_book(
        self,
        positions: tuple[PaperPosition, ...],
        instrument: InstrumentExecutionSpec,
        book: StreamEvent,
        *,
        reference_price: Decimal,
        now_ms: int,
    ) -> None:
        del reference_price
        try:
            self.store.capture(
                positions=positions,
                instrument=instrument,
                book=book,
                now_ms=now_ms,
            )
        except Exception as exc:
            if self.error is None:
                self.error = f"{type(exc).__name__}: {exc}"

    def record_closed_trade(self, trade: TradeJournalEntry) -> None:
        del trade
