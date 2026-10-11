from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from scripts.attest_paper_short_rank_artifact import (
    REQUIRED_SUCCESSFUL_PAPER_STEPS,
    OriginalWorkerAttestationError,
    attest_original_worker_rank_artifact,
)
from scripts.seal_paper_short_rank_archive import (
    ARCHIVE_NAME,
    RECEIPT_NAME,
    seal_completed_short_rank_archive,
)

RUN = 38162541394
HEAD = "a" * 40
REPOSITORY = "Dtwosam/Cocomelon"
OBS = 1_790_000_000_000


def _inputs(
    tmp_path: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], bytes]:
    state, output = tmp_path / "worker-state", tmp_path / "published"
    store = FirstSeenRankSnapshotStore(
        state / "prospective-short-rank-first-seen"
    )
    store.append(FirstSeenRankSnapshot(
        observed_at_ms=OBS, captured_at_ms=OBS + 80,
        features=(("BTC", "original-feature", OBS - 100),),
        ranks=(("BTC", 1, "0.9", ("original-coarse",)),),
    ))
    proof = seal_completed_short_rank_archive(
        state, output, worker_run_id=RUN, worker_run_attempt=1,
        worker_head_sha=HEAD, sealed_at_ms=OBS + 500,
    )
    assert proof["rank_source_status"] == "locally_sealed"
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as zipout:
        zipout.writestr(RECEIPT_NAME, (output / RECEIPT_NAME).read_bytes())
        zipout.writestr(ARCHIVE_NAME, (output / ARCHIVE_NAME).read_bytes())
    raw = outer.getvalue()
    run: dict[str, object] = {
        "id": RUN, "status": "completed",
        "head_branch": "main", "path": ".github/workflows/continuous-paper.yml",
        "event": "workflow_dispatch", "run_attempt": 1, "head_sha": HEAD,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }
    jobs: dict[str, object] = {
        "jobs": [{
            "name": "paper", "run_attempt": 1,
            "steps": [
                {"name": name, "conclusion": "success"}
                for name in REQUIRED_SUCCESSFUL_PAPER_STEPS
            ],
        }],
    }
    artifacts: dict[str, object] = {
        "artifacts": [{
            "id": 10001,
            "name": f"continuous-paper-first-seen-short-rank-{RUN}-1",
            "size_in_bytes": len(raw),
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "expired": False,
            "workflow_run": {"id": RUN, "head_sha": HEAD},
        }],
    }
    return run, jobs, artifacts, raw


def _assess(
    run: object, jobs: object, artifacts: object, raw: bytes | None,
    *,
    expected_attempt: int = 1,
) -> dict[str, object]:
    return attest_original_worker_rank_artifact(
        run_json=run, jobs_json=jobs,
        artifacts_json=artifacts,
        expected_run_id=RUN,
        expected_run_attempt=expected_attempt,
        expected_repository=REPOSITORY,
        original_artifact_zip=raw,
    )


def test_github_source_successful_original_paper_step_and_sha_are_all_required(
    tmp_path: Path,
) -> None:
    run, jobs, artifacts, raw = _inputs(tmp_path)
    result = _assess(run, jobs, artifacts, raw)
    assert result["first_seen_rank_artifact_status"] == (
        "github_api_bound_bytes_verified"
    )
    assert result["github_artifact_digest_and_step_metadata_checked"] is True
    assert result["rank_snapshot_count"] == 1
    assert result["original_worker_head_sha"] == HEAD
    assert result["original_worker_run_attempt"] == 1
    assert result["original_exchange_market_stream_authenticated"] is False
    assert result["rank_feature_market_lineage_verified"] is False
    assert result["full_account_trial"] is False
    assert result["ready_for_review"] is False
    assert result["promotion_authority"] is False


