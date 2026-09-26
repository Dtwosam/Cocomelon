from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord, SourceRecordKind

CONTINUOUS_PAPER_TRADE_PATH_SCHEMA_VERSION = 1


class ContinuousPaperTradePathError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _decimal(value: object, field: str) -> Decimal:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ContinuousPaperTradePathError(
            f"{field} must be a decimal"
        ) from exc
    if not resolved.is_finite():
        raise ContinuousPaperTradePathError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class ContinuousPaperTradePathMark:
    available_at_ms: int
    exchange_time_ms: int | None
    event_key: str
    mark_px: Decimal

    def __post_init__(self) -> None:
        if self.available_at_ms < 0:
            raise ValueError("available_at_ms must be non-negative")
        if self.exchange_time_ms is not None and self.exchange_time_ms < 0:
            raise ValueError("exchange_time_ms must be non-negative")
        _require_nonempty(self.event_key, "event_key")
        if not self.mark_px.is_finite() or self.mark_px <= 0:
            raise ValueError("mark_px must be positive and finite")

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (
            self.available_at_ms,
            -1 if self.exchange_time_ms is None else self.exchange_time_ms,
            self.event_key,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "available_at_ms": self.available_at_ms,
            "exchange_time_ms": self.exchange_time_ms,
            "event_key": self.event_key,
            "mark_px": str(self.mark_px),
        }

    @classmethod
    def from_dict(
        cls,
        raw: object,
    ) -> ContinuousPaperTradePathMark:
        if not isinstance(raw, dict) or set(raw) != {
            "available_at_ms",
            "exchange_time_ms",
            "event_key",
            "mark_px",
        }:
            raise ContinuousPaperTradePathError(
                "CONTINUOUS_PAPER_TRADE_PATH_MARK_INVALID"
            )
        available_at_ms = raw["available_at_ms"]
        exchange_time_ms = raw["exchange_time_ms"]
        event_key = raw["event_key"]
        if (
            isinstance(available_at_ms, bool)
            or not isinstance(available_at_ms, int)
        ):
            raise ContinuousPaperTradePathError(
                "trade path mark available_at_ms must be an integer"
            )
        if exchange_time_ms is not None and (
            isinstance(exchange_time_ms, bool)
            or not isinstance(exchange_time_ms, int)
        ):
            raise ContinuousPaperTradePathError(
                "trade path mark exchange_time_ms must be an integer or null"
            )
        if not isinstance(event_key, str):
            raise ContinuousPaperTradePathError(
                "trade path mark event_key must be a string"
            )
        try:
            return cls(
                available_at_ms=available_at_ms,
                exchange_time_ms=exchange_time_ms,
                event_key=event_key,
                mark_px=_decimal(raw["mark_px"], "mark_px"),
            )
        except ValueError as exc:
            raise ContinuousPaperTradePathError(
                "CONTINUOUS_PAPER_TRADE_PATH_MARK_INVALID"
            ) from exc


