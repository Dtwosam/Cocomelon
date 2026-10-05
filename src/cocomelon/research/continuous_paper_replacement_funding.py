from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from cocomelon.domain.market import FundingRate, PerpMarketSnapshot
from cocomelon.execution.funding import (
    FUNDING_INTERVAL_MS,
    funding_boundary_for_record_time,
)

SCHEMA_VERSION: Final = 1
ZERO: Final = Decimal("0")


class ContinuousPaperReplacementFundingError(RuntimeError):
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


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContinuousPaperReplacementFundingError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContinuousPaperReplacementFundingError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContinuousPaperReplacementFundingError(
            f"{field} must be a decimal"
        ) from exc
    if not result.is_finite():
        raise ContinuousPaperReplacementFundingError(
            f"{field} must be finite"
        )
    return result


@dataclass(frozen=True, slots=True)
class ReplacementFundingRegistration:
    opportunity_id: str
    market: str
    opportunity_timestamp_ms: int

    def __post_init__(self) -> None:
        if not self.opportunity_id.strip():
            raise ValueError("opportunity_id must not be empty")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.opportunity_timestamp_ms < 0:
            raise ValueError(
                "opportunity_timestamp_ms must be non-negative"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "market": self.market,
            "opportunity_timestamp_ms": self.opportunity_timestamp_ms,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ReplacementFundingRegistration:
        if not isinstance(raw, dict) or set(raw) != {
            "opportunity_id",
            "market",
            "opportunity_timestamp_ms",
        }:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding registration is invalid"
            )
        try:
            return cls(
                opportunity_id=_text(
                    raw["opportunity_id"],
                    "opportunity_id",
                ),
                market=_text(raw["market"], "market"),
                opportunity_timestamp_ms=_integer(
                    raw["opportunity_timestamp_ms"],
                    "opportunity_timestamp_ms",
                ),
            )
        except ValueError as exc:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding registration is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class ReplacementFundingBoundaryRequest:
    market: str
    boundary_ms: int

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.boundary_ms < 0:
            raise ValueError("boundary_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class ReplacementFundingOracleCandidate:
    market: str
    boundary_ms: int
    oracle_px: Decimal
    observed_at_ms: int
    source: str
    schema_version: int

    def __post_init__(self) -> None:
        if not self.market.strip() or not self.source.strip():
            raise ValueError("oracle candidate identity must not be empty")
        if self.boundary_ms < 0 or self.observed_at_ms < 0:
            raise ValueError("oracle candidate timestamps must be non-negative")
        if self.observed_at_ms > self.boundary_ms:
            raise ValueError("oracle candidate is after funding boundary")
        if not self.oracle_px.is_finite() or self.oracle_px <= ZERO:
            raise ValueError("oracle candidate price must be positive")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def oracle_age_ms(self) -> int:
        return self.boundary_ms - self.observed_at_ms

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "boundary_ms": self.boundary_ms,
            "oracle_px": str(self.oracle_px),
            "observed_at_ms": self.observed_at_ms,
            "source": self.source,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ReplacementFundingOracleCandidate:
        if not isinstance(raw, dict) or set(raw) != {
            "market",
            "boundary_ms",
            "oracle_px",
            "observed_at_ms",
            "source",
            "schema_version",
        }:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding oracle candidate is invalid"
            )
        try:
            return cls(
                market=_text(raw["market"], "market"),
                boundary_ms=_integer(
                    raw["boundary_ms"],
                    "boundary_ms",
                ),
                oracle_px=_decimal(raw["oracle_px"], "oracle_px"),
                observed_at_ms=_integer(
                    raw["observed_at_ms"],
                    "observed_at_ms",
                ),
                source=_text(raw["source"], "source"),
                schema_version=_integer(
                    raw["schema_version"],
                    "schema_version",
                ),
            )
        except ValueError as exc:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding oracle candidate is invalid"
            ) from exc


