from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind

SCHEMA_VERSION: Final = 1
ZERO: Final = Decimal("0")


class ContinuousPaperOpeningOpportunityExitBookError(RuntimeError):
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


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContinuousPaperOpeningOpportunityExitBookError(
            f"{field} must be a non-empty string"
        )
    return value


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            f"{field} must be a decimal"
        ) from exc
    if not result.is_finite():
        raise ContinuousPaperOpeningOpportunityExitBookError(
            f"{field} must be finite"
        )
    return result


def _market(canonical: str) -> MarketId:
    _require_text(canonical, "market")
    if ":" not in canonical:
        return MarketId(dex="", coin=canonical)
    dex, coin = canonical.split(":", 1)
    return MarketId(dex=dex, coin=coin)


def _receive_ms(event: StreamEvent) -> int:
    return int(event.receive_time.timestamp() * 1000)


def _level_payload(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != {"px", "sz", "n"}:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit book level is invalid"
        )
    px = _decimal(raw["px"], "px")
    sz = _decimal(raw["sz"], "sz")
    count = _require_int(raw["n"], "n")
    if px <= ZERO or sz < ZERO:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit book level economics are invalid"
        )
    return {"px": str(px), "sz": str(sz), "n": count}


def _book_payload(event: StreamEvent) -> dict[str, object]:
    if event.kind is not StreamKind.L2_BOOK:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit evidence requires an L2 book"
        )
    if event.exchange_time_ms is None:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit book requires exchange timestamp"
        )
    bids = event.payload.get("bids")
    asks = event.payload.get("asks")
    if not isinstance(bids, (tuple, list)) or not isinstance(
        asks,
        (tuple, list),
    ):
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit book levels are missing"
        )
    return {
        "market": event.market.canonical,
        "exchange_time_ms": event.exchange_time_ms,
        "received_at_ms": _receive_ms(event),
        "schema_version": event.schema_version,
        "source": event.source,
        "event_key": event.event_key,
        "bids": [_level_payload(item) for item in bids],
        "asks": [_level_payload(item) for item in asks],
    }


def _book_from_payload(raw: object) -> StreamEvent:
    if not isinstance(raw, dict):
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit book payload must be an object"
        )
    expected = {
        "market",
        "exchange_time_ms",
        "received_at_ms",
        "schema_version",
        "source",
        "event_key",
        "bids",
        "asks",
    }
    if set(raw) != expected:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit book payload fields are invalid"
        )
    bids_raw = raw["bids"]
    asks_raw = raw["asks"]
    if not isinstance(bids_raw, list) or not isinstance(asks_raw, list):
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit book sides must be arrays"
        )

    def rows(values: list[object]) -> tuple[dict[str, object], ...]:
        output: list[dict[str, object]] = []
        for item in values:
            encoded = _level_payload(item)
            output.append(
                {
                    "px": Decimal(str(encoded["px"])),
                    "sz": Decimal(str(encoded["sz"])),
                    "n": encoded["n"],
                }
            )
        return tuple(output)

    received_at_ms = _require_int(
        raw["received_at_ms"],
        "received_at_ms",
    )
    return StreamEvent(
        kind=StreamKind.L2_BOOK,
        market=_market(_require_text(raw["market"], "market")),
        exchange_time_ms=_require_int(
            raw["exchange_time_ms"],
            "exchange_time_ms",
        ),
        receive_time=datetime.fromtimestamp(
            received_at_ms / 1000,
            tz=UTC,
        ),
        schema_version=_require_int(
            raw["schema_version"],
            "schema_version",
        ),
        source=_require_text(raw["source"], "source"),
        event_key=_require_text(raw["event_key"], "event_key"),
        payload={"bids": rows(bids_raw), "asks": rows(asks_raw)},
    )


def _instrument_payload(
    instrument: InstrumentExecutionSpec,
) -> dict[str, object]:
    return {
        "market": instrument.market.canonical,
        "sz_decimals": instrument.sz_decimals,
        "venue_max_leverage": str(
            instrument.venue_max_leverage
        ),
        "minimum_order_notional": str(
            instrument.minimum_order_notional
        ),
        "metadata_received_at_ms": (
            instrument.metadata_received_at_ms
        ),
        "metadata_source": instrument.metadata_source,
    }


