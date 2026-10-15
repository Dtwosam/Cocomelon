"""Read-only, non-admitting consistency audit of an original v2 research ZIP.

No archive extraction to user-controlled paths, signed-row truncation, SQL
writes, or promotion/execution. This cannot certify an original venue feed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from scripts.diagnose_v2_source_gap_order import diagnose_source_gap_order

ROOT = "both-side-trend-paired-shadow-v2/"
MAX_STATE_BYTES = 16 * 1024 * 1024
MAX_SQLITE_BYTES = 128 * 1024 * 1024
MAX_WITNESS_BYTES = 512 * 1024 * 1024


class CheckpointArchiveAuditError(ValueError):
    """The supplied archive cannot be safely diagnosed."""


def _canonical(data: object) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _load_member(
    archive: zipfile.ZipFile, name: str, *, limit: int,
) -> bytes:
    if archive.namelist().count(name) != 1:
        raise CheckpointArchiveAuditError("required archive member not unique")
    member = archive.getinfo(name)
    if member.is_dir() or member.file_size > limit:
        raise CheckpointArchiveAuditError("archive member exceeds bounded size")
    with archive.open(member) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit or len(data) != member.file_size:
        raise CheckpointArchiveAuditError("member actual size invalid")
    return data


def _read_sqlite_account_id(path: Path) -> str:
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            rows = connection.execute(
                "SELECT state_id FROM paper_account_state WHERE singleton_id=1"
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise CheckpointArchiveAuditError("archived account store invalid") from exc
    if len(rows) != 1 or not isinstance(rows[0][0], str):
        raise CheckpointArchiveAuditError("archived account state ID invalid")
    return cast(str, rows[0][0])


def audit_original_v2_checkpoint_split(
    archive_path: Path, *, expected_zip_sha256: str,
) -> dict[str, object]:
    """Compare ZIP bytes, original signed witness prefix and BOTH account IDs.

    Expected digest must come from independent GitHub artifact metadata.
    This tool checks equality only; it cannot authenticate who supplied it.
    """
    if (
        len(expected_zip_sha256) != 64
        or any(c not in "0123456789abcdef" for c in expected_zip_sha256)
    ):
        raise CheckpointArchiveAuditError("expected ZIP SHA-256 invalid")
    with archive_path.open("rb") as handle:
        observed_zip_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    if observed_zip_sha256 != expected_zip_sha256:
        raise CheckpointArchiveAuditError("original artifact digest mismatch")

    with zipfile.ZipFile(archive_path) as archive:
        state_bytes = _load_member(
            archive, ROOT + "paired-shadow-state.json", limit=MAX_STATE_BYTES,
        )
        try:
            loaded: object = json.loads(state_bytes)
        except (ValueError, UnicodeError) as exc:
            raise CheckpointArchiveAuditError("signed state JSON invalid") from exc
        if not isinstance(loaded, dict):
            raise CheckpointArchiveAuditError("signed state not an object")
        state = cast(dict[str, object], loaded)
        unsigned = dict(state)
        recorded_state_digest = unsigned.pop("state_digest", None)
        if (
            not isinstance(recorded_state_digest, str)
            or hashlib.sha256(_canonical(unsigned)).hexdigest()
            != recorded_state_digest
        ):
            raise CheckpointArchiveAuditError("signed state self-digest invalid")
        count = state.get("record_count")
        receipt = state.get("v2_source_gap_event_witness")
        if (
            type(count) is not int or count < 0
            or not isinstance(receipt, dict)
            or receipt.get("processed_market_record_count") != count
        ):
            raise CheckpointArchiveAuditError("signed witness count missing")
        prefix_len = receipt.get("witness_byte_count")
        prefix_expected_sha = receipt.get("witness_bytes_sha256")
        prefix_rows = receipt.get("received_gap_record_count")
        prefix_last_digest = receipt.get("latest_gap_record_digest")
        if (
            type(prefix_len) is not int or prefix_len < 0
            or type(prefix_rows) is not int or prefix_rows < 0
            or not isinstance(prefix_expected_sha, str)
            or len(prefix_expected_sha) != 64
            or (prefix_last_digest is not None and not isinstance(prefix_last_digest, str))
        ):
            raise CheckpointArchiveAuditError("signed prefix metadata invalid")

        with tempfile.TemporaryDirectory(prefix="v2-archive-audit-") as temp:
            temp_root = Path(temp)
            witness_path = temp_root / "original-gap-witness.jsonl"
            witness_member = ROOT + "source-gap-record-witness.jsonl"
            if archive.namelist().count(witness_member) != 1:
                raise CheckpointArchiveAuditError("witness member not unique")
            info = archive.getinfo(witness_member)
            if info.file_size > MAX_WITNESS_BYTES:
                raise CheckpointArchiveAuditError("witness exceeds bounded size")
            original_bytes = 0
            prefix_hasher = hashlib.sha256()
            prefix_last_byte: int | None = None
            with archive.open(info) as source, witness_path.open("xb") as target:
                while chunk := source.read(1024 * 1024):
                    original_bytes += len(chunk)
                    if original_bytes > MAX_WITNESS_BYTES:
                        raise CheckpointArchiveAuditError("expanded witness too large")
                    remaining = max(0, prefix_len - (original_bytes - len(chunk)))
                    prefix_chunk = chunk[:remaining]
                    if prefix_chunk:
                        prefix_hasher.update(prefix_chunk)
                        prefix_last_byte = prefix_chunk[-1]
                    target.write(chunk)
            if (
                original_bytes != info.file_size or prefix_len > original_bytes
                or prefix_hasher.hexdigest() != prefix_expected_sha
                or (prefix_len and prefix_last_byte != 10)
            ):
                raise CheckpointArchiveAuditError("signed witness prefix bytes differ")

            local = diagnose_source_gap_order(
                witness_path, signed_processed_records=count,
            )
            prefix_row_count = 0
            last_digest: object = None
            covered = 0
            with witness_path.open("rb") as handle:
                while covered < prefix_len:
                    line = handle.readline()
                    covered += len(line)
                    if not line or covered > prefix_len:
                        raise CheckpointArchiveAuditError("signed prefix not row aligned")
                    row: object = json.loads(line)
                    if not isinstance(row, dict):
                        raise CheckpointArchiveAuditError("signed prefix row invalid")
                    last_digest = row.get("row_digest")
                    prefix_row_count += 1
            if prefix_row_count != prefix_rows or last_digest != prefix_last_digest:
                raise CheckpointArchiveAuditError("signed witness row receipt differs")
            # A digest-only prefix check is insufficient if its internal row
            # chain or source timestamps are invalid; the independent strict
            # read-only diagnostic must show no earlier break.
            if local["status"] == "invalid":
                raise CheckpointArchiveAuditError("original witness chain invalid")

            parity: dict[str, bool] = {}
            for lane in ("baseline", "candidate"):
                stored = state.get(lane)
                if not isinstance(stored, dict) or not isinstance(
                    stored.get("account_state_id"), str
                ):
                    raise CheckpointArchiveAuditError("signed lane account ID invalid")
                sqlite_bytes = _load_member(
                    archive, ROOT + lane + "-execution.sqlite3",
                    limit=MAX_SQLITE_BYTES,
                )
                filename = temp_root / (lane + ".sqlite3")
                filename.write_bytes(sqlite_bytes)
                parity[lane] = (
                    _read_sqlite_account_id(filename) == stored["account_state_id"]
                )

    is_split = (
        local["status"] == "uncheckpointed_witness_tail"
        and not parity["baseline"] and not parity["candidate"]
    )
    return {
        "schema": "original-v2-checkpoint-split-archive-diagnostic-v1",
        "classification": (
            "three_way_checkpoint_split" if is_split
            else "locally_consistent_unverified"
            if local["status"] == "self_consistent_unverified" and all(parity.values())
            else "inconsistent_or_unverified"
        ),
        "original_zip_sha256_verified_against_supplied_digest": True,
        "expected_digest_independently_sourced": False,
        "signed_state_self_digest_valid": True,
        "signed_witness_prefix_bytes_sha256_valid": True,
        "signed_witness_prefix_row_count_and_last_digest_valid": True,
        "witness_diagnostic": local,
        "baseline_sqlite_account_id_matches_signed_state": parity["baseline"],
        "candidate_sqlite_account_id_matches_signed_state": parity["candidate"],
        "original_exchange_feed_authenticated": False,
        "independent_terminal_account_parity_certified": False,
        "research_restore_authorized": False,
        "execution_authority": False,
        "promotion_authority": False,
        "after_cost_profitability_verified": False,
        "source_files_modified": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--expected-zip-sha256", required=True)
    args = parser.parse_args(argv)
    report = audit_original_v2_checkpoint_split(
        args.zip, expected_zip_sha256=args.expected_zip_sha256,
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