@pytest.mark.parametrize(
    "blocked_name",
    REQUIRED_SUCCESSFUL_PAPER_STEPS,
)
def test_unfinished_paper_seal_or_upload_steps_cannot_attest(
    tmp_path: Path, blocked_name: str,
) -> None:
    run, jobs, artifacts, raw = _inputs(tmp_path)
    job = jobs["jobs"][0]  # type: ignore[index]
    for step in job["steps"]:
        if step["name"] == blocked_name:
            step["conclusion"] = "failure"
    result = _assess(run, jobs, artifacts, raw)
    assert result["first_seen_rank_artifact_status"] == "unverified"
    assert result["failure_reason_code"] == (
        "paper_proof_step_missing_or_unsuccessful"
    )


def test_original_worker_different_head_attempt_or_run_is_not_attributed(
    tmp_path: Path,
) -> None:
    run, jobs, artifacts, raw = _inputs(tmp_path)
    modified = dict(run, head_sha="b" * 40)
    result = _assess(modified, jobs, artifacts, raw)
    assert result["first_seen_rank_artifact_status"] == "unverified"
    assert result["failure_reason_code"] == (
        "rank_artifact_digest_or_content_invalid"
    )
    assert _assess(run, jobs, artifacts, raw, expected_attempt=2)[
        "failure_reason_code"
    ] == "original_worker_attempt_or_head_invalid"
    modified = dict(run, id=RUN + 1)
    assert _assess(modified, jobs, artifacts, raw)[
        "failure_reason_code"
    ] == "original_worker_run_identity_unverified"


def test_absent_duplicate_expired_artifact_fails_closed(
    tmp_path: Path,
) -> None:
    run, jobs, artifacts, raw = _inputs(tmp_path)
    artifact = artifacts["artifacts"][0]  # type: ignore[index]
    assert _assess(run, jobs, {"artifacts": []}, raw)[
        "failure_reason_code"
    ] == "rank_artifact_missing_or_ambiguous"
    assert _assess(run, jobs, {"artifacts": [artifact, artifact]}, raw)[
        "failure_reason_code"
    ] == "rank_artifact_missing_or_ambiguous"
    assert _assess(
        run, jobs, {"artifacts": [dict(artifact, expired=True)]}, raw,
    )["failure_reason_code"] == "rank_artifact_expired_or_unbound"
    assert _assess(run, jobs, artifacts, None)[
        "failure_reason_code"
    ] == "rank_artifact_zip_unavailable"


def test_missing_rank_data_in_original_worker_has_no_positive_economic_receipt(
    tmp_path: Path,
) -> None:
    run, jobs, artifacts, raw = _inputs(tmp_path)
    proof = _assess(run, jobs, artifacts, raw + b"bitflip")
    assert proof["failure_reason_code"] == (
        "rank_artifact_digest_or_content_invalid"
    )
    assert proof["ready_for_review"] is False
    assert proof["full_account_trial"] is False
    assert proof["execution_authority"] is False


def test_invalid_user_provided_expected_repository_or_run_id_rejected(
    tmp_path: Path,
) -> None:
    run, jobs, artifacts, raw = _inputs(tmp_path)
    with pytest.raises(OriginalWorkerAttestationError, match="repository"):
        attest_original_worker_rank_artifact(
            run_json=run, jobs_json=jobs, artifacts_json=artifacts,
            expected_run_id=RUN, expected_run_attempt=1,
            expected_repository="../unsafe/", original_artifact_zip=raw,
        )


def test_source_audit_workflow_fetches_real_github_api_step_and_artifact_metadata() -> None:
    source = Path(
        ".github/workflows/original-short-rank-source-audit.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_run:" in source
    assert "types:\n      - completed" in source
    assert "actions: read" in source
    assert "gh api \"repos/$GITHUB_REPOSITORY/actions/runs/$SOURCE_RUN_ID\"" in source
    assert "jobs?per_page=100" in source
    assert "artifacts?per_page=100" in source
    assert "Authorization: Bearer $GH_TOKEN" in source
    assert "scripts/attest_paper_short_rank_artifact.py" in source
    assert 'source-run-attempt "$SOURCE_RUN_ATTEMPT"' in source
    assert "original-first-seen-short-rank-audit-" in source
    assert "cocomelon-continuous-paper" not in source
    assert "github_artifact_digest_and_step_metadata_checked" in source
