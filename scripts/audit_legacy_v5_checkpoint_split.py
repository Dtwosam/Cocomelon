"""Read-only authenticated legacy v5 checkpoint vs execution-store forensics.

A later SQLite account state is not the account signed at an earlier ledger
checkpoint, even if its marked net PnL appears favorable. NEVER repair data,
read after signed end as if it were signed, or grant execution/promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Final, Sequence

from cocomelon.research.loss_context_paired_shadow_review import (
    review_ledger_receipt,
)
from scripts.audit_both_side_trend_paired_handoff import (
    TrendPairHandoffAuditError,
    _json_file,
    _mapping,
    _signed_digest,
    _source_class,
)

ANCHOR_RUN_ID: Final = 38281228549
ANCHOR_ATTEMPT: Final = 1
ROOT: Final = "loss-context-paired-portfolio-shadow-scoped-v5"
ARTIFACT_PREFIX: Final = "continuous-paper-loss-context-paired-shadow-"
MAX_DB_BYTES: Final = 600_000_000
MAX_JSON_BYTES: Final = 55_000_000


def _unique_member(
    archive: zipfile.ZipFile, path: str, max_bytes: int,
) -> zipfile.ZipInfo:
    matches = [
        item for item in archive.infolist()
        if item.filename in {path, f"continuous-paper-state/{path}"}
    ]
    if (
        len(matches) != 1 or matches[0].is_dir()
        or not (0 < matches[0].file_size <= max_bytes)
    ):
        raise TrendPairHandoffAuditError(
            f"missing, ambiguous, or oversized legacy v5 member {path}"
        )
    return matches[0]


def _checked_artifact_sha(
    artifacts: dict[str, object], path: Path,
    *, run_id: int, attempt: int,
) -> str:
    expected = f"{ARTIFACT_PREFIX}{run_id}-{attempt}"
    items = artifacts.get("artifacts")
    if not isinstance(items, list):
        raise TrendPairHandoffAuditError("source artifact list invalid")
    matches = [
        _mapping(item, "legacy v5 artifact")
        for item in items
        if isinstance(item, dict) and item.get("name") == expected
    ]
    if len(matches) != 1 or matches[0].get("expired") is not False:
        raise TrendPairHandoffAuditError(
            "exact unexpired legacy v5 artifact absent or ambiguous"
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    value = digest.hexdigest()
    if matches[0].get("digest") != f"sha256:{value}":
        raise TrendPairHandoffAuditError("legacy v5 artifact SHA256 mismatch")
    return value


def _read_signed_v5(
    archive: zipfile.ZipFile, root: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    state = _mapping(
        json.loads(archive.read(_unique_member(
            archive, f"{ROOT}/paired-shadow-state.json", MAX_JSON_BYTES,
        ))),
        "legacy v5 signed state",
    )
    unsigned = dict(state)
    digest = unsigned.pop("state_digest", None)
    if digest != _signed_digest(unsigned):
        raise TrendPairHandoffAuditError("legacy v5 checkpoint digest invalid")
    if (
        state.get("schema_version") != 2
        or state.get("paper_only") is not True
        or state.get("research_only") is not True
        or state.get("execution_authority") is not False
        or state.get("promotion_authority") is not False
    ):
        raise TrendPairHandoffAuditError("legacy v5 state authority invalid")
    ledger_path = root / "review-ledger.jsonl"
    ledger_path.write_bytes(
        archive.read(_unique_member(
            archive, f"{ROOT}/review-ledger.jsonl", MAX_JSON_BYTES,
        ))
    )
    candidate_id = state.get("portfolio_shadow_candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise TrendPairHandoffAuditError("legacy v5 candidate ID absent")
    receipt = review_ledger_receipt(ledger_path, candidate_id=candidate_id)
    if (
        receipt.get("row_count") != state.get("review_ledger_row_count")
        or receipt.get("latest_row_digest")
        != state.get("review_ledger_latest_row_digest")
    ):
        raise TrendPairHandoffAuditError("legacy v5 signed ledger state mismatch")
    lines = ledger_path.read_bytes().splitlines()
    if not lines:
        raise TrendPairHandoffAuditError("legacy v5 signed review ledger empty")
    last = _mapping(json.loads(lines[-1]), "legacy v5 last signed review")
    if (
        last.get("portfolio_shadow_candidate_id") != candidate_id
        or last.get("record_count") != state.get("record_count")
    ):
        raise TrendPairHandoffAuditError("legacy v5 signed ledger lineage mismatch")
    summary = _mapping(
        json.loads(archive.read(_unique_member(
            archive, "loss-context-paired-portfolio-shadow-summary.json",
            MAX_JSON_BYTES,
        ))),
        "legacy v5 runtime summary",
    )
    return state, last, summary


def _archive_db_state(
    archive: zipfile.ZipFile, root: Path, lane: str,
) -> dict[str, object]:
    info = _unique_member(
        archive, f"{ROOT}/{lane}-execution.sqlite3", MAX_DB_BYTES,
    )
    filename = root / f"{lane}-execution.sqlite3"
    count = 0
    with archive.open(info) as source, filename.open("xb") as output:
        while block := source.read(8 * 1024 * 1024):
            count += len(block)
            if count > MAX_DB_BYTES:
                raise TrendPairHandoffAuditError("legacy v5 SQLite oversized")
            output.write(block)
    with sqlite3.connect(f"{filename.as_uri()}?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        if conn.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise TrendPairHandoffAuditError("legacy v5 SQLite integrity failed")
        row = conn.execute(
            "SELECT state_id, payload_json FROM paper_account_state "
            "WHERE singleton_id=1"
        ).fetchone()
        if row is None:
            raise TrendPairHandoffAuditError("legacy v5 SQLite account absent")
        payload = _mapping(json.loads(row[1]), "legacy v5 sqlite account")
        return {"state_id": row[0], "account": payload}


def _diagnose_lane(
    state: dict[str, object],
    last: dict[str, object],
    sql: dict[str, object],
    lane: str,
) -> dict[str, object]:
    signed = _mapping(state.get(lane), f"{lane} signed state")
    ledger = _mapping(last.get(lane), f"{lane} signed ledger")
    account = _mapping(sql.get("account"), f"{lane} SQLite account")
    checkpoint_ms = state.get("last_record_available_at_ms")
    account_ms = account.get("updated_at_ms")
    if (
        type(checkpoint_ms) is not int or checkpoint_ms < 0
        or type(account_ms) is not int or account_ms < 0
        or not isinstance(signed.get("account_state_id"), str)
        or not isinstance(sql.get("state_id"), str)
    ):
        raise TrendPairHandoffAuditError(
            f"{lane} legacy v5 account chronology or IDs invalid"
        )
    from decimal import Decimal
    value = Decimal(str(account.get("equity")))
    start = Decimal(str(account.get("starting_cash")))
    if not value.is_finite() or not start.is_finite() or start <= 0:
        raise TrendPairHandoffAuditError("legacy v5 SQLite cash invalid")
    diverged = signed["account_state_id"] != sql["state_id"]
    timestamp_delta = account_ms - checkpoint_ms
    # Never substitute SQLite future values for frozen signed review rows.
    return {
        "signed_checkpoint_account_id": signed["account_state_id"],
        "execution_database_account_id": sql["state_id"],
        "durable_state_id_matches": not diverged,
        "signed_last_record_ms": checkpoint_ms,
        "execution_database_last_account_ms": account_ms,
        "execution_database_minus_signed_record_ms": timestamp_delta,
        "signed_total_account_pnl": ledger.get("total_account_pnl"),
        "signed_realized_net_pnl": ledger.get("realized_net_pnl"),
        "signed_closed_trade_count": ledger.get("closed_trade_count"),
        "sqlite_account_pnl_not_signed": str(value - start),
        "sqlite_is_after_signed_record": timestamp_delta > 0,
        "source_market_data_independently_authenticated": False,
        "signed_account_economics_eligible_for_promotion": False,
    }


def audit_legacy_v5_split(
    *, run: dict[str, object], jobs: dict[str, object],
    artifacts: dict[str, object], archive_path: Path,
    repository: str, run_id: int, attempt: int,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "unverified",
        "reasons": [],
        "source_run_id": run_id,
        "source_attempt": attempt,
        "source_class": None,
        "archive_sha256": None,
        "signed_checkpoint_count": None,
        "lanes": None,
        "research_only": True,
        "paper_only": True,
        "promotion_authority": False,
        "execution_authority": False,
        "forward_profitability_verified": False,
    }
    try:
        if run_id != ANCHOR_RUN_ID or attempt != ANCHOR_ATTEMPT:
            raise TrendPairHandoffAuditError("legacy v5 source outside frozen anchor")
        source_class = _source_class(
            run=run, jobs=jobs, repository=repository,
            run_id=run_id, attempt=attempt,
        )
        if source_class != "completed_expected_upgrade_handoff_worker":
            raise TrendPairHandoffAuditError(
                "original upgrade source not independently authenticated"
            )
        result["source_class"] = source_class
        result["archive_sha256"] = _checked_artifact_sha(
            artifacts, archive_path, run_id=run_id, attempt=attempt,
        )
        with tempfile.TemporaryDirectory() as dr:
            root = Path(dr)
            with zipfile.ZipFile(archive_path) as archive:
                state, last, summary = _read_signed_v5(archive, root)
                lanes = {
                    lane: _diagnose_lane(
                        state, last, _archive_db_state(archive, root, lane),
                        lane,
                    )
                    for lane in ("baseline", "candidate")
                }
            result["lanes"] = lanes
            result["signed_checkpoint_count"] = state.get(
                "review_ledger_row_count"
            )
            result["signed_data_gap_open_count"] = last.get(
                "data_gap_open_count"
            )
            result["checkpoint_failure_reason"] = summary.get(
                "checkpoint_error"
            )
            if any(
                not info["durable_state_id_matches"]
                for info in lanes.values()
            ):
                result["status"] = "authenticated_legacy_v5_checkpoint_db_split"
                result["reasons"] = [
                    "execution_database_state_id_differs_from_signed_checkpoint",
                    "later_sqlite_account_is_not_signed_forward_profitability",
                ]
            else:
                result["status"] = "legacy_v5_terminal_ids_match_not_profit_certified"
                result["reasons"] = [
                    "legacy_v5_account_ids_alone_do_not_prove_after_cost_edge",
                ]
    except (
        OSError, ValueError, RuntimeError, TypeError, KeyError,
        sqlite3.DatabaseError, zipfile.BadZipFile,
        UnicodeDecodeError, ArithmeticError,
    ) as exc:
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = audit_legacy_v5_split(
            run=_json_file(args.run), jobs=_json_file(args.jobs),
            artifacts=_json_file(args.artifacts),
            archive_path=args.archive,
            repository=args.repository,
            run_id=args.run_id, attempt=args.attempt,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        payload = {
            "status": "unverified", "reasons": [str(exc)],
            "research_only": True, "paper_only": True,
            "promotion_authority": False, "execution_authority": False,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(
        f".{args.output.name}.{os.getpid()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
            + "\n", encoding="utf-8",
        )
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
