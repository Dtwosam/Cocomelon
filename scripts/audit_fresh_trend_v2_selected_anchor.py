"""Independent selected-anchor v2 worker ledger extension.

A selected archive anchor is NOT proof of the first genuine v2 worker.
No SQLite state or signed ledger can be rewritten, recovered, or promoted.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    FILE_NAME as V2_GAP_WITNESS_FILE,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_gap_witness import (
    read_source_gap_witness,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_genesis import (
    GENESIS_FILE_V2,
    verify_v2_genesis,
)
from scripts.audit_both_side_trend_ledger_anchor import (
    _archived_gap_scopes,
    _compare_gap_scopes,
    _compare_rows,
    _ledger_rows,
    _sha256_file,
)
from scripts.audit_both_side_trend_paired_handoff import (
    TrendPairHandoffAuditError,
    _json_file,
    _mapping,
    _member,
    _write_json_atomic,
    audit_trend_handoff,
)

V2_LEDGER_MEMBER = "both-side-trend-paired-shadow-v2/review-ledger.jsonl"
V2_STATE_MEMBER = "both-side-trend-paired-shadow-v2/paired-shadow-state.json"
V2_GAP_WITNESS_MEMBER = (
    "both-side-trend-paired-shadow-v2/" + V2_GAP_WITNESS_FILE
)
ACCEPTED_SOURCE = "archive_checkpoint_lineage_verified"


def _strict_source(
    *,
    run: dict[str, object], jobs: dict[str, object],
    artifacts: dict[str, object], archive: Path,
    repository: str, run_id: int, attempt: int,
) -> dict[str, object]:
    receipt = audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts, archive=archive,
        repository=repository, source_run_id=run_id,
        source_attempt=attempt, campaign="v2",
    )
    if (
        receipt.get("status") != ACCEPTED_SOURCE
        or receipt.get("source_run_id") != run_id
        or receipt.get("source_run_attempt") != attempt
        or receipt.get("source_worker_completed") is not True
        or receipt.get("source_class") not in (
            "completed_successful_worker",
            "completed_expected_upgrade_handoff_worker",
        )
        or receipt.get("archived_execution_economics_reconciled") is not True
        or receipt.get("source_v2_terminal_receipt_verified") is not True
        or receipt.get("v2_actor_received_gap_record_chain_verified") is not True
        or receipt.get("archive_sha256") != _sha256_file(archive)
        or receipt.get("promotion_authority") is not False
        or receipt.get("execution_authority") is not False
    ):
        raise TrendPairHandoffAuditError(
            "v2 selected source was not independently account-authenticated"
        )
    return receipt


def _compare_received_gap_witness_prefix(
    *, anchor_archive: Path, current_archive: Path,
    anchor_record_count: int, successor_record_count: int,
) -> dict[str, object]:
    """Authenticate original actor-received gap history across workers.

    Per-source audits prove that each received gap file matches its OWN signed
    checkpoint, but do not prove that a successor preserved an earlier
    worker's bytes. Require exact prefix, including previously closed gaps,
    even if both later signed account/gap-summary histories seem healthy.
    These are *normalized received events*, not complete original venue data.
    """
    with zipfile.ZipFile(anchor_archive) as prior, zipfile.ZipFile(
        current_archive,
    ) as later:
        before = _member(prior, V2_GAP_WITNESS_MEMBER)
        after = _member(later, V2_GAP_WITNESS_MEMBER)
        before_state = _mapping(
            json.loads(_member(prior, V2_STATE_MEMBER)),
            "originating v2 signed market-gap witness state",
        )
        after_state = _mapping(
            json.loads(_member(later, V2_STATE_MEMBER)),
            "successor v2 signed market-gap witness state",
        )
    if not after.startswith(before):
        raise TrendPairHandoffAuditError(
            "successor rewrote or discarded original actor-received DATA_GAP history"
        )
    with tempfile.TemporaryDirectory() as directory:
        old_path = Path(directory) / "originating-gap-records.jsonl"
        new_path = Path(directory) / "successor-gap-records.jsonl"
        old_path.write_bytes(before)
        new_path.write_bytes(after)
        anchored = read_source_gap_witness(
            old_path, total_processed_records=anchor_record_count,
        )
        successor = read_source_gap_witness(
            new_path, total_processed_records=successor_record_count,
        )
    if (
        before_state.get("record_count") != anchor_record_count
        or after_state.get("record_count") != successor_record_count
        or before_state.get("v2_source_gap_event_witness") != anchored
        or after_state.get("v2_source_gap_event_witness") != successor
    ):
        raise TrendPairHandoffAuditError(
            "archived DATA_GAP record file does not match its signed worker count"
        )
    # An event newly seen after the selected genesis worker must not be
    # retroactively placed at an earlier processed-market record ordinal.
    appended = after[len(before):]
    if appended:
        first = _mapping(
            json.loads(appended.splitlines()[0]),
            "first appended original actor-received DATA_GAP event",
        )
        ordinal = first.get("record_ordinal")
        if (
            type(ordinal) is not int
            or ordinal <= anchor_record_count
            or ordinal > successor_record_count
        ):
            raise TrendPairHandoffAuditError(
                "successor backdated first appended received DATA_GAP market ordinal"
            )
    old_count = anchored["received_gap_record_count"]
    new_count = successor["received_gap_record_count"]
    if not isinstance(old_count, int) or not isinstance(new_count, int):
        raise TrendPairHandoffAuditError("invalid signed gap event counts")
    if new_count < old_count:
        raise TrendPairHandoffAuditError(
            "successor removed received DATA_GAP events"
        )
    return {
        "v2_actor_gap_witness_anchor_record_count": old_count,
        "v2_actor_gap_witness_successor_record_count": new_count,
        "v2_actor_gap_witness_new_record_count": new_count - old_count,
        "v2_actor_gap_witness_anchored_bytes": len(before),
        "v2_actor_gap_witness_successor_bytes": len(after),
        "v2_actor_gap_witness_anchor_digest": anchored["witness_bytes_sha256"],
        "v2_actor_gap_witness_successor_digest": successor["witness_bytes_sha256"],
        "original_actor_received_gap_prefix_preserved": True,
        "original_venue_gap_completeness_authenticated": False,
        "research_only": True,
        "paper_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def audit_v2_selected_anchor_lineage(
    *,
    repository: str,
    anchor_run: dict[str, object] | None,
    anchor_jobs: dict[str, object] | None,
    anchor_artifacts: dict[str, object] | None,
    anchor_archive: Path | None,
    anchor_run_id: int,
    anchor_attempt: int,
    current_run: dict[str, object],
    current_jobs: dict[str, object],
    current_artifacts: dict[str, object],
    current_archive: Path,
    current_run_id: int,
    current_attempt: int,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "unverified",
        "reasons": [],
        "anchor_run_id": anchor_run_id,
        "anchor_attempt": anchor_attempt,
        "current_run_id": current_run_id,
        "current_attempt": current_attempt,
        "v2_source_archive_authenticated": False,
        "v2_selected_anchor_archive_authenticated": False,
        "signed_selected_anchor_prefix_preserved": False,
        "new_signed_checkpoint_append_verified": False,
        "v2_actor_gap_witness_prefix_verified": False,
        "v2_actor_gap_witness_continuity": None,
        "source_gap_lifecycle_state_only": None,
        "independent_market_feed_authenticated": False,
        "v2_campaign_genesis_proven": False,
        "first_archived_v2_worker_proven": False,
        "identical_write_once_genesis_across_workers": False,
        "72h_positive_after_cost_edge_verified": False,
        "paper_only": True,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    try:
        if (
            current_run_id < 1 or current_attempt < 1 or
            anchor_run_id < 1 or anchor_attempt < 1 or
            current_run_id < anchor_run_id or
            (
                current_run_id == anchor_run_id
                and current_attempt != anchor_attempt
            )
        ):
            raise TrendPairHandoffAuditError(
                "invalid v2 selected source and anchor chronology"
            )
        _strict_source(
            run=current_run, jobs=current_jobs,
            artifacts=current_artifacts, archive=current_archive,
            repository=repository, run_id=current_run_id,
            attempt=current_attempt,
        )
        result["v2_source_archive_authenticated"] = True
        if (
            anchor_run is None or anchor_jobs is None
            or anchor_artifacts is None or anchor_archive is None
        ):
            raise TrendPairHandoffAuditError(
                "independent v2 selected anchor evidence missing"
            )
        first_receipt = _strict_source(
            run=anchor_run, jobs=anchor_jobs,
            artifacts=anchor_artifacts, archive=anchor_archive,
            repository=repository, run_id=anchor_run_id,
            attempt=anchor_attempt,
        )
        result["v2_selected_anchor_archive_authenticated"] = True
        with zipfile.ZipFile(anchor_archive) as original, zipfile.ZipFile(
            current_archive,
        ) as successor:
            genesis_name = (
                "both-side-trend-paired-shadow-v2/" + GENESIS_FILE_V2
            )
            anchor_genesis_bytes = _member(original, genesis_name)
            successor_genesis_bytes = _member(successor, genesis_name)
            if anchor_genesis_bytes != successor_genesis_bytes:
                raise TrendPairHandoffAuditError(
                    "v2 selected anchor genesis replaced between workers"
                )
            genesis = verify_v2_genesis(json.loads(anchor_genesis_bytes))
        if (
            genesis["source_github_run_id"] != anchor_run_id
            or genesis["source_github_attempt"] != anchor_attempt
            or genesis["source_github_head_sha"] != anchor_run.get("head_sha")
            or first_receipt.get("v2_genesis_original_worker_authenticated")
            is not True
        ):
            raise TrendPairHandoffAuditError(
                "v2 selected source is not the sealed original genesis worker"
            )
        result["identical_write_once_genesis_across_workers"] = True
        result["first_archived_v2_worker_proven"] = True
        anchor = _ledger_rows(anchor_archive, ledger_member=V2_LEDGER_MEMBER)
        current = _ledger_rows(current_archive, ledger_member=V2_LEDGER_MEMBER)
        comparison = _compare_rows(anchor, current)
        result.update(comparison)
        result["signed_selected_anchor_prefix_preserved"] = True
        gap_witness_continuity = _compare_received_gap_witness_prefix(
            anchor_archive=anchor_archive,
            current_archive=current_archive,
            anchor_record_count=int(comparison["anchored_record_count"]),
            successor_record_count=int(comparison["successor_record_count"]),
        )
        result["v2_actor_gap_witness_continuity"] = gap_witness_continuity
        result["v2_actor_gap_witness_prefix_verified"] = True
        if current_run_id == anchor_run_id:
            if _sha256_file(current_archive) != _sha256_file(anchor_archive):
                raise TrendPairHandoffAuditError(
                    "selected same-attempt v2 source archive differs"
                )
            result["status"] = "v2_selected_anchor_only"
            result["reasons"] = ["no_next_original_worker_authenticated"]
            return result
        if comparison["new_signed_checkpoint_count"] <= 0:
            result["status"] = "v2_no_new_signed_checkpoint"
            result["reasons"] = ["next_paper_worker_has_no_signed_account_advance"]
            return result
        lifecycle = _compare_gap_scopes(
            _archived_gap_scopes(
                anchor_archive, state_member=V2_STATE_MEMBER,
            ),
            _archived_gap_scopes(
                current_archive, state_member=V2_STATE_MEMBER,
            ),
            anchor_end_ms=int(comparison["anchored_end_ms"]),
            successor_end_ms=int(comparison["successor_end_ms"]),
        )
        result["source_gap_lifecycle_state_only"] = lifecycle
        result["new_signed_checkpoint_append_verified"] = True
        result["status"] = "v2_selected_anchor_worker_append_verified"
        result["reasons"] = [
            "first_v2_worker_proven_but_full_venue_history_not_authenticated",
            "original_market_data_and_72h_positive_edge_not_authenticated",
        ]
    except (
        OSError, ValueError, RuntimeError, TypeError, KeyError,
        zipfile.BadZipFile, UnicodeDecodeError,
    ) as exc:
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--anchor-run-id", type=int, required=True)
    parser.add_argument("--anchor-attempt", type=int, default=1)
    parser.add_argument("--current-run-id", type=int, required=True)
    parser.add_argument("--current-attempt", type=int, required=True)
    parser.add_argument("--anchor-run-json", type=Path)
    parser.add_argument("--anchor-jobs-json", type=Path)
    parser.add_argument("--anchor-artifacts-json", type=Path)
    parser.add_argument("--anchor-artifact-zip", type=Path)
    parser.add_argument("--current-run-json", type=Path, required=True)
    parser.add_argument("--current-jobs-json", type=Path, required=True)
    parser.add_argument("--current-artifacts-json", type=Path, required=True)
    parser.add_argument("--current-artifact-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = audit_v2_selected_anchor_lineage(
            repository=args.repository,
            anchor_run_id=args.anchor_run_id,
            anchor_attempt=args.anchor_attempt,
            anchor_run=(
                _json_file(args.anchor_run_json) if args.anchor_run_json else None
            ),
            anchor_jobs=(
                _json_file(args.anchor_jobs_json) if args.anchor_jobs_json else None
            ),
            anchor_artifacts=(
                _json_file(args.anchor_artifacts_json)
                if args.anchor_artifacts_json else None
            ),
            anchor_archive=args.anchor_artifact_zip,
            current_run_id=args.current_run_id,
            current_attempt=args.current_attempt,
            current_run=_json_file(args.current_run_json),
            current_jobs=_json_file(args.current_jobs_json),
            current_artifacts=_json_file(args.current_artifacts_json),
            current_archive=args.current_artifact_zip,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        receipt = {
            "status": "unverified",
            "reasons": [f"{type(exc).__name__}: {exc}"],
            "research_only": True,
            "paper_only": True,
            "execution_authority": False,
            "promotion_authority": False,
        }
    _write_json_atomic(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
