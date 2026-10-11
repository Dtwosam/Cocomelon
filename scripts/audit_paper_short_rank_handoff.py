"""Independently audit two completed original paper-worker rank artifacts.

Read-only: two original GitHub run/job/artifact API records and the downloaded
artifact ZIP bytes are verified before any chronological rank prefix can pass.
This authenticates only the GitHub artifact chain, NOT the market stream,
funding, trading economics, or live readiness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from cocomelon.research.prospective_short_rank_worker_artifact import (
    ExpectedGithubRankArtifact,
    GithubShortRankArtifactError,
    verify_github_original_short_rank_artifact,
)
from cocomelon.research.prospective_short_rank_worker_handoff import (
    ShortRankHandoffError,
    verify_exact_original_rank_handoff,
)
from scripts.attest_paper_short_rank_artifact import (
    OriginalWorkerAttestationError,
    attest_original_worker_rank_artifact,
)


def _negative(
    code: str, *, source_id: int, predecessor_id: int | None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_worker_run_id_claimed": source_id,
        "predecessor_worker_run_id_claimed": predecessor_id,
        "rank_handoff_status": "unverified",
        "failure_reason_code": code,
        "both_github_original_rank_artifacts_verified": False,
        "original_rank_history_exact_prefix_reconciled": False,
        "source_market_gaps_and_feature_lineage_authenticated": False,
        "risk_matched_account_economics_mature": False,
        "ready_for_review": False,
        "full_account_trial": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _binding(
    run_json: object,
    artifacts_json: object,
    *,
    expected_run_id: int,
) -> ExpectedGithubRankArtifact:
    if not isinstance(run_json, dict) or not isinstance(artifacts_json, dict):
        raise ValueError("missing original worker API metadata")
    attempt = run_json.get("run_attempt")
    if type(attempt) is not int or attempt <= 0:
        raise ValueError("missing original run attempt")
    name = (
        f"continuous-paper-first-seen-short-rank-"
        f"{expected_run_id}-{attempt}"
    )
    rows = artifacts_json.get("artifacts")
    if not isinstance(rows, list):
        raise ValueError("missing original artifact metadata")
    matching = [
        item for item in rows
        if isinstance(item, dict) and item.get("name") == name
    ]
    if len(matching) != 1:
        raise ValueError("original rank artifact not unique")
    artifact: dict[str, Any] = matching[0]
    workflow = artifact.get("workflow_run")
    if not isinstance(workflow, dict):
        raise ValueError("rank artifact lacks source workflow binding")
    return ExpectedGithubRankArtifact(
        run_id=expected_run_id,
        run_attempt=attempt,
        head_sha=run_json.get("head_sha"),
        artifact_run_id=workflow.get("id"),
        artifact_head_sha=workflow.get("head_sha"),
        artifact_name=name,
        artifact_digest=artifact.get("digest"),
        artifact_size_bytes=artifact.get("size_in_bytes"),
    )


def audit_completed_original_rank_handoff(
    *,
    source_run_id: int,
    source_run_attempt: int,
    source_run_json: object,
    source_jobs_json: object,
    source_artifacts_json: object,
    source_artifact_zip: bytes | None,
    predecessor_run_json: object | None,
    predecessor_jobs_json: object | None,
    predecessor_artifacts_json: object | None,
    predecessor_artifact_zip: bytes | None,
    expected_repository: str,
) -> dict[str, object]:
    """Fail closed unless both GitHub-bound artifacts and full prefix match."""
    predecessor_id = None
    if isinstance(predecessor_run_json, dict):
        candidate = predecessor_run_json.get("id")
        if type(candidate) is int and candidate > 0:
            predecessor_id = candidate
    def rejected(code: str) -> dict[str, object]:
        return _negative(
            code, source_id=source_run_id, predecessor_id=predecessor_id,
        )
    if (
        type(source_run_id) is not int or source_run_id <= 0
        or type(source_run_attempt) is not int or source_run_attempt <= 0
    ):
        return rejected("source_run_identity_invalid")
    if (
        predecessor_id is None
        or source_artifact_zip is None
        or predecessor_artifact_zip is None
        or predecessor_jobs_json is None
        or predecessor_artifacts_json is None
    ):
        return rejected("exact_predecessor_source_or_artifact_missing")
    try:
        source_receipt = attest_original_worker_rank_artifact(
            run_json=source_run_json,
            jobs_json=source_jobs_json,
            artifacts_json=source_artifacts_json,
            expected_run_id=source_run_id,
            expected_run_attempt=source_run_attempt,
            expected_repository=expected_repository,
            original_artifact_zip=source_artifact_zip,
        )
        recognized = {
            "github_api_bound_bytes_verified",
            "github_api_bound_upgrade_handoff_only",
        }
        if source_receipt["first_seen_rank_artifact_status"] not in recognized:
            return rejected("successor_rank_source_unverified")
        prior_attempt = predecessor_run_json.get("run_attempt")
        if type(prior_attempt) is not int or prior_attempt <= 0:
            return rejected("predecessor_run_attempt_missing")
        prev_receipt = attest_original_worker_rank_artifact(
            run_json=predecessor_run_json,
            jobs_json=predecessor_jobs_json,
            artifacts_json=predecessor_artifacts_json,
            expected_run_id=predecessor_id,
            expected_run_attempt=prior_attempt,
            expected_repository=expected_repository,
            original_artifact_zip=predecessor_artifact_zip,
        )
        if prev_receipt["first_seen_rank_artifact_status"] not in recognized:
            return rejected("predecessor_rank_source_unverified")
        prev = verify_github_original_short_rank_artifact(
            predecessor_artifact_zip,
            expected=_binding(
                predecessor_run_json,
                predecessor_artifacts_json,
                expected_run_id=predecessor_id,
            ),
        )
        next_source = verify_github_original_short_rank_artifact(
            source_artifact_zip,
            expected=_binding(
                source_run_json,
                source_artifacts_json,
                expected_run_id=source_run_id,
            ),
        )
        handoff = verify_exact_original_rank_handoff(
            predecessor=prev,
            successor=next_source,
            predecessor_run_json=predecessor_run_json,
            successor_run_json=source_run_json,
            expected_repository=expected_repository,
        )
    except (
        OriginalWorkerAttestationError, ShortRankHandoffError,
        GithubShortRankArtifactError, TypeError, ValueError,
    ):
        return rejected("original_rank_handoff_provenance_or_prefix_invalid")
    includes_upgrade_only = (
        source_receipt["original_worker_run_source_class"]
        == "upgrade_handoff_only"
        or prev_receipt["original_worker_run_source_class"]
        == "upgrade_handoff_only"
    )
    return {
        **rejected("none"),
        **handoff,
        "rank_handoff_status": (
            "github_api_bound_upgrade_handoff_prefix_only"
            if includes_upgrade_only
            else "github_api_bound_immutable_prefix"
        ),
        "predecessor_worker_run_source_class": (
            prev_receipt["original_worker_run_source_class"]
        ),
        "successor_worker_run_source_class": (
            source_receipt["original_worker_run_source_class"]
        ),
        "source_chain_contains_upgrade_only_worker": includes_upgrade_only,
        "chain_is_successful_research_source": not includes_upgrade_only,
        "failure_reason_code": None,
        "both_github_original_rank_artifacts_verified": True,
        "original_rank_history_exact_prefix_reconciled": True,
        "source_market_gaps_and_feature_lineage_authenticated": False,
        "risk_matched_account_economics_mature": False,
        "ready_for_review": False,
        "full_account_trial": False,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _read_json(path: Path) -> object | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_zip(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-run-id", type=int, required=True)
    p.add_argument("--source-run-attempt", type=int, required=True)
    p.add_argument("--repository", required=True)
    p.add_argument("--source-dir", type=Path, required=True)
    p.add_argument("--predecessor-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    source = args.source_dir
    predecessor = args.predecessor_dir
    evidence = audit_completed_original_rank_handoff(
        source_run_id=args.source_run_id,
        source_run_attempt=args.source_run_attempt,
        source_run_json=_read_json(source / "run.json"),
        source_jobs_json=_read_json(source / "jobs.json"),
        source_artifacts_json=_read_json(source / "artifacts.json"),
        source_artifact_zip=_read_zip(source / "artifact.zip"),
        predecessor_run_json=_read_json(predecessor / "run.json"),
        predecessor_jobs_json=_read_json(predecessor / "jobs.json"),
        predecessor_artifacts_json=_read_json(predecessor / "artifacts.json"),
        predecessor_artifact_zip=_read_zip(predecessor / "artifact.zip"),
        expected_repository=args.repository,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
