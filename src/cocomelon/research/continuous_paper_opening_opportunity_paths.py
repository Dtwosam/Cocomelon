from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

SCHEMA_VERSION: Final = 1
DEFAULT_MAX_PATH_AGE_MS: Final = 21_600_000
DEFAULT_MAX_COMPLETION_LAG_MS: Final = 120_000
ZERO: Final = Decimal("0")


class ContinuousPaperOpeningOpportunityPathError(RuntimeError):
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
        raise ContinuousPaperOpeningOpportunityPathError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ContinuousPaperOpeningOpportunityPathError(
            f"{field} must be finite"
        )
    return resolved


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


@dataclass(frozen=True, slots=True)
class ContinuousPaperOpeningOpportunityPathMark:
    observed_at_ms: int
    mark_px: Decimal
    source: str

    def __post_init__(self) -> None:
        if self.observed_at_ms < 0:
            raise ValueError("observed_at_ms must be non-negative")
        if not self.mark_px.is_finite() or self.mark_px <= ZERO:
            raise ValueError("mark_px must be positive and finite")
        _require_nonempty(self.source, "source")

    def to_dict(self) -> dict[str, object]:
        return {
            "observed_at_ms": self.observed_at_ms,
            "mark_px": str(self.mark_px),
            "source": self.source,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ContinuousPaperOpeningOpportunityPathMark:
        if not isinstance(raw, dict) or set(raw) != {
            "observed_at_ms",
            "mark_px",
            "source",
        }:
            raise ContinuousPaperOpeningOpportunityPathError(
                "OPENING_OPPORTUNITY_PATH_MARK_INVALID"
            )
        observed_at_ms = raw["observed_at_ms"]
        source = raw["source"]
        if isinstance(observed_at_ms, bool) or not isinstance(
            observed_at_ms,
            int,
        ):
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity mark timestamp must be an integer"
            )
        if not isinstance(source, str):
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity mark source must be a string"
            )
        try:
            return cls(
                observed_at_ms=observed_at_ms,
                mark_px=_decimal(raw["mark_px"], "mark_px"),
                source=source,
            )
        except ValueError as exc:
            raise ContinuousPaperOpeningOpportunityPathError(
                "OPENING_OPPORTUNITY_PATH_MARK_INVALID"
            ) from exc


@dataclass(frozen=True, slots=True)
class ContinuousPaperOpeningOpportunityPath:
    opportunity_id: str
    market: str
    direction: str
    opportunity_timestamp_ms: int
    max_path_age_ms: int
    max_completion_lag_ms: int
    marks: tuple[ContinuousPaperOpeningOpportunityPathMark, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.opportunity_id, "opportunity_id")
        _require_nonempty(self.market, "market")
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.opportunity_timestamp_ms < 0:
            raise ValueError(
                "opportunity_timestamp_ms must be non-negative"
            )
        if self.max_path_age_ms <= 0:
            raise ValueError("max_path_age_ms must be positive")
        if self.max_completion_lag_ms < 0:
            raise ValueError(
                "max_completion_lag_ms must be non-negative"
            )
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                "unsupported opening opportunity path schema"
            )
        previous_ms: int | None = None
        for mark in self.marks:
            if mark.observed_at_ms < self.opportunity_timestamp_ms:
                raise ValueError(
                    "opening opportunity path mark precedes opportunity"
                )
            if mark.observed_at_ms > self.completion_deadline_ms:
                raise ValueError(
                    "opening opportunity path mark follows completion deadline"
                )
            if (
                previous_ms is not None
                and mark.observed_at_ms <= previous_ms
            ):
                raise ValueError(
                    "opening opportunity path marks must be strictly ordered"
                )
            previous_ms = mark.observed_at_ms
        if self.complete:
            horizon_marks = tuple(
                mark
                for mark in self.marks
                if mark.observed_at_ms >= self.expires_at_ms
            )
            if len(horizon_marks) != 1:
                raise ValueError(
                    "complete opportunity path must stop at first horizon mark"
                )

    @property
    def expires_at_ms(self) -> int:
        return self.opportunity_timestamp_ms + self.max_path_age_ms

    @property
    def completion_deadline_ms(self) -> int:
        return self.expires_at_ms + self.max_completion_lag_ms

    @property
    def complete(self) -> bool:
        return any(
            mark.observed_at_ms >= self.expires_at_ms
            for mark in self.marks
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "market": self.market,
            "direction": self.direction,
            "opportunity_timestamp_ms": self.opportunity_timestamp_ms,
            "max_path_age_ms": self.max_path_age_ms,
            "max_completion_lag_ms": self.max_completion_lag_ms,
            "expires_at_ms": self.expires_at_ms,
            "completion_deadline_ms": self.completion_deadline_ms,
            "marks": [mark.to_dict() for mark in self.marks],
            "complete": self.complete,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ContinuousPaperOpeningOpportunityPath:
        if not isinstance(raw, dict):
            raise ContinuousPaperOpeningOpportunityPathError(
                "OPENING_OPPORTUNITY_PATH_INVALID"
            )
        expected = {
            "opportunity_id",
            "market",
            "direction",
            "opportunity_timestamp_ms",
            "max_path_age_ms",
            "max_completion_lag_ms",
            "expires_at_ms",
            "completion_deadline_ms",
            "marks",
            "complete",
            "schema_version",
        }
        if set(raw) != expected:
            raise ContinuousPaperOpeningOpportunityPathError(
                "OPENING_OPPORTUNITY_PATH_INVALID"
            )
        marks_raw = raw["marks"]
        if not isinstance(marks_raw, list):
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity path marks must be an array"
            )
        try:
            result = cls(
                opportunity_id=str(raw["opportunity_id"]),
                market=str(raw["market"]),
                direction=str(raw["direction"]),
                opportunity_timestamp_ms=int(
                    raw["opportunity_timestamp_ms"]
                ),
                max_path_age_ms=int(raw["max_path_age_ms"]),
                max_completion_lag_ms=int(
                    raw["max_completion_lag_ms"]
                ),
                marks=tuple(
                    ContinuousPaperOpeningOpportunityPathMark.from_dict(
                        item
                    )
                    for item in marks_raw
                ),
                schema_version=int(raw["schema_version"]),
            )
        except (TypeError, ValueError) as exc:
            raise ContinuousPaperOpeningOpportunityPathError(
                "OPENING_OPPORTUNITY_PATH_INVALID"
            ) from exc
        if raw["expires_at_ms"] != result.expires_at_ms:
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity path expiry mismatch"
            )
        if (
            raw["completion_deadline_ms"]
            != result.completion_deadline_ms
        ):
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity path deadline mismatch"
            )
        if raw["complete"] is not result.complete:
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity path completion mismatch"
            )
        return result


