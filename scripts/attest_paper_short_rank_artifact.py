"""Read-only first-seen SHORT rank provenance audit for completed paper workers.

This module checks GitHub API response data passed by a trusted workflow and
verifies both original artifact ZIP layers. It NEVER promotes a candidate or
turns self-asserted run metadata into proof of exchange data completeness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from cocomelon.research.prospective_short_rank_worker_artifact import (
    ExpectedGithubRankArtifact,
    GithubShortRankArtifactError,
    verify_github_original_short_rank_artifact,
)

WORKFLOW_PATH = ".github/workflows/continuous-paper.yml"
REQUIRED_SUCCESSFUL_PAPER_STEPS = (
    "Run continuous paper trader",
    "Seal original first-seen SHORT rank source after worker exit",
    "Upload original first-seen SHORT rank seal and failure receipt",
)
UPGRADE_ONLY_FAILURE_STEP = "Fail closed on upgrade handoff source"
DURABLE_HANDOFF_STEP = "Upload durable continuous paper state"


class OriginalWorkerAttestationError(RuntimeError):
    pass


def _dict(raw: object, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise OriginalWorkerAttestationError(f"{label} response is not an object")
    return cast(dict[str, Any], raw)


def _refuse(reason: str, *, run_id: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_worker_run_id_claimed": run_id,
        "first_seen_rank_artifact_status": "unverified",
        "failure_reason_code": reason,
        "github_artifact_digest_and_step_metadata_checked": False,
        "original_exchange_market_stream_authenticated": False,
        "rank_feature_market_lineage_verified": False,
        "forward_maturity_certified": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def attest_original_worker_rank_artifact(
    *,
    run_json: object,
    jobs_json: object,
    artifacts_json: object,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_repository: str,
    original_artifact_zip: bytes | None,
) -> dict[str, object]:
    """Return a verified archive receipt or explicit evidence failure.

    API data origin is authenticated by the GitHub workflow that invokes this
    function using the read-only GITHUB_TOKEN, not by this pure function.
    """
    if type(expected_run_id) is not int or expected_run_id <= 0:
        raise OriginalWorkerAttestationError("expected worker ID invalid")
    if type(expected_run_attempt) is not int or expected_run_attempt <= 0:
        raise OriginalWorkerAttestationError("expected worker attempt invalid")
    if (
        not expected_repository or expected_repository.count("/") != 1
        or expected_repository.startswith("/") or expected_repository.endswith("/")
    ):
        raise OriginalWorkerAttestationError("expected repository invalid")
    run = _dict(run_json, "run")
    jobs = _dict(jobs_json, "jobs")
    artifacts = _dict(artifacts_json, "artifacts")
    source_id = run.get("id")
    if (
        source_id != expected_run_id
        or run.get("status") != "completed"
        or run.get("head_branch") != "main"
        or run.get("path") != WORKFLOW_PATH
        or run.get("event") not in {"push", "workflow_dispatch"}
        or _dict(run.get("head_repository"), "head repository").get("full_name")
        != expected_repository
        or _dict(run.get("repository"), "repository").get("full_name")
        != expected_repository
    ):
        return _refuse("original_worker_run_identity_unverified", run_id=expected_run_id)
    run_attempt = run.get("run_attempt")
    head = run.get("head_sha")
    if (
        type(run_attempt) is not int
        or run_attempt != expected_run_attempt
        or not isinstance(head, str)
    ):
        return _refuse("original_worker_attempt_or_head_invalid", run_id=expected_run_id)
    job_rows = jobs.get("jobs")
    if not isinstance(job_rows, list):
        return _refuse("original_worker_jobs_missing", run_id=expected_run_id)
    paper_jobs = [
        item for item in job_rows
        if isinstance(item, dict) and item.get("name") == "paper"
    ]
    if len(paper_jobs) != 1:
        return _refuse("original_paper_job_not_unique", run_id=expected_run_id)
    paper = paper_jobs[0]
    if paper.get("run_attempt") not in (None, run_attempt):
        return _refuse("paper_job_attempt_mismatch", run_id=expected_run_id)
    steps = paper.get("steps")
    if not isinstance(steps, list):
        return _refuse("paper_proof_steps_missing", run_id=expected_run_id)
    for name in REQUIRED_SUCCESSFUL_PAPER_STEPS:
        matches = [
            step for step in steps
            if isinstance(step, dict) and step.get("name") == name
        ]
        if len(matches) != 1 or matches[0].get("conclusion") != "success":
            return _refuse(
                "paper_proof_step_missing_or_unsuccessful",
                run_id=expected_run_id,
            )
    # A worker exiting for an upgrade intentionally fails the late research
    # source gate after preserving the original state and sealing ranks. Never
    # portray its overall failed run as successful standalone research, and
    # never reject its SHA-verified historical rank bytes solely because that
    # explicit *expected* upgrade gate failed. Any other failure is untrusted.
    paper_conclusion = paper.get("conclusion")
    run_conclusion = run.get("conclusion")
    if run.get("status") != "completed" or paper.get("status") != "completed":
        return _refuse("original_paper_run_or_job_not_completed", run_id=expected_run_id)
    if paper_conclusion == "success" and run_conclusion == "success":
        if any(
            isinstance(step, dict) and step.get("conclusion") == "failure"
            for step in steps
        ):
            return _refuse(
                "successful_worker_contains_failed_step", run_id=expected_run_id,
            )
        rank_run_outcome = "successful_research_run"
    elif paper_conclusion == "failure" and run_conclusion == "failure":
        failed = [
            step.get("name") for step in steps
            if isinstance(step, dict) and step.get("conclusion") == "failure"
        ]
        durable = [
            step for step in steps
            if isinstance(step, dict) and step.get("name") == DURABLE_HANDOFF_STEP
        ]
        if (
            failed != [UPGRADE_ONLY_FAILURE_STEP]
            or len(durable) != 1
            or durable[0].get("conclusion") != "success"
        ):
            return _refuse(
                "failed_worker_not_exact_state_preserving_upgrade",
                run_id=expected_run_id,
            )
        rank_run_outcome = "upgrade_handoff_only"
    else:
        return _refuse(
            "worker_run_and_paper_job_outcomes_disagree",
            run_id=expected_run_id,
        )
    artifact_rows = artifacts.get("artifacts")
    if not isinstance(artifact_rows, list):
        return _refuse("original_rank_artifacts_missing", run_id=expected_run_id)
    artifact_name = (
        f"continuous-paper-first-seen-short-rank-{expected_run_id}-{run_attempt}"
    )
    candidates = [
        row for row in artifact_rows
        if isinstance(row, dict) and row.get("name") == artifact_name
    ]
    if len(candidates) != 1:
        return _refuse("rank_artifact_missing_or_ambiguous", run_id=expected_run_id)
    candidate = candidates[0]
    workflow_run = candidate.get("workflow_run")
    if (
        candidate.get("expired") is not False
        or not isinstance(workflow_run, dict)
    ):
        return _refuse("rank_artifact_expired_or_unbound", run_id=expected_run_id)
    if original_artifact_zip is None:
        return _refuse("rank_artifact_zip_unavailable", run_id=expected_run_id)
    try:
        binding = ExpectedGithubRankArtifact(
            run_id=expected_run_id,
            run_attempt=run_attempt,
            head_sha=head,
            artifact_run_id=workflow_run.get("id"),
            artifact_head_sha=workflow_run.get("head_sha"),
            artifact_name=artifact_name,
            artifact_digest=candidate.get("digest"),
            artifact_size_bytes=candidate.get("size_in_bytes"),
        )
        result = verify_github_original_short_rank_artifact(
            original_artifact_zip, expected=binding,
        )
    except (GithubShortRankArtifactError, TypeError, ValueError):
        return _refuse("rank_artifact_digest_or_content_invalid", run_id=expected_run_id)
    return {
        **_refuse("none", run_id=expected_run_id),
        **result.receipt(),
        "first_seen_rank_artifact_status": (
            "github_api_bound_bytes_verified"
            if rank_run_outcome == "successful_research_run"
            else "github_api_bound_upgrade_handoff_only"
        ),
        "original_worker_run_source_class": rank_run_outcome,
        "rank_artifact_from_failed_original_workflow": (
            rank_run_outcome == "upgrade_handoff_only"
        ),
        "successful_research_run_proven": (
            rank_run_outcome == "successful_research_run"
        ),
        "upgrade_handoff_exit_reason_independently_attested": False,
        "failure_reason_code": None,
        "rank_artifact_id": candidate.get("id"),
        "rank_artifact_name": artifact_name,
        "rank_artifact_sha256": candidate.get("digest"),
        "original_worker_run_attempt": run_attempt,
        "original_worker_head_sha": head,
        "github_artifact_digest_and_step_metadata_checked": True,
        "github_api_origin_authenticated_by_caller": False,
        "original_exchange_market_stream_authenticated": False,
        "rank_feature_market_lineage_verified": False,
        "forward_maturity_certified": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-json", type=Path, required=True)
    p.add_argument("--jobs-json", type=Path, required=True)
    p.add_argument("--artifacts-json", type=Path, required=True)
    p.add_argument("--artifact-zip", type=Path, required=True)
    p.add_argument("--source-run-id", type=int, required=True)
    p.add_argument("--source-run-attempt", type=int, required=True)
    p.add_argument("--repository", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    raw = (
        args.artifact_zip.read_bytes() if args.artifact_zip.is_file() else None
    )
    evidence = attest_original_worker_rank_artifact(
        run_json=json.loads(args.run_json.read_text(encoding="utf-8")),
        jobs_json=json.loads(args.jobs_json.read_text(encoding="utf-8")),
        artifacts_json=json.loads(args.artifacts_json.read_text(encoding="utf-8")),
        expected_run_id=args.source_run_id,
        expected_run_attempt=args.source_run_attempt,
        expected_repository=args.repository,
        original_artifact_zip=raw,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            evidence, sort_keys=True, separators=(",", ":"),
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
