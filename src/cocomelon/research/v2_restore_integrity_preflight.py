"""Read-only preflight before opening an existing frozen v2 research actor.

Check original signed witness bytes and both SQLite account state IDs against
the stored signed checkpoint *before* any paired paper-execution adapters are
constructed. This cannot authenticate a complete venue feed or authorize
profit, trading, source promotion, account rewind or reconstruction.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    FILE_NAME,
)


class V2RestorePreflightError(ValueError):
    """Frozen v2 actor cannot read its original checkpoint as a unit."""


def _signed_nonnegative(raw: object) -> int:
    if type(raw) is not int or raw < 0:
        raise V2RestorePreflightError("v2 signed witness count invalid")
    return raw


def _sqlite_account_id(path: Path) -> str:
    if not path.is_file():
        raise V2RestorePreflightError("v2 original account store missing")
    try:
        # Immutable+RO cannot create SQLite WAL/SHM/journal files or alter
        # original historical bytes. Uncheckpointed WAL is NOT accepted.
        with sqlite3.connect(
            path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1",
            uri=True,
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                "SELECT state_id FROM paper_account_state WHERE singleton_id=1"
            ).fetchall()
    except (sqlite3.DatabaseError, OSError) as exc:
        raise V2RestorePreflightError(
            "v2 original account database could not be verified read-only"
        ) from exc
    if (
        len(rows) != 1 or not isinstance(rows[0][0], str)
        or not rows[0][0]
    ):
        raise V2RestorePreflightError("v2 original account state ID invalid")
    return str(rows[0][0])


def verify_v2_restore_preflight(root: Path, signed: dict[str, object]) -> None:
    """Require exact signed source bytes and both persistent account IDs.

    The caller MUST first verify the signed JSON state digest, frozen
    candidate/config identity and genesis. The original paired actor will
    still independently validate every original gap record and review row.
    """
    count = _signed_nonnegative(signed.get("record_count"))
    receipt = signed.get("v2_source_gap_event_witness")
    if not isinstance(receipt, dict):
        raise V2RestorePreflightError("v2 signed original gap receipt missing")
    expected_count = _signed_nonnegative(receipt.get("processed_market_record_count"))
    expected_rows = _signed_nonnegative(receipt.get("received_gap_record_count"))
    expected_bytes = _signed_nonnegative(receipt.get("witness_byte_count"))
    digest = receipt.get("witness_bytes_sha256")
    if (
        expected_count != count
        or not isinstance(digest, str) or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise V2RestorePreflightError("v2 signed gap receipt not coherent")

    witness = root / FILE_NAME
    if not witness.is_file():
        raise V2RestorePreflightError("v2 original received gap witness missing")
    sha = hashlib.sha256()
    rows = 0
    size = 0
    last_byte: int | None = None
    # Streaming audit avoids copying a potentially large DATA_GAP ledger into
    # memory merely to reject a torn checkpoint at worker startup.
    with witness.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            sha.update(block)
            size += len(block)
            rows += block.count(b"\n")
            last_byte = block[-1]
    if (
        size != expected_bytes or rows != expected_rows
        or sha.hexdigest() != digest
        or (size > 0 and last_byte != 10)
    ):
        raise V2RestorePreflightError(
            "v2 original received gap witness differs from signed checkpoint"
        )
    # Preserve the existing full row-by-row SHA chain/audit within the actor;
    # matching signed-file digest alone is not venue completeness evidence.
    for lane in ("baseline", "candidate"):
        details = signed.get(lane)
        if not isinstance(details, dict):
            raise V2RestorePreflightError("v2 signed account lane missing")
        expected_id = details.get("account_state_id")
        if not isinstance(expected_id, str) or not expected_id:
            raise V2RestorePreflightError("v2 signed account identity invalid")
        if _sqlite_account_id(root / f"{lane}-execution.sqlite3") != expected_id:
            raise V2RestorePreflightError(
                "v2 original account SQLite differs from signed checkpoint"
            )
