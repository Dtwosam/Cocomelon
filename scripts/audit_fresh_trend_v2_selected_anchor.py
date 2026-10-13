"""Independent selected-anchor v2 worker ledger extension.

A selected archive anchor is NOT proof of the first genuine v2 worker.
No SQLite state or signed ledger can be rewritten, recovered, or promoted.
"""

from __future__ import annotations

import argparse
import json
import os
import zipfile
from collections.abc import Sequence
from pathlib import Path

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
    _write_json_atomic,
    audit_trend_handoff,
)

V2_LEDGER_MEMBER = "both-side-trend-paired-shadow-v2/review-ledger.jsonl"
V2_STATE_MEMBER = "both-side-trend-paired-shadow-v2/paired-shadow-state.json"
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
        or receipt.get("archive_sha256") != _sha256_file(archive)
        or receipt.get("promotion_authority") is not False
        or receipt.get("execution_authority") is not False
    ):
        raise TrendPairHandoffAuditError(
            "v2 selected source was not independently account-authenticated"
        )
    return receipt


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
        "source_gap_lifecycle_state_only": None,
        "independent_market_feed_authenticated": False,
        "v2_campaign_genesis_proven": False,
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
        _strict_source(
            run=anchor_run, jobs=anchor_jobs,
            artifacts=anchor_artifacts, archive=anchor_archive,
            repository=repository, run_id=anchor_run_id,
            attempt=anchor_attempt,
        )
        result["v2_selected_anchor_archive_authenticated"] = True
        anchor = _ledger_rows(anchor_archive, ledger_member=V2_LEDGER_MEMBER)
        current = _ledger_rows(current_archive, ledger_member=V2_LEDGER_MEMBER)
        comparison = _compare_rows(anchor, current)
        result.update(comparison)
        result["signed_selected_anchor_prefix_preserved"] = True
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
            "selected_anchor_is_not_proven_first_v2_genesis",
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
