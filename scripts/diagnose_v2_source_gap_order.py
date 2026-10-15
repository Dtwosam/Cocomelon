"""Read-only forensic localization of a failed v2 DATA_GAP source witness.

A self-consistent JSONL digest chain is NOT a signed paper checkpoint, a
complete exchange feed, or profitable evidence. No source files are modified.
This offline diagnostic deliberately does not run inside the paper record pump.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from cocomelon.domain.replay import ReplayRecord, SourceRecordKind
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    SCHEMA,
)


def _canonical(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def diagnose_source_gap_order(
    path: Path, *, signed_processed_records: int,
) -> dict[str, object]:
    """Locate the first failed invariant without rewriting or truncating bytes.

    The count is operator-supplied; independently authenticate the archived
    signed checkpoint and source-artifact digest before using it as evidence.
    Read the entire file even on error to hash its original bytes; never trust
    source fields from a row until its local SHA chain has been checked.
    """
    if type(signed_processed_records) is not int or signed_processed_records < 0:
        raise ValueError("signed_processed_records must be nonnegative integer")
    result: dict[str, object] = {
        "schema": "v2-received-gap-order-forensics-v1",
        "status": "unverified",
        "reason": "not_checked",
        "input_signed_processed_records": signed_processed_records,
        "signed_count_independently_authenticated": False,
        "original_exchange_feed_complete": False,
        "signed_checkpoint_accepted": False,
        "profitability_verified": False,
        "promotion_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "source_file_modified": False,
        "first_failed_row_number": None,
        "previous_record_ordinal": None,
        "observed_record_ordinal": None,
        "previous_available_at_ms": None,
        "observed_available_at_ms": None,
        "verified_chain_rows_before_failure": 0,
        "original_file_sha256": None,
        "original_file_bytes": None,
    }
    if not path.is_file():
        result.update(status="invalid", reason="witness_file_missing")
        return result
    digest = hashlib.sha256()
    total_bytes = 0
    previous_digest: str | None = None
    previous_ordinal = 0
    previous_time: int | None = None
    first_failure: tuple[str, int, int | None, int | None] | None = None
    first_excess: tuple[int, int, int | None] | None = None
    accepted = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            digest.update(line)
            total_bytes += len(line)
            if first_failure is not None:
                continue

            def fail(reason: str, ordinal: int | None = None,
                     at_ms: int | None = None) -> None:
                nonlocal first_failure
                first_failure = (reason, line_number, ordinal, at_ms)

            if not line.endswith(b"\n"):
                fail("truncated_row")
                continue
            try:
                parsed: object = json.loads(line)
            except (ValueError, UnicodeError):
                fail("invalid_json")
                continue
            if not isinstance(parsed, dict):
                fail("row_not_object")
                continue
            row = cast(dict[str, object], parsed)
            unsigned = dict(row)
            recorded_digest = unsigned.pop("row_digest", None)
            try:
                expected_digest = hashlib.sha256(_canonical(unsigned)).hexdigest()
            except (ValueError, TypeError):
                fail("noncanonical_row")
                continue
            if type(recorded_digest) is not str or recorded_digest != expected_digest:
                fail("row_digest_mismatch")
                continue
            if row.get("previous_digest") != previous_digest:
                fail("previous_digest_mismatch")
                continue
            record = row.get("record")
            if (
                type(row.get("schema_version")) is not int
                or row["schema_version"] != SCHEMA
                or not isinstance(record, dict)
                or record.get("record_kind") != SourceRecordKind.DATA_GAP.value
            ):
                fail("record_identity_invalid")
                continue
            number = row.get("record_ordinal")
            at_ms = record.get("available_at_ms")
            if type(number) is not int or number <= previous_ordinal:
                fail("ordinal_not_strictly_increasing")
                continue
            if type(at_ms) is not int or at_ms < 0:
                fail("invalid_received_timestamp", number)
                continue
            if previous_time is not None and at_ms < previous_time:
                fail("received_timestamp_regression", number, at_ms)
                continue
            required = (
                "source", "schema_version", "payload_json", "market",
                "exchange_time_ms", "event_kind", "event_key",
            )
            if not all(key in record for key in required):
                fail("incomplete_gap_envelope", number, at_ms)
                continue
            try:
                original = ReplayRecord(
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
            except (TypeError, ValueError):
                fail("invalid_gap_envelope", number, at_ms)
                continue
            if (
                record["payload_json"] != original.payload_json
                or type(record["schema_version"]) is not int
                or not isinstance(record["source"], str)
                or not record["source"]
            ):
                fail("noncanonical_gap_envelope", number, at_ms)
                continue
            if number > signed_processed_records and first_excess is None:
                first_excess = (line_number, number, at_ms)
            previous_digest = expected_digest
            previous_ordinal = number
            previous_time = at_ms
            accepted += 1

    result["original_file_sha256"] = digest.hexdigest()
    result["original_file_bytes"] = total_bytes
    result["verified_chain_rows_before_failure"] = accepted
    if first_failure is not None:
        reason, row_number, number, at_ms = first_failure
        result.update(
            status="invalid",
            reason=reason,
            first_failed_row_number=row_number,
            previous_record_ordinal=previous_ordinal or None,
            observed_record_ordinal=number,
            previous_available_at_ms=previous_time,
            observed_available_at_ms=at_ms,
        )
    elif first_excess is not None:
        row_number, number, at_ms = first_excess
        result.update(
            status="uncheckpointed_witness_tail",
            reason="ordinal_exceeds_signed_processed_count",
            first_failed_row_number=row_number,
            previous_record_ordinal=None,
            observed_record_ordinal=number,
            observed_available_at_ms=at_ms,
        )
    else:
        result.update(
            status="self_consistent_unverified",
            reason="no_local_gap_order_violation",
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--witness", required=True, type=Path)
    parser.add_argument("--signed-processed-records", required=True, type=int)
    args = parser.parse_args(argv)
    diagnosis = diagnose_source_gap_order(
        args.witness, signed_processed_records=args.signed_processed_records,
    )
    print(json.dumps(diagnosis, sort_keys=True, separators=(",", ":")))
    # Diagnostics must not make an unverified source look green to CI callers.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
