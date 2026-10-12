"""Read-only independent receipt for an archived both-side-trend paired paper handoff.

An outer ZIP matching GitHub artifact metadata is *not* a signed profitable
strategy. This audit independently binds original completed GitHub job steps,
the frozen candidate, both persistent execution stores, account-state digest,
and the append-only checkpoint ledger. No execution or promotion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

from cocomelon.research.loss_context_paired_shadow_review import (
    build_paired_shadow_review,
    review_ledger_receipt,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    TRIAL_ID,
    both_side_trend_matched_shadow_freeze,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    TREND_PAIR_FREEZE_FILE,
    TREND_PAIR_STATE_ROOT,
    TREND_PAIR_SUMMARY_FILE,
)

RUN_NAME: Final = "Continuous Mainnet Paper Trader"
ARTIFACT_PREFIX: Final = "continuous-paper-both-side-trend-paired-shadow-"
MAX_RECEIPT_MEMBER_BYTES: Final = 128 * 1024 * 1024


class TrendPairHandoffAuditError(RuntimeError):
    pass


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise TrendPairHandoffAuditError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _json_file(path: Path) -> dict[str, object]:
    return _mapping(json.loads(path.read_text(encoding="utf-8")), path.name)


def _signed_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _source_class(
    *,
    run: dict[str, object],
    jobs: dict[str, object],
    repository: str,
    run_id: int,
    attempt: int,
) -> str:
    if (
        run.get("id") != run_id
        or run.get("run_attempt") != attempt
        or run.get("name") != RUN_NAME
        or run.get("head_branch") != "main"
        or run.get("status") != "completed"
    ):
        raise TrendPairHandoffAuditError("source worker identity is not exact")
    source_repository = _mapping(run.get("repository"), "repository")
    if source_repository.get("full_name") != repository:
        raise TrendPairHandoffAuditError("source repository identity mismatch")
    source_head = run.get("head_sha")
    if (
        not isinstance(source_head, str) or len(source_head) != 40
        or any(char not in "0123456789abcdef" for char in source_head)
    ):
        raise TrendPairHandoffAuditError("source worker commit is invalid")

    raw_jobs = jobs.get("jobs")
    if not isinstance(raw_jobs, list):
        raise TrendPairHandoffAuditError("source jobs missing")
    successful_steps: set[str] = set()
    for item in raw_jobs:
        job = _mapping(item, "worker job")
        if job.get("run_id") != run_id:
            raise TrendPairHandoffAuditError("foreign source job in job list")
        if job.get("name") != "paper":
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            raise TrendPairHandoffAuditError("paper worker step history absent")
        successful_steps.update(
            str(step["name"])
            for item_step in steps
            if isinstance(item_step, dict)
            for step in [item_step]
            if step.get("conclusion") == "success"
            and isinstance(step.get("name"), str)
        )
    if not {
        "Run continuous paper trader",
        "Upload isolated both-side trend paired-paper evidence",
    } <= successful_steps:
        raise TrendPairHandoffAuditError(
            "original paper and trend archive publication steps not both successful"
        )
    if run.get("conclusion") == "success":
        return "completed_successful_worker"
    return "completed_non_success_worker"


def _validate_artifact(
    artifacts: dict[str, object],
    archive: Path,
    *,
    run_id: int,
    attempt: int,
) -> str:
    raw = artifacts.get("artifacts")
    if not isinstance(raw, list):
        raise TrendPairHandoffAuditError("GitHub artifacts list missing")
    name = f"{ARTIFACT_PREFIX}{run_id}-{attempt}"
    exact = [
        _mapping(item, "source artifact") for item in raw
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(exact) != 1:
        raise TrendPairHandoffAuditError(
            "missing or ambiguous exact original trend paired artifact"
        )
    artifact = exact[0]
    if artifact.get("expired") is True:
        raise TrendPairHandoffAuditError("source trend artifact expired")
    if not archive.is_file():
        raise TrendPairHandoffAuditError("source trend artifact ZIP not downloaded")
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    actual = digest.hexdigest()
    if artifact.get("digest") != f"sha256:{actual}":
        raise TrendPairHandoffAuditError(
            "source artifact outer ZIP SHA256 mismatch"
        )
    return actual


def _member(archive: zipfile.ZipFile, filename: str) -> bytes:
    names = [
        item
        for item in (filename, f"continuous-paper-state/{filename}")
        if item in archive.namelist()
    ]
    if len(names) != 1:
        raise TrendPairHandoffAuditError(
            f"missing or ambiguous independent paired member: {filename}"
        )
    info = archive.getinfo(names[0])
    if info.is_dir() or info.file_size > MAX_RECEIPT_MEMBER_BYTES:
        raise TrendPairHandoffAuditError("paired member is not a bounded file")
    return archive.read(info)


def _extract_receipts(
    archive_path: Path,
    work: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], Path]:
    freeze_path = work / TREND_PAIR_FREEZE_FILE
    ledger_path = work / "review-ledger.jsonl"
    with zipfile.ZipFile(archive_path) as archive:
        freeze_path.write_bytes(_member(archive, TREND_PAIR_FREEZE_FILE))
        summary = _mapping(
            json.loads(_member(archive, TREND_PAIR_SUMMARY_FILE)),
            "trend paired summary",
        )
        state = _mapping(
            json.loads(_member(
                archive, f"{TREND_PAIR_STATE_ROOT}/paired-shadow-state.json",
            )),
            "trend paired state",
        )
        ledger_path.write_bytes(_member(
            archive, f"{TREND_PAIR_STATE_ROOT}/review-ledger.jsonl",
        ))
        for lane in ("baseline", "candidate"):
            name = f"{TREND_PAIR_STATE_ROOT}/{lane}-execution.sqlite3"
            candidates = [
                item
                for item in (name, f"continuous-paper-state/{name}")
                if item in archive.namelist()
            ]
            if len(candidates) != 1 or archive.getinfo(candidates[0]).file_size <= 0:
                raise TrendPairHandoffAuditError(
                    f"paired {lane} execution store absent"
                )
    freeze = verify_loss_context_portfolio_shadow_freeze(freeze_path)
    if freeze != both_side_trend_matched_shadow_freeze():
        raise TrendPairHandoffAuditError("signed freeze != predeclared trend hypothesis")
    return freeze.to_dict(), summary, state, ledger_path


def audit_trend_handoff(
    *,
    run: dict[str, object],
    jobs: dict[str, object],
    artifacts: dict[str, object],
    archive: Path,
    repository: str,
    source_run_id: int,
    source_attempt: int,
) -> dict[str, object]:
    expected = both_side_trend_matched_shadow_freeze()
    result: dict[str, object] = {
        "trial_id": TRIAL_ID,
        "source_run_id": source_run_id,
        "source_run_attempt": source_attempt,
        "expected_candidate_id": expected.candidate_id,
        "source_class": "unverified",
        "status": "unverified",
        "reasons": [],
        "archive_sha256": None,
        "review_report": None,
        "independent_mainnet_market_source_authenticated": False,
        "full_forward_after_cost_profit_verified": False,
        "ready_for_review": False,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
        "promotion_authority": False,
        "execution_authority": False,
    }
    try:
        source_class = _source_class(
            run=run, jobs=jobs, repository=repository,
            run_id=source_run_id, attempt=source_attempt,
        )
        result["source_class"] = source_class
        digest = _validate_artifact(
            artifacts, archive,
            run_id=source_run_id, attempt=source_attempt,
        )
        result["archive_sha256"] = digest
        with tempfile.TemporaryDirectory() as directory:
            freeze, summary, state, ledger_path = _extract_receipts(
                archive, Path(directory),
            )
            if freeze["candidate_id"] != expected.candidate_id:
                raise TrendPairHandoffAuditError("candidate ID mismatch")
            if summary.get("checkpoint_published") is not True:
                raise TrendPairHandoffAuditError("paired checkpoint unpublished")
            if summary.get("checkpoint_error") is not None:
                raise TrendPairHandoffAuditError("paired checkpoint reported error")
            if summary.get("checkpoint") != state:
                raise TrendPairHandoffAuditError("summary/checkpoint/state mismatch")
            if summary.get("frozen_forward_not_before_ms") != (
                expected.prospective_not_before_ms
            ):
                raise TrendPairHandoffAuditError("prospective boundary drift")
            for field in ("promotion_authority", "execution_authority"):
                if summary.get(field) is not False or state.get(field) is not False:
                    raise TrendPairHandoffAuditError(
                        "paired receipt granted prohibited authority"
                    )
            if state.get("portfolio_shadow_candidate_id") != expected.candidate_id:
                raise TrendPairHandoffAuditError("paired durable candidate mismatch")
            unsigned = dict(state)
            digest_value = unsigned.pop("state_digest", None)
            if digest_value != _signed_digest(unsigned):
                raise TrendPairHandoffAuditError("paired durable digest mismatch")
            ledger = review_ledger_receipt(
                ledger_path, candidate_id=expected.candidate_id,
            )
            if (
                state.get("review_ledger_row_count") != ledger["row_count"]
                or state.get("review_ledger_latest_row_digest")
                != ledger["latest_row_digest"]
            ):
                raise TrendPairHandoffAuditError("paired ledger receipt mismatch")
            review = build_paired_shadow_review(expected, ledger_path)
            result["review_report"] = review
            result["record_count"] = state.get("record_count")
            result["verified_checkpoint_count"] = ledger["row_count"]
            result["status"] = "authenticated_handoff"
            if source_class != "completed_successful_worker":
                result["reasons"] = [
                    "source_worker_was_not_fully_successful",
                ]
            elif review.get("ready_for_review") is not True:
                result["reasons"] = ["economic_review_not_ready"]
            else:
                result["reasons"] = [
                    "independent_mainnet_market_source_not_authenticated",
                ]
    except (
        OSError, ValueError, RuntimeError, TypeError,
        zipfile.BadZipFile, UnicodeDecodeError,
    ) as exc:
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--jobs-json", type=Path, required=True)
    parser.add_argument("--artifacts-json", type=Path, required=True)
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.source_run_id < 1 or args.source_attempt < 1:
        parser.error("source worker identity must be positive")
    try:
        receipt = audit_trend_handoff(
            run=_json_file(args.run_json),
            jobs=_json_file(args.jobs_json),
            artifacts=_json_file(args.artifacts_json),
            archive=args.artifact_zip,
            repository=args.repository,
            source_run_id=args.source_run_id,
            source_attempt=args.source_attempt,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        receipt = {
            "status": "unverified", "reasons": [
                f"{type(exc).__name__}: {exc}",
            ],
            "research_only": True, "paper_only": True,
            "promotion_authority": False, "execution_authority": False,
        }
    _write_json_atomic(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