@dataclass(frozen=True, slots=True)
class ContinuousPaperTradePath:
    trade_id: str
    market: str
    direction: str
    opened_at_ms: int
    closed_at_ms: int
    entry_price: Decimal
    exit_price: Decimal
    initial_stop: Decimal
    initial_risk_amount: Decimal
    filled_quantity: Decimal
    excursion_complete: bool
    health_refs: tuple[str, ...]
    marks: tuple[ContinuousPaperTradePathMark, ...]
    known_gap_intervals: tuple[tuple[int, int | None], ...]
    schema_version: int = CONTINUOUS_PAPER_TRADE_PATH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in ("trade_id", "market", "direction"):
            _require_nonempty(str(getattr(self, field)), field)
        if self.direction not in {"long", "short"}:
            raise ValueError("direction must be long or short")
        if self.opened_at_ms < 0 or self.closed_at_ms < self.opened_at_ms:
            raise ValueError("trade path timestamps are invalid")
        for field in (
            "entry_price",
            "exit_price",
            "initial_stop",
            "filled_quantity",
        ):
            value = getattr(self, field)
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{field} must be positive and finite")
        if (
            not self.initial_risk_amount.is_finite()
            or self.initial_risk_amount < 0
        ):
            raise ValueError(
                "initial_risk_amount must be non-negative and finite"
            )
        if self.schema_version != CONTINUOUS_PAPER_TRADE_PATH_SCHEMA_VERSION:
            raise ValueError("unsupported continuous paper trade path schema")
        if tuple(sorted(set(self.health_refs))) != self.health_refs:
            raise ValueError("health_refs must be sorted and unique")
        previous_key: tuple[int, int, str] | None = None
        seen_event_keys: set[str] = set()
        for mark in self.marks:
            if not (
                self.opened_at_ms
                <= mark.available_at_ms
                <= self.closed_at_ms
            ):
                raise ValueError("trade path mark is outside lifecycle")
            if mark.event_key in seen_event_keys:
                raise ValueError("trade path mark event keys must be unique")
            seen_event_keys.add(mark.event_key)
            if previous_key is not None and mark.sort_key < previous_key:
                raise ValueError("trade path marks must be sorted")
            previous_key = mark.sort_key
        for started_ms, ended_ms in self.known_gap_intervals:
            if started_ms < 0:
                raise ValueError("gap start must be non-negative")
            if ended_ms is not None and ended_ms < started_ms:
                raise ValueError("gap end must not precede gap start")

    @property
    def path_complete(self) -> bool:
        return self.excursion_complete and bool(self.marks)

    def identity_payload(self) -> dict[str, object]:
        return {
            "trade_id": self.trade_id,
            "market": self.market,
            "direction": self.direction,
            "opened_at_ms": self.opened_at_ms,
            "closed_at_ms": self.closed_at_ms,
            "entry_price": str(self.entry_price),
            "exit_price": str(self.exit_price),
            "initial_stop": str(self.initial_stop),
            "initial_risk_amount": str(self.initial_risk_amount),
            "filled_quantity": str(self.filled_quantity),
            "excursion_complete": self.excursion_complete,
            "path_complete": self.path_complete,
            "health_refs": list(self.health_refs),
            "marks": [mark.to_dict() for mark in self.marks],
            "known_gap_intervals": [
                [started_ms, ended_ms]
                for started_ms, ended_ms in self.known_gap_intervals
            ],
            "schema_version": self.schema_version,
        }

    @property
    def path_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "path_id": self.path_id}


def _mark_from_record(
    record: ReplayRecord,
    *,
    market: str,
    opened_at_ms: int,
    closed_at_ms: int | None,
) -> ContinuousPaperTradePathMark:
    if record.record_kind is not SourceRecordKind.NORMALIZED_EVENT:
        raise ContinuousPaperTradePathError(
            "trade path marks must be normalized events"
        )
    if record.market != market:
        raise ContinuousPaperTradePathError(
            "trade path mark market mismatch"
        )
    if record.event_key is None:
        raise ContinuousPaperTradePathError(
            "trade path mark is missing event_key"
        )
    if record.available_at_ms < opened_at_ms:
        raise ContinuousPaperTradePathError(
            "trade path mark precedes lifecycle"
        )
    if (
        closed_at_ms is not None
        and record.available_at_ms > closed_at_ms
    ):
        raise ContinuousPaperTradePathError(
            "trade path mark follows lifecycle"
        )
    payload = record.payload
    if not isinstance(payload, dict):
        raise ContinuousPaperTradePathError(
            "trade path mark payload must be an object"
        )
    return ContinuousPaperTradePathMark(
        available_at_ms=record.available_at_ms,
        exchange_time_ms=record.exchange_time_ms,
        event_key=record.event_key,
        mark_px=_decimal(payload.get("mark_px"), "mark_px"),
    )


def _merge_marks(
    marks: Sequence[ContinuousPaperTradePathMark],
) -> tuple[ContinuousPaperTradePathMark, ...]:
    by_key: dict[str, ContinuousPaperTradePathMark] = {}
    for mark in marks:
        existing = by_key.get(mark.event_key)
        if existing is not None and existing != mark:
            raise ContinuousPaperTradePathError(
                "conflicting trade path mark event"
            )
        by_key[mark.event_key] = mark
    return tuple(sorted(by_key.values(), key=lambda mark: mark.sort_key))