def _instrument_from_payload(
    raw: object,
) -> InstrumentExecutionSpec:
    if not isinstance(raw, dict):
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit instrument payload must be an object"
        )
    expected = {
        "market",
        "sz_decimals",
        "venue_max_leverage",
        "minimum_order_notional",
        "metadata_received_at_ms",
        "metadata_source",
    }
    if set(raw) != expected:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit instrument payload fields are invalid"
        )
    try:
        return InstrumentExecutionSpec(
            market=_market(
                _require_text(raw["market"], "market")
            ),
            sz_decimals=_require_int(
                raw["sz_decimals"],
                "sz_decimals",
            ),
            venue_max_leverage=_decimal(
                raw["venue_max_leverage"],
                "venue_max_leverage",
            ),
            minimum_order_notional=_decimal(
                raw["minimum_order_notional"],
                "minimum_order_notional",
            ),
            metadata_received_at_ms=_require_int(
                raw["metadata_received_at_ms"],
                "metadata_received_at_ms",
            ),
            metadata_source=_require_text(
                raw["metadata_source"],
                "metadata_source",
            ),
        )
    except ValueError as exc:
        raise ContinuousPaperOpeningOpportunityExitBookError(
            "exit instrument payload is invalid"
        ) from exc


@dataclass(frozen=True, slots=True)
class OpeningOpportunityExitBookRegistration:
    opportunity_id: str
    market: str
    direction: str
    opportunity_timestamp_ms: int

    def __post_init__(self) -> None:
        if not self.opportunity_id.strip():
            raise ValueError("opportunity_id must not be empty")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.opportunity_timestamp_ms < 0:
            raise ValueError(
                "opportunity_timestamp_ms must be non-negative"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "market": self.market,
            "direction": self.direction,
            "opportunity_timestamp_ms": (
                self.opportunity_timestamp_ms
            ),
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> OpeningOpportunityExitBookRegistration:
        if not isinstance(raw, dict) or set(raw) != {
            "opportunity_id",
            "market",
            "direction",
            "opportunity_timestamp_ms",
        }:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book registration is invalid"
            )
        try:
            return cls(
                opportunity_id=_require_text(
                    raw["opportunity_id"],
                    "opportunity_id",
                ),
                market=_require_text(raw["market"], "market"),
                direction=_require_text(
                    raw["direction"],
                    "direction",
                ),
                opportunity_timestamp_ms=_require_int(
                    raw["opportunity_timestamp_ms"],
                    "opportunity_timestamp_ms",
                ),
            )
        except ValueError as exc:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book registration is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class OpeningOpportunityExitBookRequest:
    opportunity_id: str
    market: str
    direction: str
    opportunity_timestamp_ms: int
    horizon_ms: int
    target_at_ms: int

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if (
            self.target_at_ms
            != self.opportunity_timestamp_ms + self.horizon_ms
        ):
            raise ValueError("target_at_ms does not match horizon")