@dataclass(frozen=True, slots=True)
class ReplacementFundingBoundaryEvidence:
    market: str
    boundary_ms: int
    oracle_px: Decimal
    oracle_observed_at_ms: int
    oracle_age_ms: int
    oracle_source: str
    oracle_schema_version: int
    funding_rate: Decimal
    premium: Decimal
    funding_time_ms: int
    funding_received_at_ms: int
    funding_source: str
    funding_schema_version: int

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if not self.oracle_source.strip() or not self.funding_source.strip():
            raise ValueError("funding evidence sources must not be empty")
        for value, field in (
            (self.boundary_ms, "boundary_ms"),
            (self.oracle_observed_at_ms, "oracle_observed_at_ms"),
            (self.oracle_age_ms, "oracle_age_ms"),
            (self.funding_time_ms, "funding_time_ms"),
            (self.funding_received_at_ms, "funding_received_at_ms"),
        ):
            if value < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.oracle_observed_at_ms > self.boundary_ms:
            raise ValueError("oracle evidence is after funding boundary")
        if (
            self.boundary_ms - self.oracle_observed_at_ms
            != self.oracle_age_ms
        ):
            raise ValueError("oracle age does not match timestamps")
        if not self.oracle_px.is_finite() or self.oracle_px <= ZERO:
            raise ValueError("oracle_px must be positive and finite")
        if not self.funding_rate.is_finite() or not self.premium.is_finite():
            raise ValueError("funding values must be finite")
        if self.oracle_schema_version <= 0 or self.funding_schema_version <= 0:
            raise ValueError("schema versions must be positive")
        if funding_boundary_for_record_time(self.funding_time_ms) != (
            self.boundary_ms
        ):
            raise ValueError("funding time does not match boundary")

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "boundary_ms": self.boundary_ms,
            "oracle_px": str(self.oracle_px),
            "oracle_observed_at_ms": self.oracle_observed_at_ms,
            "oracle_age_ms": self.oracle_age_ms,
            "oracle_source": self.oracle_source,
            "oracle_schema_version": self.oracle_schema_version,
            "funding_rate": str(self.funding_rate),
            "premium": str(self.premium),
            "funding_time_ms": self.funding_time_ms,
            "funding_received_at_ms": self.funding_received_at_ms,
            "funding_source": self.funding_source,
            "funding_schema_version": self.funding_schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ReplacementFundingBoundaryEvidence:
        if not isinstance(raw, dict):
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence is invalid"
            )
        expected = {
            "market",
            "boundary_ms",
            "oracle_px",
            "oracle_observed_at_ms",
            "oracle_age_ms",
            "oracle_source",
            "oracle_schema_version",
            "funding_rate",
            "premium",
            "funding_time_ms",
            "funding_received_at_ms",
            "funding_source",
            "funding_schema_version",
        }
        if set(raw) != expected:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence is invalid"
            )
        try:
            return cls(
                market=_text(raw["market"], "market"),
                boundary_ms=_integer(raw["boundary_ms"], "boundary_ms"),
                oracle_px=_decimal(raw["oracle_px"], "oracle_px"),
                oracle_observed_at_ms=_integer(
                    raw["oracle_observed_at_ms"],
                    "oracle_observed_at_ms",
                ),
                oracle_age_ms=_integer(
                    raw["oracle_age_ms"],
                    "oracle_age_ms",
                ),
                oracle_source=_text(
                    raw["oracle_source"],
                    "oracle_source",
                ),
                oracle_schema_version=_integer(
                    raw["oracle_schema_version"],
                    "oracle_schema_version",
                ),
                funding_rate=_decimal(
                    raw["funding_rate"],
                    "funding_rate",
                ),
                premium=_decimal(raw["premium"], "premium"),
                funding_time_ms=_integer(
                    raw["funding_time_ms"],
                    "funding_time_ms",
                ),
                funding_received_at_ms=_integer(
                    raw["funding_received_at_ms"],
                    "funding_received_at_ms",
                ),
                funding_source=_text(
                    raw["funding_source"],
                    "funding_source",
                ),
                funding_schema_version=_integer(
                    raw["funding_schema_version"],
                    "funding_schema_version",
                ),
            )
        except ValueError as exc:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence is invalid"
            ) from exc