def continuous_paper_trade_path(
    trade: TradeJournalEntry,
    marks: Sequence[ContinuousPaperTradePathMark],
    known_gap_intervals: Sequence[tuple[int, int | None]],
) -> ContinuousPaperTradePath:
    ordered_marks = _merge_marks(marks)
    mfe_complete = trade.mfe is not None and trade.mfe.complete
    mae_complete = trade.mae is not None and trade.mae.complete
    return ContinuousPaperTradePath(
        trade_id=trade.trade_id,
        market=trade.market.canonical,
        direction=trade.direction.value,
        opened_at_ms=trade.opened_at_ms,
        closed_at_ms=trade.closed_at_ms,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        initial_stop=trade.initial_stop,
        initial_risk_amount=trade.initial_risk_amount,
        filled_quantity=trade.filled_quantity,
        excursion_complete=mfe_complete and mae_complete,
        health_refs=tuple(sorted(set(trade.health_refs))),
        marks=ordered_marks,
        known_gap_intervals=tuple(known_gap_intervals),
    )


class ContinuousPaperTradePathStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.open_root = self.root / "open"
        self.records_root.mkdir(parents=True, exist_ok=True)
        self.open_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _record_name(identity: str, suffix: str) -> str:
        _require_nonempty(identity, "identity")
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return digest + suffix

    def _path(self, trade_id: str) -> Path:
        return self.records_root / self._record_name(trade_id, ".json")

    def _open_path(self, opening_plan_id: str) -> Path:
        return self.open_root / self._record_name(opening_plan_id, ".jsonl")

    @staticmethod
    def _open_header(
        *,
        opening_plan_id: str,
        market: str,
        opened_at_ms: int,
    ) -> dict[str, object]:
        return {
            "kind": "header",
            "schema_version": CONTINUOUS_PAPER_TRADE_PATH_SCHEMA_VERSION,
            "opening_plan_id": opening_plan_id,
            "market": market,
            "opened_at_ms": opened_at_ms,
        }

    @staticmethod
    def _open_mark_payload(
        mark: ContinuousPaperTradePathMark,
    ) -> dict[str, object]:
        return {"kind": "mark", **mark.to_dict()}

    def _load_open(
        self,
        opening_plan_id: str,
    ) -> tuple[dict[str, object] | None, tuple[ContinuousPaperTradePathMark, ...]]:
        path = self._open_path(opening_plan_id)
        if not path.exists():
            return None, ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ContinuousPaperTradePathError(
                "CONTINUOUS_PAPER_TRADE_PATH_OPEN_UNREADABLE"
            ) from exc
        if not lines:
            raise ContinuousPaperTradePathError(
                "CONTINUOUS_PAPER_TRADE_PATH_OPEN_EMPTY"
            )
        parsed: list[dict[str, object]] = []
        for line in lines:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_OPEN_INVALID"
                ) from exc
            if not isinstance(raw, dict) or not all(
                isinstance(key, str) for key in raw
            ):
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_OPEN_INVALID"
                )
            if _canonical_json(raw) != line:
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_OPEN_NON_CANONICAL"
                )
            parsed.append(raw)

        header = parsed[0]
        if (
            set(header)
            != {
                "kind",
                "schema_version",
                "opening_plan_id",
                "market",
                "opened_at_ms",
            }
            or header.get("kind") != "header"
            or header.get("schema_version")
            != CONTINUOUS_PAPER_TRADE_PATH_SCHEMA_VERSION
            or header.get("opening_plan_id") != opening_plan_id
        ):
            raise ContinuousPaperTradePathError(
                "CONTINUOUS_PAPER_TRADE_PATH_OPEN_HEADER_INVALID"
            )
        marks: list[ContinuousPaperTradePathMark] = []
        for raw in parsed[1:]:
            if raw.get("kind") != "mark":
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_OPEN_MARK_INVALID"
                )
            mark_payload = dict(raw)
            mark_payload.pop("kind")
            marks.append(ContinuousPaperTradePathMark.from_dict(mark_payload))
        return header, _merge_marks(marks)

    def checkpoint_open_path(
        self,
        *,
        opening_plan_id: str,
        market: MarketId,
        opened_at_ms: int,
        mark_observations: Sequence[ReplayRecord],
    ) -> int:
        _require_nonempty(opening_plan_id, "opening_plan_id")
        if opened_at_ms < 0:
            raise ValueError("opened_at_ms must be non-negative")
        path = self._open_path(opening_plan_id)
        header, existing_marks = self._load_open(opening_plan_id)
        expected_header = self._open_header(
            opening_plan_id=opening_plan_id,
            market=market.canonical,
            opened_at_ms=opened_at_ms,
        )
        if header is not None and header != expected_header:
            raise ContinuousPaperTradePathError(
                "CONTINUOUS_PAPER_TRADE_PATH_OPEN_IDENTITY_MISMATCH"
            )

        current_marks = _merge_marks(
            tuple(existing_marks)
            + tuple(
                _mark_from_record(
                    record,
                    market=market.canonical,
                    opened_at_ms=opened_at_ms,
                    closed_at_ms=None,
                )
                for record in mark_observations
            )
        )
        existing_by_key = {
            mark.event_key: mark
            for mark in existing_marks
        }
        new_marks = tuple(
            mark
            for mark in current_marks
            if mark.event_key not in existing_by_key
        )
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(
                    (_canonical_json(expected_header) + "\n").encode("utf-8")
                )
                for mark in new_marks:
                    handle.write(
                        (
                            _canonical_json(self._open_mark_payload(mark))
                            + "\n"
                        ).encode("utf-8")
                    )
                handle.flush()
                os.fsync(handle.fileno())
            return len(new_marks)

        if new_marks:
            with path.open("ab") as handle:
                for mark in new_marks:
                    handle.write(
                        (
                            _canonical_json(self._open_mark_payload(mark))
                            + "\n"
                        ).encode("utf-8")
                    )
                handle.flush()
                os.fsync(handle.fileno())
        return len(new_marks)

    def record(self, trade_path: ContinuousPaperTradePath) -> bool:
        path = self._path(trade_path.trade_id)
        encoded = (_canonical_json(trade_path.to_dict()) + "\n").encode("utf-8")
        if path.exists():
            if path.read_bytes() != encoded:
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_CONFLICT"
                )
            return False
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != encoded:
                    raise ContinuousPaperTradePathError(
                        "CONTINUOUS_PAPER_TRADE_PATH_CONFLICT"
                    ) from None
                return False
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def finalize_trade(
        self,
        trade: TradeJournalEntry,
        mark_observations: Sequence[ReplayRecord],
        known_gap_intervals: Sequence[tuple[int, int | None]],
    ) -> bool:
        header, staged_marks = self._load_open(trade.opening_plan_id)
        if header is not None and (
            header.get("market") != trade.market.canonical
            or header.get("opened_at_ms") != trade.opened_at_ms
        ):
            raise ContinuousPaperTradePathError(
                "CONTINUOUS_PAPER_TRADE_PATH_OPEN_TRADE_MISMATCH"
            )
        current_marks = tuple(
            _mark_from_record(
                record,
                market=trade.market.canonical,
                opened_at_ms=trade.opened_at_ms,
                closed_at_ms=trade.closed_at_ms,
            )
            for record in mark_observations
        )
        trade_path = continuous_paper_trade_path(
            trade,
            tuple(staged_marks) + current_marks,
            known_gap_intervals,
        )
        created = self.record(trade_path)
        open_path = self._open_path(trade.opening_plan_id)
        if open_path.exists():
            open_path.unlink()
        return created

    def iter_payloads(self) -> tuple[dict[str, object], ...]:
        payloads: list[dict[str, object]] = []
        for path in sorted(self.records_root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_UNREADABLE"
                ) from exc
            if not isinstance(raw, dict) or not all(
                isinstance(key, str) for key in raw
            ):
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_RECORD_INVALID"
                )
            trade_id = raw.get("trade_id")
            path_id = raw.get("path_id")
            if not isinstance(trade_id, str) or not isinstance(path_id, str):
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_IDENTITY_INVALID"
                )
            if path.name != self._record_name(trade_id, ".json"):
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_FILENAME_MISMATCH"
                )
            identity = dict(raw)
            identity.pop("path_id")
            if _sha256_json(identity) != path_id:
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_ID_MISMATCH"
                )
            canonical = (_canonical_json(raw) + "\n").encode("utf-8")
            if path.read_bytes() != canonical:
                raise ContinuousPaperTradePathError(
                    "CONTINUOUS_PAPER_TRADE_PATH_NON_CANONICAL"
                )
            payloads.append(raw)
        return tuple(
            sorted(
                payloads,
                key=lambda item: (
                    int(item["closed_at_ms"]),
                    str(item["market"]),
                    str(item["trade_id"]),
                ),
            )
        )

    @property
    def record_count(self) -> int:
        return len(self.iter_payloads())

    @property
    def open_path_count(self) -> int:
        return len(tuple(self.open_root.glob("*.jsonl")))

    @property
    def state_digest(self) -> str:
        return _sha256_json(self.iter_payloads())