@dataclass(frozen=True, slots=True)
class OpeningOpportunityExitBookEvidence:
    opportunity_id: str
    market: str
    direction: str
    opportunity_timestamp_ms: int
    horizon_ms: int
    target_at_ms: int
    observed_at_ms: int
    observation_lag_ms: int
    book_event: StreamEvent
    instrument: InstrumentExecutionSpec
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if (
            self.target_at_ms
            != self.opportunity_timestamp_ms + self.horizon_ms
        ):
            raise ValueError("target_at_ms does not match horizon")
        if self.observed_at_ms < self.target_at_ms:
            raise ValueError("observed_at_ms precedes target")
        if (
            self.observation_lag_ms
            != self.observed_at_ms - self.target_at_ms
        ):
            raise ValueError("observation_lag_ms mismatch")
        if self.book_event.market.canonical != self.market:
            raise ValueError("exit book market mismatch")
        if self.instrument.market.canonical != self.market:
            raise ValueError("exit instrument market mismatch")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported exit book schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "market": self.market,
            "direction": self.direction,
            "opportunity_timestamp_ms": (
                self.opportunity_timestamp_ms
            ),
            "horizon_ms": self.horizon_ms,
            "target_at_ms": self.target_at_ms,
            "observed_at_ms": self.observed_at_ms,
            "observation_lag_ms": self.observation_lag_ms,
            "book": _book_payload(self.book_event),
            "instrument": _instrument_payload(self.instrument),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> OpeningOpportunityExitBookEvidence:
        if not isinstance(raw, dict) or set(raw) != {
            "opportunity_id",
            "market",
            "direction",
            "opportunity_timestamp_ms",
            "horizon_ms",
            "target_at_ms",
            "observed_at_ms",
            "observation_lag_ms",
            "book",
            "instrument",
            "schema_version",
        }:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book evidence is invalid"
            )
        try:
            return cls(
                opportunity_id=_require_text(
                    raw["opportunity_id"],
                    "opportunity_id",
                ),
                market=_require_text(raw["market"], "market"),
                direction=_require_text(
                    raw["direction"],
                    "direction",
                ),
                opportunity_timestamp_ms=_require_int(
                    raw["opportunity_timestamp_ms"],
                    "opportunity_timestamp_ms",
                ),
                horizon_ms=_require_int(
                    raw["horizon_ms"],
                    "horizon_ms",
                ),
                target_at_ms=_require_int(
                    raw["target_at_ms"],
                    "target_at_ms",
                ),
                observed_at_ms=_require_int(
                    raw["observed_at_ms"],
                    "observed_at_ms",
                ),
                observation_lag_ms=_require_int(
                    raw["observation_lag_ms"],
                    "observation_lag_ms",
                ),
                book_event=_book_from_payload(raw["book"]),
                instrument=_instrument_from_payload(
                    raw["instrument"]
                ),
                schema_version=_require_int(
                    raw["schema_version"],
                    "schema_version",
                ),
            )
        except ValueError as exc:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book evidence is invalid"
            ) from exc