class ContinuousPaperReplacementFundingStore:
    def __init__(
        self,
        root: str | Path,
        *,
        capture_started_at_ms: int,
        max_window_ms: int,
        max_oracle_age_ms: int,
        max_funding_capture_lag_ms: int,
    ) -> None:
        if capture_started_at_ms < 0:
            raise ValueError("capture_started_at_ms must be non-negative")
        if max_window_ms <= 0:
            raise ValueError("max_window_ms must be positive")
        if max_oracle_age_ms <= 0:
            raise ValueError("max_oracle_age_ms must be positive")
        if max_funding_capture_lag_ms < 0:
            raise ValueError(
                "max_funding_capture_lag_ms must be non-negative"
            )
        self.root = Path(root)
        self.registrations_root = self.root / "registrations"
        self.candidates_root = self.root / "oracle-candidates"
        self.records_root = self.root / "records"
        self.protocol_path = self.root / "protocol.json"
        self.registrations_root.mkdir(parents=True, exist_ok=True)
        self.candidates_root.mkdir(parents=True, exist_ok=True)
        self.records_root.mkdir(parents=True, exist_ok=True)
        self.max_window_ms = max_window_ms
        self.max_oracle_age_ms = max_oracle_age_ms
        self.max_funding_capture_lag_ms = max_funding_capture_lag_ms
        self.capture_started_at_ms = self._load_or_create_protocol(
            capture_started_at_ms
        )
        self._registrations_cache = self._read_registrations()
        self._required_boundary_keys: set[tuple[str, int]] = set()
        self._required_boundaries_cache: tuple[
            ReplacementFundingBoundaryRequest,
            ...,
        ] = ()
        self._boundaries_by_market: dict[str, tuple[int, ...]] = {}
        self._markets_by_boundary: dict[int, tuple[str, ...]] = {}
        self._rebuild_boundary_index()

    @staticmethod
    def _write(path: Path, value: object) -> None:
        encoded = _canonical_json(value).encode("utf-8")
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _read(path: Path) -> object:
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence file is unreadable"
            ) from exc
        if _canonical_json(parsed) != raw:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence file is non-canonical"
            )
        return parsed

    def _load_or_create_protocol(
        self,
        capture_started_at_ms: int,
    ) -> int:
        candidate = {
            "schema_version": SCHEMA_VERSION,
            "capture_started_at_ms": capture_started_at_ms,
            "max_window_ms": self.max_window_ms,
            "max_oracle_age_ms": self.max_oracle_age_ms,
            "max_funding_capture_lag_ms": (
                self.max_funding_capture_lag_ms
            ),
        }
        if not self.protocol_path.exists():
            self._write(self.protocol_path, candidate)
            return capture_started_at_ms
        raw = self._read(self.protocol_path)
        if not isinstance(raw, dict) or set(raw) != set(candidate):
            raise ContinuousPaperReplacementFundingError(
                "replacement funding capture protocol is invalid"
            )
        if (
            raw.get("schema_version") != SCHEMA_VERSION
            or raw.get("max_window_ms") != self.max_window_ms
            or raw.get("max_oracle_age_ms") != self.max_oracle_age_ms
            or raw.get("max_funding_capture_lag_ms")
            != self.max_funding_capture_lag_ms
        ):
            raise ContinuousPaperReplacementFundingError(
                "replacement funding capture protocol mismatch"
            )
        return _integer(
            raw.get("capture_started_at_ms"),
            "capture_started_at_ms",
        )

    @staticmethod
    def _registration_name(opportunity_id: str) -> str:
        return hashlib.sha256(
            opportunity_id.encode("utf-8")
        ).hexdigest() + ".json"

    @staticmethod
    def _boundary_name(market: str, boundary_ms: int) -> str:
        return hashlib.sha256(
            f"{market}:{boundary_ms}".encode()
        ).hexdigest() + ".json"

    def _registration_path(self, opportunity_id: str) -> Path:
        return (
            self.registrations_root
            / self._registration_name(opportunity_id)
        )

    def _candidate_path(self, market: str, boundary_ms: int) -> Path:
        return self.candidates_root / self._boundary_name(
            market,
            boundary_ms,
        )

    def _record_path(self, market: str, boundary_ms: int) -> Path:
        return self.records_root / self._boundary_name(
            market,
            boundary_ms,
        )

    def register(
        self,
        *,
        opportunity_id: str,
        market: str,
        opportunity_timestamp_ms: int,
    ) -> bool:
        if opportunity_timestamp_ms < self.capture_started_at_ms:
            raise ContinuousPaperReplacementFundingError(
                "opening opportunity predates funding capture protocol"
            )
        candidate = ReplacementFundingRegistration(
            opportunity_id=opportunity_id,
            market=market,
            opportunity_timestamp_ms=opportunity_timestamp_ms,
        )
        path = self._registration_path(opportunity_id)
        if path.exists():
            existing = ReplacementFundingRegistration.from_dict(
                self._read(path)
            )
            if existing != candidate:
                raise ContinuousPaperReplacementFundingError(
                    "conflicting replacement funding registration"
                )
            self._cache_registration(existing)
            return False
        self._write(path, candidate.to_dict())
        self._cache_registration(candidate)
        return True

    def _read_registrations(
        self,
    ) -> tuple[ReplacementFundingRegistration, ...]:
        rows: list[ReplacementFundingRegistration] = []
        for path in self.registrations_root.glob("*.json"):
            registration = ReplacementFundingRegistration.from_dict(
                self._read(path)
            )
            if path.name != self._registration_name(
                registration.opportunity_id
            ):
                raise ContinuousPaperReplacementFundingError(
                    "replacement funding registration filename mismatch"
                )
            rows.append(registration)
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

    def iter_registrations(
        self,
    ) -> tuple[ReplacementFundingRegistration, ...]:
        return self._registrations_cache

    def _boundaries(
        self,
        registration: ReplacementFundingRegistration,
    ) -> tuple[int, ...]:
        first = (
            (registration.opportunity_timestamp_ms // FUNDING_INTERVAL_MS)
            + 1
        ) * FUNDING_INTERVAL_MS
        last = (
            registration.opportunity_timestamp_ms
            + self.max_window_ms
        )
        if first > last:
            return ()
        return tuple(
            range(first, last + 1, FUNDING_INTERVAL_MS)
        )

    def _rebuild_boundary_index(self) -> None:
        unique = {
            (registration.market, boundary_ms)
            for registration in self._registrations_cache
            for boundary_ms in self._boundaries(registration)
        }
        self._required_boundary_keys = unique
        self._required_boundaries_cache = tuple(
            ReplacementFundingBoundaryRequest(
                market=market,
                boundary_ms=boundary_ms,
            )
            for market, boundary_ms in sorted(
                unique,
                key=lambda item: (item[1], item[0]),
            )
        )
        by_market: dict[str, list[int]] = {}
        by_boundary: dict[int, list[str]] = {}
        for market, boundary_ms in unique:
            by_market.setdefault(market, []).append(boundary_ms)
            by_boundary.setdefault(boundary_ms, []).append(market)
        self._boundaries_by_market = {
            market: tuple(sorted(boundaries))
            for market, boundaries in by_market.items()
        }
        self._markets_by_boundary = {
            boundary_ms: tuple(sorted(markets))
            for boundary_ms, markets in by_boundary.items()
        }

    def _cache_registration(
        self,
        registration: ReplacementFundingRegistration,
    ) -> None:
        if any(
            item.opportunity_id == registration.opportunity_id
            for item in self._registrations_cache
        ):
            return
        self._registrations_cache = tuple(
            sorted(
                (*self._registrations_cache, registration),
                key=lambda item: (
                    item.opportunity_timestamp_ms,
                    item.market,
                    item.opportunity_id,
                ),
            )
        )
        self._rebuild_boundary_index()

    def required_boundaries(
        self,
    ) -> tuple[ReplacementFundingBoundaryRequest, ...]:
        return self._required_boundaries_cache

    def _load_candidate(
        self,
        market: str,
        boundary_ms: int,
    ) -> ReplacementFundingOracleCandidate | None:
        path = self._candidate_path(market, boundary_ms)
        if not path.exists():
            return None
        candidate = ReplacementFundingOracleCandidate.from_dict(
            self._read(path)
        )
        if (
            candidate.market != market
            or candidate.boundary_ms != boundary_ms
            or path.name != self._boundary_name(market, boundary_ms)
        ):
            raise ContinuousPaperReplacementFundingError(
                "replacement funding oracle candidate lineage mismatch"
            )
        if candidate.oracle_age_ms > self.max_oracle_age_ms:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding oracle candidate is stale"
            )
        return candidate

    def observe_snapshot(
        self,
        snapshot: PerpMarketSnapshot,
    ) -> bool:
        market = snapshot.meta.market.canonical
        if snapshot.context.market != snapshot.meta.market:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding snapshot market mismatch"
            )
        oracle_px = snapshot.context.oracle_px
        if (
            oracle_px is None
            or not oracle_px.is_finite()
            or oracle_px <= ZERO
        ):
            return False
        updated = False
        for request in self.required_boundaries():
            if request.market != market:
                continue
            if self.load(market, request.boundary_ms) is not None:
                continue
            observed_at_ms = snapshot.received_at_ms
            if observed_at_ms > request.boundary_ms:
                continue
            age_ms = request.boundary_ms - observed_at_ms
            if age_ms > self.max_oracle_age_ms:
                continue
            proposed = ReplacementFundingOracleCandidate(
                market=market,
                boundary_ms=request.boundary_ms,
                oracle_px=oracle_px,
                observed_at_ms=observed_at_ms,
                source=snapshot.source,
                schema_version=snapshot.schema_version,
            )
            existing = self._load_candidate(
                market,
                request.boundary_ms,
            )
            if existing is not None:
                if existing.observed_at_ms > proposed.observed_at_ms:
                    continue
                if existing.observed_at_ms == proposed.observed_at_ms:
                    if existing != proposed:
                        raise ContinuousPaperReplacementFundingError(
                            "conflicting replacement funding oracle candidate"
                        )
                    continue
            self._write(
                self._candidate_path(market, request.boundary_ms),
                proposed.to_dict(),
            )
            updated = True
        return updated

    def load(
        self,
        market: str,
        boundary_ms: int,
    ) -> ReplacementFundingBoundaryEvidence | None:
        path = self._record_path(market, boundary_ms)
        if not path.exists():
            return None
        evidence = ReplacementFundingBoundaryEvidence.from_dict(
            self._read(path)
        )
        if (
            evidence.market != market
            or evidence.boundary_ms != boundary_ms
            or path.name != self._boundary_name(market, boundary_ms)
        ):
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence lineage mismatch"
            )
        if evidence.oracle_age_ms > self.max_oracle_age_ms:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence oracle is stale"
            )
        if not (
            evidence.boundary_ms
            <= evidence.funding_received_at_ms
            <= evidence.boundary_ms
            + self.max_funding_capture_lag_ms
        ):
            raise ContinuousPaperReplacementFundingError(
                "replacement funding evidence received outside capture lag"
            )
        return evidence

    def iter_records(
        self,
    ) -> tuple[ReplacementFundingBoundaryEvidence, ...]:
        rows: list[ReplacementFundingBoundaryEvidence] = []
        for path in self.records_root.glob("*.json"):
            evidence = ReplacementFundingBoundaryEvidence.from_dict(
                self._read(path)
            )
            if path.name != self._boundary_name(
                evidence.market,
                evidence.boundary_ms,
            ):
                raise ContinuousPaperReplacementFundingError(
                    "replacement funding evidence filename mismatch"
                )
            rows.append(evidence)
        return tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.boundary_ms,
                    item.market,
                ),
            )
        )

    def due_requests(
        self,
        *,
        now_ms: int,
    ) -> tuple[ReplacementFundingBoundaryRequest, ...]:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        output: list[ReplacementFundingBoundaryRequest] = []
        for request in self.required_boundaries():
            if self.load(request.market, request.boundary_ms) is not None:
                continue
            if not (
                request.boundary_ms
                <= now_ms
                <= request.boundary_ms
                + self.max_funding_capture_lag_ms
            ):
                continue
            if self._load_candidate(
                request.market,
                request.boundary_ms,
            ) is None:
                continue
            output.append(request)
        return tuple(output)

    def capture(
        self,
        request: ReplacementFundingBoundaryRequest,
        rate: FundingRate,
    ) -> bool:
        requirements = {
            (item.market, item.boundary_ms)
            for item in self.required_boundaries()
        }
        if (request.market, request.boundary_ms) not in requirements:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding request is not registered"
            )
        candidate = self._load_candidate(
            request.market,
            request.boundary_ms,
        )
        if candidate is None:
            raise ContinuousPaperReplacementFundingError(
                "replacement funding oracle candidate is missing"
            )
        if rate.market.canonical != request.market:
            raise ContinuousPaperReplacementFundingError(
                "funding rate market mismatch"
            )
        if funding_boundary_for_record_time(rate.time_ms) != (
            request.boundary_ms
        ):
            raise ContinuousPaperReplacementFundingError(
                "funding rate boundary mismatch"
            )
        if not (
            request.boundary_ms
            <= rate.received_at_ms
            <= request.boundary_ms
            + self.max_funding_capture_lag_ms
        ):
            raise ContinuousPaperReplacementFundingError(
                "funding rate received outside capture lag"
            )
        evidence = ReplacementFundingBoundaryEvidence(
            market=request.market,
            boundary_ms=request.boundary_ms,
            oracle_px=candidate.oracle_px,
            oracle_observed_at_ms=candidate.observed_at_ms,
            oracle_age_ms=candidate.oracle_age_ms,
            oracle_source=candidate.source,
            oracle_schema_version=candidate.schema_version,
            funding_rate=rate.funding_rate,
            premium=rate.premium,
            funding_time_ms=rate.time_ms,
            funding_received_at_ms=rate.received_at_ms,
            funding_source=rate.source,
            funding_schema_version=rate.schema_version,
        )
        path = self._record_path(
            request.market,
            request.boundary_ms,
        )
        if path.exists():
            existing = self.load(
                request.market,
                request.boundary_ms,
            )
            if existing != evidence:
                raise ContinuousPaperReplacementFundingError(
                    "conflicting replacement funding evidence"
                )
            return False
        self._write(path, evidence.to_dict())
        return True

    def markets_for_boundary(
        self,
        boundary_ms: int,
    ) -> tuple[str, ...]:
        if boundary_ms < 0:
            raise ValueError("boundary_ms must be non-negative")
        return tuple(
            sorted(
                {
                    request.market
                    for request in self.required_boundaries()
                    if request.boundary_ms == boundary_ms
                    and self.load(
                        request.market,
                        request.boundary_ms,
                    )
                    is None
                }
            )
        )

    @property
    def registration_count(self) -> int:
        return len(self.iter_registrations())

    @property
    def required_boundary_count(self) -> int:
        return len(self.required_boundaries())

    @property
    def oracle_candidate_count(self) -> int:
        return len(tuple(self.candidates_root.glob("*.json")))

    @property
    def record_count(self) -> int:
        return len(self.iter_records())

    def missed_count(self, *, now_ms: int) -> int:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        return sum(
            1
            for request in self.required_boundaries()
            if self.load(request.market, request.boundary_ms) is None
            and now_ms
            > request.boundary_ms
            + self.max_funding_capture_lag_ms
        )

    def pending_count(self, *, now_ms: int) -> int:
        if now_ms < 0:
            raise ValueError("now_ms must be non-negative")
        return sum(
            1
            for request in self.required_boundaries()
            if self.load(request.market, request.boundary_ms) is None
            and now_ms
            <= request.boundary_ms
            + self.max_funding_capture_lag_ms
        )

    @property
    def state_digest(self) -> str:
        protocol = self._read(self.protocol_path)
        return _digest(
            {
                "protocol": protocol,
                "registrations": [
                    row.to_dict()
                    for row in self.iter_registrations()
                ],
                "oracle_candidates": [
                    ReplacementFundingOracleCandidate.from_dict(
                        self._read(path)
                    ).to_dict()
                    for path in sorted(
                        self.candidates_root.glob("*.json")
                    )
                ],
                "records": [
                    row.to_dict()
                    for row in self.iter_records()
                ],
            }
        )
