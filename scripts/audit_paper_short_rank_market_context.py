"""Three-source original SHORT rank eligibility audit from GitHub API evidence.

Requires independently fetched completed paper worker run/jobs/artifacts and
all three original GitHub artifact ZIP bytes. Never accepts a producer claim
as Hyperliquid exchange-feed authentication or profitable account expectancy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from cocomelon.research.prospective_short_rank_full_feature_artifact import (
    OriginalRankFeatureArtifactError,
    verify_github_original_rank_full_input_artifact,
)
from cocomelon.research.prospective_short_rank_market_context_artifact import (
    ExpectedGithubRankContextArtifact,
    OriginalRankContextArtifactError,
    verify_github_original_rank_market_context_artifact,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    GithubShortRankArtifactError,
    verify_github_original_short_rank_artifact,
)
from scripts.attest_paper_short_rank_artifact import (
    OriginalWorkerAttestationError,
    attest_original_worker_rank_artifact,
)
from scripts.audit_paper_short_rank_coarse_scores import (
    FULL_FEATURE_SUCCESS_STEPS,
    _input_binding,
    _json,
    _zip,
)
from scripts.audit_paper_short_rank_handoff import _binding

CONTEXT_SUCCESS_STEPS = (
    "Seal original SHORT rank market context after paper exit",
    "Upload original SHORT rank market context seal or rejection",
)


def _refuse(reason: str, run_id: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "original_worker_run_id_claimed": run_id,
        "rank_market_context_audit_status": "unverified",
        "failure_reason_code": reason,
        "all_three_original_worker_artifact_sha256s_verified": False,
        "rankable_market_membership_reconstructed_from_recorded_context": False,
        "original_mainnet_market_stream_and_gaps_authenticated": False,
        "original_after_cost_full_account_profitable": False,
        "ready_for_review": False,
        "full_account_trial": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _context_binding(
    run: dict[str, Any],
    artifacts: dict[str, Any],
    run_id: int,
) -> ExpectedGithubRankContextArtifact:
    attempt = run.get("run_attempt")
    head = run.get("head_sha")
    rows = artifacts.get("artifacts")
    if type(attempt) is not int or attempt <= 0 or not isinstance(rows, list):
        raise OriginalRankContextArtifactError(
            "original GitHub context artifact metadata missing"
        )
    name = (
        "continuous-paper-first-seen-short-rank-market-context-"
        f"{run_id}-{attempt}"
    )
    matches = [
        row for row in rows
        if isinstance(row, dict) and row.get("name") == name
    ]
    if len(matches) != 1:
        raise OriginalRankContextArtifactError(
            "original market context artifact missing or ambiguous"
        )
    item = matches[0]
    wr = item.get("workflow_run")
    if item.get("expired") is not False or not isinstance(wr, dict):
        raise OriginalRankContextArtifactError(
            "original GitHub context artifact expired or unbound"
        )
    return ExpectedGithubRankContextArtifact(
        run_id=run_id,
        run_attempt=attempt,
        head_sha=head,
        artifact_run_id=wr.get("id"),
        artifact_head_sha=wr.get("head_sha"),
        artifact_name=name,
        artifact_digest=item.get("digest"),
        artifact_size_bytes=item.get("size_in_bytes"),
    )


def audit_original_worker_rank_context_sources(
    *,
    run_id: int,
    run_attempt: int,
    run_json: object,
    jobs_json: object,
    artifacts_json: object,
    rank_artifact_zip: bytes | None,
    full_input_artifact_zip: bytes | None,
    context_artifact_zip: bytes | None,
    expected_repository: str,
) -> dict[str, object]:
    """An absent, in-flight, wrong-run or changed source emits negative receipt."""
    if (
        type(run_id) is not int or run_id <= 0
        or type(run_attempt) is not int or run_attempt <= 0
    ):
        return _refuse("original_worker_run_attempt_invalid", run_id)
    for blob, reason in (
        (rank_artifact_zip, "original_rank_artifact_unavailable"),
        (full_input_artifact_zip, "original_full_input_artifact_unavailable"),
        (context_artifact_zip, "original_context_artifact_unavailable"),
    ):
        if blob is None:
            return _refuse(reason, run_id)
    try:
        attestation = attest_original_worker_rank_artifact(
            run_json=run_json,
            jobs_json=jobs_json,
            artifacts_json=artifacts_json,
            expected_run_id=run_id,
            expected_run_attempt=run_attempt,
            expected_repository=expected_repository,
            original_artifact_zip=rank_artifact_zip,
        )
        cls = attestation.get("original_worker_run_source_class")
        if (
            attestation.get("first_seen_rank_artifact_status") not in (
                "github_api_bound_bytes_verified",
                "github_api_bound_upgrade_handoff_only",
            )
            or cls not in ("successful_research_run", "upgrade_handoff_only")
        ):
            return _refuse("original_worker_rank_source_unverified", run_id)
        if not isinstance(jobs_json, dict):
            return _refuse("original_worker_job_metadata_invalid", run_id)
        jobs = jobs_json.get("jobs")
        if not isinstance(jobs, list):
            return _refuse("original_worker_job_metadata_invalid", run_id)
        papers = [
            row for row in jobs
            if isinstance(row, dict) and row.get("name") == "paper"
        ]
        if len(papers) != 1 or not isinstance(papers[0].get("steps"), list):
            return _refuse("original_worker_job_metadata_invalid", run_id)
        steps = papers[0]["steps"]
        for name in (*FULL_FEATURE_SUCCESS_STEPS, *CONTEXT_SUCCESS_STEPS):
            found = [
                step for step in steps
                if isinstance(step, dict) and step.get("name") == name
            ]
            if len(found) != 1 or found[0].get("conclusion") != "success":
                return _refuse("original_context_or_full_source_export_not_successful", run_id)
        if not isinstance(run_json, dict) or not isinstance(artifacts_json, dict):
            return _refuse("original_github_source_metadata_invalid", run_id)
        run = cast(dict[str, Any], run_json)
        artifacts = cast(dict[str, Any], artifacts_json)
        rank = verify_github_original_short_rank_artifact(
            rank_artifact_zip,
            expected=_binding(run, artifacts, expected_run_id=run_id),
        )
        features = verify_github_original_rank_full_input_artifact(
            full_input_artifact_zip,
            expected=_input_binding(run, artifacts, run_id),
            original_rank=rank,
        )
        context = verify_github_original_rank_market_context_artifact(
            context_artifact_zip,
            expected=_context_binding(run, artifacts, run_id),
            original_rank=rank,
            original_features=features,
        )
    except (
        OriginalWorkerAttestationError,
        GithubShortRankArtifactError,
        OriginalRankFeatureArtifactError,
        OriginalRankContextArtifactError,
        OSError, ValueError, TypeError,
    ):
        return _refuse("original_context_source_or_eligibility_replay_invalid", run_id)
    return {
        **_refuse("none", run_id),
        **context.receipt(),
        "rank_market_context_audit_status": (
            "github_bound_recorded_context_eligibility_replayed"
            if cls == "successful_research_run"
            else "github_bound_upgrade_handoff_eligibility_only"
        ),
        "original_worker_run_source_class": cls,
        "failure_reason_code": None,
        "all_three_original_worker_artifact_sha256s_verified": True,
        "rankable_market_membership_reconstructed_from_recorded_context": True,
        "original_mainnet_market_stream_and_gaps_authenticated": False,
        "original_after_cost_full_account_profitable": False,
        "ready_for_review": False,
        "full_account_trial": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-run-attempt", type=int, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    p = args.source_dir
    report = audit_original_worker_rank_context_sources(
        run_id=args.source_run_id,
        run_attempt=args.source_run_attempt,
        run_json=_json(p / "run.json"),
        jobs_json=_json(p / "jobs.json"),
        artifacts_json=_json(p / "artifacts.json"),
        rank_artifact_zip=_zip(p / "artifact.zip"),
        full_input_artifact_zip=_zip(p / "full-input-artifact.zip"),
        context_artifact_zip=_zip(p / "market-context-artifact.zip"),
        expected_repository=args.repository,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