class ContinuousPaperOpeningOpportunityExitBookStore:
    def __init__(
        self,
        root: str | Path,
        *,
        capture_started_at_ms: int,
        horizons_ms: tuple[int, ...],
        max_capture_lag_ms: int,
    ) -> None:
        if capture_started_at_ms < 0:
            raise ValueError(
                "capture_started_at_ms must be non-negative"
            )
        if (
            not horizons_ms
            or tuple(sorted(set(horizons_ms))) != horizons_ms
            or any(value <= 0 for value in horizons_ms)
        ):
            raise ValueError(
                "horizons_ms must be positive and strictly increasing"
            )
        if max_capture_lag_ms < 0:
            raise ValueError(
                "max_capture_lag_ms must be non-negative"
            )
        self.root = Path(root)
        self.registrations_root = self.root / "registrations"
        self.records_root = self.root / "records"
        self.protocol_path = self.root / "protocol.json"
        self.registrations_root.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.records_root.mkdir(parents=True, exist_ok=True)
        self.horizons_ms = horizons_ms
        self.max_capture_lag_ms = max_capture_lag_ms
        self.capture_started_at_ms = self._load_or_create_protocol(
            capture_started_at_ms
        )

    @staticmethod
    def _write(path: Path, value: object) -> None:
        encoded = _canonical_json(value).encode("utf-8")
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with tmp.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()

    @staticmethod
    def _read(path: Path) -> object:
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book evidence file is unreadable"
            ) from exc
        if _canonical_json(parsed) != raw:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book evidence file is non-canonical"
            )
        return parsed

    def _load_or_create_protocol(
        self,
        capture_started_at_ms: int,
    ) -> int:
        candidate = {
            "schema_version": SCHEMA_VERSION,
            "capture_started_at_ms": capture_started_at_ms,
            "horizons_ms": list(self.horizons_ms),
            "max_capture_lag_ms": self.max_capture_lag_ms,
        }
        if not self.protocol_path.exists():
            self._write(self.protocol_path, candidate)
            return capture_started_at_ms
        raw = self._read(self.protocol_path)
        if not isinstance(raw, dict) or set(raw) != set(candidate):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book capture protocol is invalid"
            )
        if (
            raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("horizons_ms") != list(self.horizons_ms)
            or raw.get("max_capture_lag_ms")
            != self.max_capture_lag_ms
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book capture protocol configuration mismatch"
            )
        return _require_int(
            raw.get("capture_started_at_ms"),
            "capture_started_at_ms",
        )

    @staticmethod
    def _registration_name(opportunity_id: str) -> str:
        return hashlib.sha256(
            opportunity_id.encode("utf-8")
        ).hexdigest() + ".json"

    @staticmethod
    def _record_name(
        opportunity_id: str,
        horizon_ms: int,
    ) -> str:
        return hashlib.sha256(
            f"{opportunity_id}:{horizon_ms}".encode()
        ).hexdigest() + ".json"

    def _registration_path(self, opportunity_id: str) -> Path:
        return (
            self.registrations_root
            / self._registration_name(opportunity_id)
        )

    def _record_path(
        self,
        opportunity_id: str,
        horizon_ms: int,
    ) -> Path:
        return (
            self.records_root
            / self._record_name(opportunity_id, horizon_ms)
        )

    def register(
        self,
        *,
        opportunity_id: str,
        market: str,
        direction: str,
        opportunity_timestamp_ms: int,
    ) -> bool:
        if (
            opportunity_timestamp_ms
            < self.capture_started_at_ms
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "opening opportunity predates capture protocol"
            )
        candidate = OpeningOpportunityExitBookRegistration(
            opportunity_id=opportunity_id,
            market=market,
            direction=direction,
            opportunity_timestamp_ms=opportunity_timestamp_ms,
        )
        path = self._registration_path(opportunity_id)
        if path.exists():
            existing = OpeningOpportunityExitBookRegistration.from_dict(
                self._read(path)
            )
            if existing != candidate:
                raise ContinuousPaperOpeningOpportunityExitBookError(
                    "conflicting exit book registration"
                )
            return False
        self._write(path, candidate.to_dict())
        return True

    def _registration(
        self,
        opportunity_id: str,
    ) -> OpeningOpportunityExitBookRegistration:
        path = self._registration_path(opportunity_id)
        if not path.exists():
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book opportunity registration is missing"
            )
        registration = (
            OpeningOpportunityExitBookRegistration.from_dict(
                self._read(path)
            )
        )
        if path.name != self._registration_name(
            registration.opportunity_id
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book registration filename mismatch"
            )
        return registration

    def iter_registrations(
        self,
    ) -> tuple[OpeningOpportunityExitBookRegistration, ...]:
        rows = tuple(
            self._registration_from_path(path)
            for path in self.registrations_root.glob("*.json")
        )
        return tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.opportunity_timestamp_ms,
                    item.market,
                    item.opportunity_id,
                ),
            )
        )

    def _registration_from_path(
        self,
        path: Path,
    ) -> OpeningOpportunityExitBookRegistration:
        registration = (
            OpeningOpportunityExitBookRegistration.from_dict(
                self._read(path)
            )
        )
        if path.name != self._registration_name(
            registration.opportunity_id
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book registration filename mismatch"
            )
        return registration

    def request(
        self,
        opportunity_id: str,
        horizon_ms: int,
    ) -> OpeningOpportunityExitBookRequest:
        if horizon_ms not in self.horizons_ms:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book horizon is not configured"
            )
        registration = self._registration(opportunity_id)
        return OpeningOpportunityExitBookRequest(
            opportunity_id=registration.opportunity_id,
            market=registration.market,
            direction=registration.direction,
            opportunity_timestamp_ms=(
                registration.opportunity_timestamp_ms
            ),
            horizon_ms=horizon_ms,
            target_at_ms=(
                registration.opportunity_timestamp_ms
                + horizon_ms
            ),
        )

    def due_requests(
        self,
        *,
        now_ms: int,
    ) -> tuple[OpeningOpportunityExitBookRequest, ...]:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        output: list[OpeningOpportunityExitBookRequest] = []
        for registration in self.iter_registrations():
            for horizon_ms in self.horizons_ms:
                if self.load(
                    registration.opportunity_id,
                    horizon_ms,
                ) is not None:
                    continue
                request = self.request(
                    registration.opportunity_id,
                    horizon_ms,
                )
                if (
                    request.target_at_ms <= now_ms
                    <= request.target_at_ms
                    + self.max_capture_lag_ms
                ):
                    output.append(request)
        return tuple(
            sorted(
                output,
                key=lambda item: (
                    item.target_at_ms,
                    item.market,
                    item.opportunity_id,
                    item.horizon_ms,
                ),
            )
        )

    def capture(
        self,
        request: OpeningOpportunityExitBookRequest,
        book: StreamEvent,
        instrument: InstrumentExecutionSpec,
    ) -> bool:
        expected = self.request(
            request.opportunity_id,
            request.horizon_ms,
        )
        if request != expected:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book request lineage mismatch"
            )
        if book.kind is not StreamKind.L2_BOOK:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit evidence requires an L2 book"
            )
        if (
            book.market.canonical != request.market
            or instrument.market.canonical != request.market
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book market mismatch"
            )
        observed_at_ms = _receive_ms(book)
        if not (
            request.target_at_ms
            <= observed_at_ms
            <= request.target_at_ms
            + self.max_capture_lag_ms
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book observed outside capture lag"
            )
        if (
            book.exchange_time_ms is None
            or book.exchange_time_ms < request.target_at_ms
            or book.exchange_time_ms > observed_at_ms
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book exchange timestamp is invalid"
            )
        if instrument.metadata_received_at_ms > observed_at_ms:
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit instrument metadata is from the future"
            )
        evidence = OpeningOpportunityExitBookEvidence(
            opportunity_id=request.opportunity_id,
            market=request.market,
            direction=request.direction,
            opportunity_timestamp_ms=(
                request.opportunity_timestamp_ms
            ),
            horizon_ms=request.horizon_ms,
            target_at_ms=request.target_at_ms,
            observed_at_ms=observed_at_ms,
            observation_lag_ms=(
                observed_at_ms - request.target_at_ms
            ),
            book_event=book,
            instrument=instrument,
        )
        path = self._record_path(
            request.opportunity_id,
            request.horizon_ms,
        )
        if path.exists():
            existing = OpeningOpportunityExitBookEvidence.from_dict(
                self._read(path)
            )
            if existing != evidence:
                raise ContinuousPaperOpeningOpportunityExitBookError(
                    "conflicting exit book evidence"
                )
            return False
        self._write(path, evidence.to_dict())
        return True

    def load(
        self,
        opportunity_id: str,
        horizon_ms: int,
    ) -> OpeningOpportunityExitBookEvidence | None:
        path = self._record_path(opportunity_id, horizon_ms)
        if not path.exists():
            return None
        evidence = OpeningOpportunityExitBookEvidence.from_dict(
            self._read(path)
        )
        if path.name != self._record_name(
            evidence.opportunity_id,
            evidence.horizon_ms,
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book evidence filename mismatch"
            )
        return evidence

    def _record_from_path(
        self,
        path: Path,
    ) -> OpeningOpportunityExitBookEvidence:
        evidence = OpeningOpportunityExitBookEvidence.from_dict(
            self._read(path)
        )
        if path.name != self._record_name(
            evidence.opportunity_id,
            evidence.horizon_ms,
        ):
            raise ContinuousPaperOpeningOpportunityExitBookError(
                "exit book evidence filename mismatch"
            )
        return evidence

    def iter_records(
        self,
    ) -> tuple[OpeningOpportunityExitBookEvidence, ...]:
        rows = tuple(
            self._record_from_path(path)
            for path in self.records_root.glob("*.json")
        )
        return tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.target_at_ms,
                    item.market,
                    item.opportunity_id,
                    item.horizon_ms,
                ),
            )
        )

    def missed_count(self, *, now_ms: int) -> int:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        missed = 0
        for registration in self.iter_registrations():
            for horizon_ms in self.horizons_ms:
                if self.load(
                    registration.opportunity_id,
                    horizon_ms,
                ) is not None:
                    continue
                target = (
                    registration.opportunity_timestamp_ms
                    + horizon_ms
                )
                if now_ms > target + self.max_capture_lag_ms:
                    missed += 1
        return missed

    def pending_count(self, *, now_ms: int) -> int:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        pending = 0
        for registration in self.iter_registrations():
            for horizon_ms in self.horizons_ms:
                if self.load(
                    registration.opportunity_id,
                    horizon_ms,
                ) is not None:
                    continue
                target = (
                    registration.opportunity_timestamp_ms
                    + horizon_ms
                )
                if now_ms <= target + self.max_capture_lag_ms:
                    pending += 1
        return pending

    @property
    def registration_count(self) -> int:
        return len(self.iter_registrations())

    @property
    def capture_count(self) -> int:
        return len(self.iter_records())

    @property
    def state_digest(self) -> str:
        return _digest(
            {
                "protocol": self._read(self.protocol_path),
                "registrations": [
                    item.to_dict()
                    for item in self.iter_registrations()
                ],
                "records": [
                    item.to_dict()
                    for item in self.iter_records()
                ],
            }
        )
