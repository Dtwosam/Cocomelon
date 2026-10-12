"""Research-only independent append-lineage check across paper worker ZIPs.

A signed hash-chain in a *single* ZIP cannot prove that the next paper worker
kept the same historical prefix. Compare actual byte-identical ledger rows
against an independently authenticated original post-embargo archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from scripts.audit_both_side_trend_paired_handoff import (
    TrendPairHandoffAuditError,
    _json_file,
    _mapping,
    _member,
    audit_trend_handoff,
)

ORIGINAL_ANCHOR_RUN_ID: Final = 38281228549
ORIGINAL_ANCHOR_ATTEMPT: Final = 1
LEDGER_MEMBER: Final = "both-side-trend-paired-shadow-v1/review-ledger.jsonl"
ACCEPTED_CURRENT_STATES: Final = frozenset({
    "archive_checkpoint_lineage_verified",
    "provisional_archive_checkpoint_lineage_verified",
})


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _ledger_rows(path: Path) -> tuple[bytes, ...]:
    with zipfile.ZipFile(path) as archive:
        raw = _member(archive, LEDGER_MEMBER)
    if not raw or not raw.endswith(b"\n"):
        raise TrendPairHandoffAuditError(
            "archived paired ledger missing or not newline terminated"
        )
    rows = tuple(raw.splitlines(keepends=True))
    for index, line in enumerate(rows):
        if not line.endswith(b"\n") or not line.strip():
            raise TrendPairHandoffAuditError(
                f"invalid archived paired ledger record {index}"
            )
        _mapping(json.loads(line), f"ledger row {index}")
    return rows


def _compare_rows(
    original: tuple[bytes, ...], successor: tuple[bytes, ...],
) -> dict[str, object]:
    if len(successor) < len(original):
        raise TrendPairHandoffAuditError(
            "later worker silently truncated archived review ledger history"
        )
    for index, prior_row in enumerate(original):
        if successor[index] != prior_row:
            raise TrendPairHandoffAuditError(
                f"later worker rewrote anchored review row {index}"
            )
    previous = _mapping(json.loads(original[-1]), "anchor last row")
    current = _mapping(json.loads(successor[-1]), "successor last row")
    if len(successor) > len(original):
        first_new = _mapping(json.loads(successor[len(original)]), "first new row")
        if first_new.get("previous_row_digest") != previous.get("row_digest"):
            raise TrendPairHandoffAuditError(
                "successor first appended review row is not linked to anchor"
            )
        for field in ("end_ms", "record_count"):
            if (
                type(previous.get(field)) is not int
                or type(current.get(field)) is not int
                or current[field] <= previous[field]
            ):
                raise TrendPairHandoffAuditError(
                    f"successor {field} did not advance across worker handoff"
                )
    return {
        "anchored_prefix_row_count": len(original),
        "successor_row_count": len(successor),
        "new_signed_checkpoint_count": len(successor) - len(original),
        "anchored_last_row_digest": previous.get("row_digest"),
        "successor_last_row_digest": current.get("row_digest"),
        "anchored_end_ms": previous.get("end_ms"),
        "successor_end_ms": current.get("end_ms"),
        "anchored_record_count": previous.get("record_count"),
        "successor_record_count": current.get("record_count"),
    }


def audit_original_trend_handoff_continuity(
    *,
    repository: str,
    current_run_id: int,
    current_attempt: int,
    current_receipt: dict[str, object],
    current_archive: Path,
    anchor_run: dict[str, object] | None,
    anchor_jobs: dict[str, object] | None,
    anchor_artifacts: dict[str, object] | None,
    anchor_archive: Path | None,
) -> dict[str, object]:
    """No promotion claims, including when every anchored byte is identical."""
    result: dict[str, object] = {
        "status": "unverified",
        "reasons": [],
        "research_only": True,
        "paper_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "original_anchor_run_id": ORIGINAL_ANCHOR_RUN_ID,
        "original_anchor_attempt": ORIGINAL_ANCHOR_ATTEMPT,
        "current_run_id": current_run_id,
        "current_attempt": current_attempt,
        "current_source_validated": False,
        "original_archive_independently_authenticated": False,
        "original_anchor_prefix_preserved": False,
        "forward_worker_append_verified": False,
        "source_worker_completion_not_inferred": True,
    }
    try:
        if current_run_id < ORIGINAL_ANCHOR_RUN_ID or current_attempt < 1:
            raise TrendPairHandoffAuditError(
                "invalid or pre-anchor successor run identity"
            )
        if (
            current_receipt.get("source_run_id") != current_run_id
            or current_receipt.get("source_run_attempt") != current_attempt
            or current_receipt.get("status") not in ACCEPTED_CURRENT_STATES
            or current_receipt.get("archived_execution_economics_reconciled")
            is not True
            or current_receipt.get("promotion_authority") is not False
            or current_receipt.get("execution_authority") is not False
            or current_receipt.get("archive_sha256")
            != _sha256_file(current_archive)
        ):
            raise TrendPairHandoffAuditError(
                "current original worker receipt/ZIP not independently verified"
            )
        result["current_source_validated"] = True
        # The first original source cannot claim *cross-worker* continuity.
        if (
            current_run_id == ORIGINAL_ANCHOR_RUN_ID
            and current_attempt == ORIGINAL_ANCHOR_ATTEMPT
        ):
            result["status"] = "original_anchor_only"
            result["reasons"] = ["no_successor_worker_to_compare"]
            return result
        if (
            anchor_run is None
            or anchor_jobs is None
            or anchor_artifacts is None
            or anchor_archive is None
        ):
            raise TrendPairHandoffAuditError(
                "immutable original postboundary anchor source absent"
            )
        anchor_receipt = audit_trend_handoff(
            run=anchor_run,
            jobs=anchor_jobs,
            artifacts=anchor_artifacts,
            archive=anchor_archive,
            repository=repository,
            source_run_id=ORIGINAL_ANCHOR_RUN_ID,
            source_attempt=ORIGINAL_ANCHOR_ATTEMPT,
        )
        if (
            anchor_receipt.get("status")
            != "archive_checkpoint_lineage_verified"
            or anchor_receipt.get("source_class")
            != "completed_expected_upgrade_handoff_worker"
            or anchor_receipt.get("expected_upgrade_handoff_proven") is not True
            or anchor_receipt.get("archived_execution_economics_reconciled")
            is not True
            or anchor_receipt.get("promotion_authority") is not False
            or anchor_receipt.get("execution_authority") is not False
        ):
            raise TrendPairHandoffAuditError(
                "original postboundary anchor failed independent authentication"
            )
        result["original_archive_independently_authenticated"] = True
        comparison = _compare_rows(
            _ledger_rows(anchor_archive), _ledger_rows(current_archive),
        )
        result.update(comparison)
        result["original_anchor_prefix_preserved"] = True
        if comparison["new_signed_checkpoint_count"] == 0:
            result["status"] = "no_new_signed_checkpoint"
            result["reasons"] = ["successor_has_not_appended_a_checkpoint"]
        else:
            result["status"] = "original_anchor_forward_append_verified"
            result["forward_worker_append_verified"] = True
    except (
        OSError, ValueError, RuntimeError, TypeError, KeyError,
        zipfile.BadZipFile, UnicodeDecodeError,
    ) as exc:
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-attempt", type=int, required=True)
    parser.add_argument("--current-receipt", type=Path, required=True)
    parser.add_argument("--current-archive", type=Path, required=True)
    parser.add_argument("--anchor-run", type=Path)
    parser.add_argument("--anchor-jobs", type=Path)
    parser.add_argument("--anchor-artifacts", type=Path)
    parser.add_argument("--anchor-archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = audit_original_trend_handoff_continuity(
            repository=args.repository,
            current_run_id=args.source_run_id,
            current_attempt=args.source_attempt,
            current_receipt=_json_file(args.current_receipt),
            current_archive=args.current_archive,
            anchor_run=_json_file(args.anchor_run) if args.anchor_run else None,
            anchor_jobs=_json_file(args.anchor_jobs) if args.anchor_jobs else None,
            anchor_artifacts=(
                _json_file(args.anchor_artifacts)
                if args.anchor_artifacts else None
            ),
            anchor_archive=args.anchor_archive,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        receipt = {
            "status": "unverified",
            "reasons": [f"{type(exc).__name__}: {exc}"],
            "research_only": True,
            "paper_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "original_anchor_prefix_preserved": False,
            "forward_worker_append_verified": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, args.output)
    finally:
        tmp.unlink(missing_ok=True)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
