from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator

from cocomelon.domain.journal import canonical_json
from cocomelon.domain.replay import EvidenceClass, ReplayEvidence

MICROSTRUCTURE_KINDS = frozenset({"l2_book", "trade"})


class EvidenceBoundaryError(ValueError):
    pass


def _sort_key(row: ReplayEvidence) -> tuple[int, str, int, int]:
    coordinate = row.coordinate
    return (
        row.receive_time_ms,
        coordinate.relative_path,
        coordinate.segment,
        coordinate.line_number,
    )


def _canonical_row(row: ReplayEvidence) -> str:
    return canonical_json(
        {
            "evidence_class": row.evidence_class.value,
            "receive_time_ms": row.receive_time_ms,
            "exchange_time_ms": row.exchange_time_ms,
            "record_type": row.record_type,
            "source": row.source,
            "relative_path": row.coordinate.relative_path,
            "segment": row.coordinate.segment,
            "line_number": row.coordinate.line_number,
            "market": None if row.market is None else row.market.canonical,
            "event_kind": row.event_kind,
            "event_key": row.event_key,
            "payload_json": row.payload_json,
        }
    )


class ReplayEngine(Iterator[ReplayEvidence]):
    def __init__(
        self,
        evidence_class: EvidenceClass,
        rows: Iterable[ReplayEvidence],
    ) -> None:
        self.evidence_class = evidence_class
        validated = tuple(rows)
        for row in validated:
            if row.evidence_class is not evidence_class:
                raise EvidenceBoundaryError(
                    "row evidence_class does not match replay evidence_class"
                )
            if (
                evidence_class is EvidenceClass.CANDLE_CONTEXT
                and row.event_kind in MICROSTRUCTURE_KINDS
            ):
                raise EvidenceBoundaryError(
                    f"candle/context replay cannot contain {row.event_kind} evidence"
                )
        self._rows = tuple(sorted(validated, key=_sort_key))
        self._index = 0
        self.current_receive_time_ms: int | None = None
        self._hasher = hashlib.sha256()
        self._hasher.update(evidence_class.value.encode("utf-8"))
        self._completion_digest: str | None = None
        if not self._rows:
            self._finalize()

    def __iter__(self) -> ReplayEngine:
        return self

    def __next__(self) -> ReplayEvidence:
        row = self.next_event()
        if row is None:
            raise StopIteration
        return row

    def peek_time(self) -> int | None:
        if self._index >= len(self._rows):
            return None
        return self._rows[self._index].receive_time_ms

    def next_event(self) -> ReplayEvidence | None:
        if self._index >= len(self._rows):
            self._finalize()
            return None
        row = self._rows[self._index]
        self._index += 1
        self.current_receive_time_ms = row.receive_time_ms
        encoded = _canonical_row(row).encode("utf-8")
        self._hasher.update(len(encoded).to_bytes(8, "big"))
        self._hasher.update(encoded)
        if self._index == len(self._rows):
            self._finalize()
        return row

    @property
    def completion_digest(self) -> str | None:
        return self._completion_digest

    def _finalize(self) -> None:
        if self._completion_digest is None:
            self._completion_digest = self._hasher.hexdigest()