class ContinuousPaperOpeningOpportunityPathStore:
    def __init__(
        self,
        root: str | Path,
        *,
        max_path_age_ms: int,
        max_completion_lag_ms: int,
    ) -> None:
        if max_path_age_ms <= 0:
            raise ValueError("max_path_age_ms must be positive")
        if max_completion_lag_ms < 0:
            raise ValueError(
                "max_completion_lag_ms must be non-negative"
            )
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)
        self.max_path_age_ms = max_path_age_ms
        self.max_completion_lag_ms = max_completion_lag_ms
        self._paths_by_id: dict[
            str, ContinuousPaperOpeningOpportunityPath
        ] = {}
        self._active_by_market: dict[
            str,
            dict[str, ContinuousPaperOpeningOpportunityPath],
        ] = {}
        self._load_index_from_disk()

    @staticmethod
    def _record_name(opportunity_id: str) -> str:
        _require_nonempty(opportunity_id, "opportunity_id")
        return hashlib.sha256(
            opportunity_id.encode("utf-8")
        ).hexdigest() + ".json"

    def _path(self, opportunity_id: str) -> Path:
        return self.records_root / self._record_name(opportunity_id)

    @staticmethod
    def _encoded(
        path: ContinuousPaperOpeningOpportunityPath,
    ) -> bytes:
        return (_canonical_json(path.to_dict()) + "\n").encode(
            "utf-8"
        )

    def _write(
        self,
        path: ContinuousPaperOpeningOpportunityPath,
    ) -> None:
        target = self._path(path.opportunity_id)
        temporary = target.with_name(f".{target.name}.tmp")
        encoded = self._encoded(path)
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _index_path(
        self,
        path: ContinuousPaperOpeningOpportunityPath,
    ) -> None:
        self._paths_by_id[path.opportunity_id] = path
        market_paths = self._active_by_market.setdefault(
            path.market,
            {},
        )
        if path.complete:
            market_paths.pop(path.opportunity_id, None)
            if not market_paths:
                self._active_by_market.pop(path.market, None)
            return
        market_paths[path.opportunity_id] = path

    def _load_index_from_disk(self) -> None:
        for record_path in sorted(self.records_root.glob("*.json")):
            loaded = self._load_path(record_path)
            if loaded.opportunity_id in self._paths_by_id:
                raise ContinuousPaperOpeningOpportunityPathError(
                    "duplicate opening opportunity path id"
                )
            self._index_path(loaded)

    def register(
        self,
        *,
        opportunity_id: str,
        market: str,
        direction: str,
        opportunity_timestamp_ms: int,
    ) -> bool:
        proposed = ContinuousPaperOpeningOpportunityPath(
            opportunity_id=opportunity_id,
            market=market,
            direction=direction,
            opportunity_timestamp_ms=opportunity_timestamp_ms,
            max_path_age_ms=self.max_path_age_ms,
            max_completion_lag_ms=self.max_completion_lag_ms,
        )
        existing = self._paths_by_id.get(opportunity_id)
        if existing is None:
            existing_path = self._path(opportunity_id)
            if existing_path.exists():
                existing = self._load_path(existing_path)
                self._index_path(existing)
        if existing is not None:
            if (
                existing.market != proposed.market
                or existing.direction != proposed.direction
                or existing.opportunity_timestamp_ms
                != proposed.opportunity_timestamp_ms
                or existing.max_path_age_ms
                != proposed.max_path_age_ms
                or existing.max_completion_lag_ms
                != proposed.max_completion_lag_ms
            ):
                raise ContinuousPaperOpeningOpportunityPathError(
                    "OPENING_OPPORTUNITY_PATH_CONFLICT"
                )
            return False
        self._write(proposed)
        self._index_path(proposed)
        return True

    def _load_path(
        self,
        path: Path,
    ) -> ContinuousPaperOpeningOpportunityPath:
        try:
            raw_text = path.read_text(encoding="utf-8")
            raw = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            raise ContinuousPaperOpeningOpportunityPathError(
                "OPENING_OPPORTUNITY_PATH_UNREADABLE"
            ) from exc
        result = ContinuousPaperOpeningOpportunityPath.from_dict(raw)
        if path.name != self._record_name(result.opportunity_id):
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity path filename mismatch"
            )
        if raw_text != self._encoded(result).decode("utf-8"):
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity path is non-canonical"
            )
        if (
            result.max_path_age_ms != self.max_path_age_ms
            or result.max_completion_lag_ms
            != self.max_completion_lag_ms
        ):
            raise ContinuousPaperOpeningOpportunityPathError(
                "opening opportunity path configuration mismatch"
            )
        return result

    def load(
        self,
        opportunity_id: str,
    ) -> ContinuousPaperOpeningOpportunityPath | None:
        cached = self._paths_by_id.get(opportunity_id)
        if cached is not None:
            return cached
        path = self._path(opportunity_id)
        if not path.exists():
            return None
        loaded = self._load_path(path)
        self._index_path(loaded)
        return loaded

    def iter_paths(
        self,
    ) -> tuple[ContinuousPaperOpeningOpportunityPath, ...]:
        return tuple(
            sorted(
                self._paths_by_id.values(),
                key=lambda item: (
                    item.opportunity_timestamp_ms,
                    item.market,
                    item.opportunity_id,
                ),
            )
        )

    def observe(
        self,
        *,
        market: str,
        observed_at_ms: int,
        mark_px: Decimal,
        source: str,
    ) -> int:
        _require_nonempty(market, "market")
        if observed_at_ms < 0:
            raise ValueError("observed_at_ms must be non-negative")
        mark = ContinuousPaperOpeningOpportunityPathMark(
            observed_at_ms=observed_at_ms,
            mark_px=mark_px,
            source=source,
        )
        recorded = 0
        market_paths = tuple(
            sorted(
                self._active_by_market.get(market, {}).values(),
                key=lambda item: (
                    item.opportunity_timestamp_ms,
                    item.opportunity_id,
                ),
            )
        )
        for current in market_paths:
            if observed_at_ms < current.opportunity_timestamp_ms:
                continue
            if observed_at_ms > current.completion_deadline_ms:
                continue
            same_timestamp = tuple(
                existing
                for existing in current.marks
                if existing.observed_at_ms == observed_at_ms
            )
            if same_timestamp:
                if len(same_timestamp) != 1:
                    raise ContinuousPaperOpeningOpportunityPathError(
                        "OPENING_OPPORTUNITY_PATH_MARK_CONFLICT"
                    )
                if same_timestamp[0] != mark:
                    raise ContinuousPaperOpeningOpportunityPathError(
                        "OPENING_OPPORTUNITY_PATH_MARK_CONFLICT"
                    )
                continue
            if (
                current.marks
                and observed_at_ms
                < current.marks[-1].observed_at_ms
            ):
                raise ContinuousPaperOpeningOpportunityPathError(
                    "OPENING_OPPORTUNITY_PATH_MARK_OUT_OF_ORDER"
                )
            updated = ContinuousPaperOpeningOpportunityPath(
                opportunity_id=current.opportunity_id,
                market=current.market,
                direction=current.direction,
                opportunity_timestamp_ms=(
                    current.opportunity_timestamp_ms
                ),
                max_path_age_ms=current.max_path_age_ms,
                max_completion_lag_ms=(
                    current.max_completion_lag_ms
                ),
                marks=(*current.marks, mark),
                schema_version=current.schema_version,
            )
            self._write(updated)
            self._index_path(updated)
            recorded += 1
        return recorded

    @property
    def record_count(self) -> int:
        return len(self.iter_paths())

    @property
    def complete_count(self) -> int:
        return sum(1 for path in self.iter_paths() if path.complete)

    @property
    def state_digest(self) -> str:
        return _digest(
            tuple(path.to_dict() for path in self.iter_paths())
        )
