"""Capture the actual v2 paired actor DATA_GAP inputs as signed audit evidence.

This records *received* normalized ReplayRecord gap envelopes, never exchange-
authenticated originals. Source absence remains unverified regardless of
whether the witnessed gap ledger is empty. Only v2 uses this module.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Final

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind

FILE_NAME: Final = "source-gap-record-witness.jsonl"
SCHEMA: Final = 1


class V2SourceGapWitnessError(RuntimeError):
    """Source gap witness is missing, tampered, or not append-only."""


def _json(data: object) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_source_gap_witness(
    path: Path, *, total_processed_records: int,
) -> dict[str, object]:
    """Independent exact-row chain replay, without consulting actor counters."""
    if type(total_processed_records) is not int or total_processed_records < 0:
        raise V2SourceGapWitnessError("processed market record count invalid")
    if not path.is_file():
        raise V2SourceGapWitnessError("original v2 gap record witness missing")
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise V2SourceGapWitnessError("truncated original gap record line")
    previous_digest: str | None = None
    ordinal = 0
    last_available: int | None = None
    count = 0
    for line in data.splitlines():
        try:
            row = json.loads(line)
        except (UnicodeError, ValueError) as exc:
            raise V2SourceGapWitnessError("invalid source gap witness JSON") from exc
        if not isinstance(row, dict):
            raise V2SourceGapWitnessError("source gap witness row is not object")
        record = row.get("record")
        if not isinstance(record, dict):
            raise V2SourceGapWitnessError("source gap record envelope missing")
        if (
            row.get("schema_version") != SCHEMA
            or row.get("previous_digest") != previous_digest
            or record.get("record_kind") != SourceRecordKind.DATA_GAP.value
        ):
            raise V2SourceGapWitnessError("source gap row identity or chain broken")
        number = row.get("record_ordinal")
        at_ms = record.get("available_at_ms")
        if (
            type(number) is not int
            or number <= ordinal
            or number > total_processed_records
            or type(at_ms) is not int or at_ms < 0
            or (last_available is not None and at_ms < last_available)
        ):
            raise V2SourceGapWitnessError("source gap event order invalid")
        required = (
            "source", "schema_version", "payload_json", "market",
            "exchange_time_ms", "event_kind", "event_key",
        )
        if not all(name in record for name in required):
            raise V2SourceGapWitnessError("source gap envelope incomplete")
        try:
            roundtrip = ReplayRecord(
                record_kind=SourceRecordKind.DATA_GAP,
                available_at_ms=at_ms,
                source=record["source"],
                schema_version=record["schema_version"],
                market=record["market"],
                exchange_time_ms=record["exchange_time_ms"],
                event_key=record["event_key"],
                payload_json=record["payload_json"],
                event_kind=record["event_kind"],
            )
        except (ValueError, TypeError) as exc:
            raise V2SourceGapWitnessError("source gap envelope invalid") from exc
        if (
            record["payload_json"] != roundtrip.payload_json
            or type(record["schema_version"]) is not int
            or not isinstance(record["source"], str)
            or not record["source"]
        ):
            raise V2SourceGapWitnessError("source gap record not canonical")
        unsigned = dict(row)
        recorded_digest = unsigned.pop("row_digest", None)
        expected_digest = _hash(_json(unsigned))
        if (
            not isinstance(recorded_digest, str)
            or recorded_digest != expected_digest
        ):
            raise V2SourceGapWitnessError("original gap witness row digest changed")
        ordinal = number
        last_available = at_ms
        previous_digest = expected_digest
        count += 1
    return {
        "schema_version": SCHEMA,
        "received_gap_record_count": count,
        "last_gap_record_ordinal": ordinal if count else None,
        "latest_gap_record_digest": previous_digest,
        "witness_bytes_sha256": _hash(data),
        "witness_byte_count": len(data),
        "processed_market_record_count": total_processed_records,
        "received_normalized_gap_events_only": True,
        "not_a_complete_original_venue_feed": True,
        "original_exchange_gap_provenance_authenticated": False,
        "research_only": True,
        "paper_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


class V2SourceGapWitness:
    """Write-once initial file; append exactly one captured row per gap input."""

    def __init__(self, root: Path, *, restoring: bool) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / FILE_NAME
        if restoring:
            if not self.path.is_file():
                raise V2SourceGapWitnessError(
                    "restored v2 accounts lack original gap event witness"
                )
        else:
            with self.path.open("x", encoding="utf-8") as file:
                file.flush()
                os.fsync(file.fileno())
        self._previous_digest: str | None = None
        self._last_ordinal = 0
        self._count = 0

    def restore(self, *, receipt: object, total_processed_records: int) -> None:
        observed = read_source_gap_witness(
            self.path, total_processed_records=total_processed_records,
        )
        if not isinstance(receipt, dict) or receipt != observed:
            raise V2SourceGapWitnessError(
                "restored source-gap witness differs from signed account checkpoint"
            )
        self._count = int(observed["received_gap_record_count"])
        self._last_ordinal = int(observed["last_gap_record_ordinal"] or 0)
        digest = observed["latest_gap_record_digest"]
        self._previous_digest = digest if isinstance(digest, str) else None

    def append(self, record: ReplayRecord, *, ordinal: int) -> None:
        if record.record_kind != SourceRecordKind.DATA_GAP:
            return
        if type(ordinal) is not int or ordinal <= self._last_ordinal:
            raise V2SourceGapWitnessError(
                "v2 source gap witness not monotonically appended"
            )
        payload: dict[str, object] = {
            "schema_version": SCHEMA,
            "record_ordinal": ordinal,
            "record": {
                "record_kind": record.record_kind.value,
                "available_at_ms": record.available_at_ms,
                "source": record.source,
                "schema_version": record.schema_version,
                "market": record.market,
                "exchange_time_ms": record.exchange_time_ms,
                "event_key": record.event_key,
                "payload_json": record.payload_json,
                "event_kind": record.event_kind,
            },
            "previous_digest": self._previous_digest,
        }
        digest = _hash(_json(payload))
        payload["row_digest"] = digest
        with self.path.open("ab") as file:
            file.write(_json(payload) + b"\n")
            file.flush()
            os.fsync(file.fileno())
        self._last_ordinal = ordinal
        self._previous_digest = digest
        self._count += 1

    def signed_receipt(self, *, total_processed_records: int) -> dict[str, object]:
        observed = read_source_gap_witness(
            self.path, total_processed_records=total_processed_records,
        )
        if (
            observed["received_gap_record_count"] != self._count
            or observed["latest_gap_record_digest"] != self._previous_digest
        ):
            raise V2SourceGapWitnessError("source gap file changed outside actor")
        return observed
