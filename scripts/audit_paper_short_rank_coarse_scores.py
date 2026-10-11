"""Read-only GitHub source audit of original SHORT coarse rank arithmetic.

After a completed original PAPER worker, independently pin both the full
first-seen rank ZIP and its prospective complete feature-input ZIP to GitHub
API metadata, then recompute all ordinal/score/reason rows in that suffix.
This does not prove the recorded market eligibility universe or profit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, cast

from cocomelon.research.prospective_short_rank_full_feature_artifact import (
    ExpectedGithubRankInputArtifact,
    OriginalRankFeatureArtifactError,
    verify_github_original_rank_full_input_artifact,
)
from cocomelon.research.prospective_short_rank_score_recomputation import (
    OriginalRankScoreRecomputationError,
    recompute_original_short_rank_coarse_scores,
)
from cocomelon.research.prospective_short_rank_worker_artifact import (
    GithubShortRankArtifactError,
    verify_github_original_short_rank_artifact,
)
from scripts.attest_paper_short_rank_artifact import (
    OriginalWorkerAttestationError,
    attest_original_worker_rank_artifact,
)
from scripts.audit_paper_short_rank_handoff import _binding


def _refuse(reason: str, run_id: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "original_worker_run_id_claimed": run_id,
        "rank_coarse_score_audit_status": "unverified",
        "failure_reason_code": reason,
        "both_original_worker_artifact_sha256s_verified": False,
        "original_rank_feature_scores_recomputed": False,
        "rankable_market_membership_independently_reconstructed": False,
        "mainnet_market_source_and_gaps_authenticated": False,
        "signed_account_positive_after_cost_expectancy_proven": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _input_binding(
    run: dict[str, Any],
    artifacts: dict[str, Any],
    run_id: int,
) -> ExpectedGithubRankInputArtifact:
    attempt = run.get("run_attempt")
    head = run.get("head_sha")
    if type(attempt) is not int or attempt <= 0:
        raise OriginalRankFeatureArtifactError(
            "original completed worker attempt invalid"
        )
    rows = artifacts.get("artifacts")
    if not isinstance(rows, list):
        raise OriginalRankFeatureArtifactError(
            "original rank-input artifact API population missing"
        )
    name = (
        "continuous-paper-first-seen-short-rank-full-inputs-"
        f"{run_id}-{attempt}"
    )
    candidates = [
        row for row in rows
        if isinstance(row, dict) and row.get("name") == name
    ]
    if len(candidates) != 1:
        raise OriginalRankFeatureArtifactError(
            "original full-input artifact absent or ambiguous"
        )
    candidate = candidates[0]
    source_run = candidate.get("workflow_run")
    if (
        candidate.get("expired") is not False
        or not isinstance(source_run, dict)
    ):
        raise OriginalRankFeatureArtifactError(
            "original feature artifact expired or has no GitHub source"
        )
    return ExpectedGithubRankInputArtifact(
        run_id=run_id,
        run_attempt=attempt,
        head_sha=head,
        artifact_run_id=source_run.get("id"),
        artifact_head_sha=source_run.get("head_sha"),
        artifact_name=name,
        artifact_digest=candidate.get("digest"),
        artifact_size_bytes=candidate.get("size_in_bytes"),
    )


FULL_FEATURE_SUCCESS_STEPS = (
    "Seal entire original SHORT rank input features after paper exit",
    "Upload original SHORT rank full-input seal or rejection",
)


def audit_original_worker_rank_score_sources(
    *,
    run_id: int,
    run_attempt: int,
    run_json: object,
    jobs_json: object,
    artifacts_json: object,
    rank_artifact_zip: bytes | None,
    full_input_artifact_zip: bytes | None,
    expected_repository: str,
) -> dict[str, object]:
    """Do not claim arithmetic parity without two independently verified ZIPs."""
    if (
        type(run_id) is not int or run_id <= 0
        or type(run_attempt) is not int or run_attempt <= 0
    ):
        return _refuse("original_worker_run_attempt_invalid", run_id)
    if rank_artifact_zip is None:
        return _refuse("original_worker_rank_archive_unavailable", run_id)
    if full_input_artifact_zip is None:
        return _refuse("original_full_feature_input_archive_unavailable", run_id)
    try:
        rank_attestation = attest_original_worker_rank_artifact(
            run_json=run_json,
            jobs_json=jobs_json,
            artifacts_json=artifacts_json,
            expected_run_id=run_id,
            expected_run_attempt=run_attempt,
            expected_repository=expected_repository,
            original_artifact_zip=rank_artifact_zip,
        )
        source_class = rank_attestation.get("original_worker_run_source_class")
        if (
            rank_attestation.get("first_seen_rank_artifact_status")
            not in (
                "github_api_bound_bytes_verified",
                "github_api_bound_upgrade_handoff_only",
            )
            or source_class not in (
                "successful_research_run", "upgrade_handoff_only",
            )
        ):
            return _refuse("original_worker_rank_source_unverified", run_id)
        if not isinstance(jobs_json, dict):
            return _refuse("original_full_input_worker_jobs_invalid", run_id)
        job_rows = jobs_json.get("jobs")
        if not isinstance(job_rows, list):
            return _refuse("original_full_input_worker_jobs_invalid", run_id)
        paper_jobs = [
            row for row in job_rows
            if isinstance(row, dict) and row.get("name") == "paper"
        ]
        if len(paper_jobs) != 1 or not isinstance(
            paper_jobs[0].get("steps"), list
        ):
            return _refuse("original_full_input_worker_jobs_invalid", run_id)
        steps = paper_jobs[0]["steps"]
        for step_name in FULL_FEATURE_SUCCESS_STEPS:
            matches = [
                step for step in steps
                if isinstance(step, dict) and step.get("name") == step_name
            ]
            if len(matches) != 1 or matches[0].get("conclusion") != "success":
                return _refuse("original_full_input_export_step_not_successful", run_id)
        if not isinstance(run_json, dict) or not isinstance(artifacts_json, dict):
            return _refuse("original_github_worker_metadata_invalid", run_id)
        run = cast(dict[str, Any], run_json)
        artifacts = cast(dict[str, Any], artifacts_json)
        rank_source = verify_github_original_short_rank_artifact(
            rank_artifact_zip,
            expected=_binding(run, artifacts, expected_run_id=run_id),
        )
        original_inputs = verify_github_original_rank_full_input_artifact(
            full_input_artifact_zip,
            expected=_input_binding(run, artifacts, run_id),
            original_rank=rank_source,
        )
        score_receipt = recompute_original_short_rank_coarse_scores(
            original_rank=rank_source,
            original_inputs=original_inputs,
        )
    except (
        OriginalWorkerAttestationError,
        GithubShortRankArtifactError,
        OriginalRankFeatureArtifactError,
        OriginalRankScoreRecomputationError,
        OSError, ValueError, TypeError,
    ):
        return _refuse("original_worker_coarse_score_source_or_arithmetic_invalid", run_id)
    return {
        **_refuse("none", run_id),
        **score_receipt,
        "rank_coarse_score_audit_status": (
            "github_bound_arithmetic_verified"
            if source_class == "successful_research_run"
            else "github_bound_upgrade_handoff_arithmetic_only"
        ),
        "original_worker_source_class": source_class,
        "failure_reason_code": None,
        "both_original_worker_artifact_sha256s_verified": True,
        "original_rank_feature_scores_recomputed": True,
        "rankable_market_membership_independently_reconstructed": False,
        "mainnet_market_source_and_gaps_authenticated": False,
        "signed_account_positive_after_cost_expectancy_proven": False,
        "full_account_trial": False,
        "ready_for_review": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def _zip(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-run-attempt", type=int, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original = args.source_dir
    rank_archive = original / "artifact.zip"
    input_archive = original / "full-input-artifact.zip"
    report = audit_original_worker_rank_score_sources(
        run_id=args.source_run_id,
        run_attempt=args.source_run_attempt,
        run_json=_json(original / "run.json"),
        jobs_json=_json(original / "jobs.json"),
        artifacts_json=_json(original / "artifacts.json"),
        rank_artifact_zip=_zip(rank_archive),
        full_input_artifact_zip=_zip(input_archive),
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
