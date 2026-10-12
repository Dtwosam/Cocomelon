"""Original GitHub source and account-handoff evidence never imply trading authority."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import audit_both_side_trend_paired_handoff as audit
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    TRIAL_ID,
    both_side_trend_matched_shadow_freeze,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    TREND_PAIR_FREEZE_FILE,
    TREND_PAIR_STATE_ROOT,
    TREND_PAIR_SUMMARY_FILE,
)

REPO = "Dtwosam/Cocomelon"
RUN = 456789
ATTEMPT = 1


def _source() -> tuple[dict[str, object], dict[str, object]]:
    run: dict[str, object] = {
        "id": RUN,
        "run_attempt": ATTEMPT,
        "name": "Continuous Mainnet Paper Trader",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": REPO},
    }
    jobs: dict[str, object] = {
        "jobs": [{
            "run_id": RUN, "run_attempt": ATTEMPT,
            "name": "paper",
            "steps": [
                {"name": "Run continuous paper trader", "conclusion": "success"},
                {
                    "name": "Upload isolated both-side trend paired-paper evidence",
                    "conclusion": "success",
                },
            ],
        }],
    }
    return run, jobs


def _artifact(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("unrelated.txt", "source")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    artifacts: dict[str, object] = {
        "artifacts": [{
            "name": f"continuous-paper-both-side-trend-paired-shadow-{RUN}-{ATTEMPT}",
            "id": 5678,
            "digest": f"sha256:{digest}",
            "expired": False,
        }],
    }
    return archive, artifacts


def _audit(tmp_path: Path) -> dict[str, object]:
    run, jobs = _source()
    archive, artifacts = _artifact(tmp_path)
    return audit.audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts,
        archive=archive, repository=REPO,
        source_run_id=RUN, source_attempt=ATTEMPT,
    )


def test_genuine_completed_worker_must_match_one_exact_attempt() -> None:
    run, jobs = _source()
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO,
        run_id=RUN, attempt=ATTEMPT,
    ) == "completed_successful_worker"
    run["conclusion"] = "failure"
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO,
        run_id=RUN, attempt=ATTEMPT,
    ) == "completed_non_success_worker"

    run["conclusion"] = "success"
    altered_jobs = json.loads(json.dumps(jobs))
    altered_jobs["jobs"][0]["run_attempt"] = ATTEMPT + 1
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="exact attempt",
    ):
        audit._source_class(
            run=run, jobs=altered_jobs, repository=REPO,
            run_id=RUN, attempt=ATTEMPT,
        )
    altered_jobs["jobs"][0]["run_attempt"] = ATTEMPT
    altered_jobs["jobs"][0]["steps"][1]["conclusion"] = "failure"
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="not both proven",
    ):
        audit._source_class(
            run=run, jobs=altered_jobs, repository=REPO,
            run_id=RUN, attempt=ATTEMPT,
        )


def test_exact_outer_zip_sha256_is_mandatory(tmp_path: Path) -> None:
    archive, metadata = _artifact(tmp_path)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert audit._validate_artifact(
        metadata, archive, run_id=RUN, attempt=ATTEMPT,
    ) == actual
    archive.write_bytes(archive.read_bytes() + b"tampering")
    with pytest.raises(audit.TrendPairHandoffAuditError, match="SHA256"):
        audit._validate_artifact(
            metadata, archive, run_id=RUN, attempt=ATTEMPT,
        )


def test_missing_trend_zip_is_explicitly_unverified(tmp_path: Path) -> None:
    receipt = _audit(tmp_path)
    assert receipt["status"] == "unverified"
    assert "paired" in str(receipt["reasons"])
    assert receipt["source_class"] == "completed_successful_worker"
    assert receipt["archive_sha256"] is not None
    assert receipt["execution_authority"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["durable_execution_sqlite_replay_verified"] is False
    assert receipt["full_forward_after_cost_profit_verified"] is False


def test_archive_reader_requires_explicit_exact_paths_and_both_stores(
    tmp_path: Path,
) -> None:
    freeze = both_side_trend_matched_shadow_freeze()
    zip_path = tmp_path / "trend.zip"
    with zipfile.ZipFile(zip_path, "w") as zipped:
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_FREEZE_FILE}",
            json.dumps(freeze.to_dict()),
        )
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_SUMMARY_FILE}",
            json.dumps({"checkpoint_published": False}),
        )
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_STATE_ROOT}/paired-shadow-state.json",
            json.dumps({"schema_version": 2}),
        )
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_STATE_ROOT}/review-ledger.jsonl",
            "{}\n",
        )
        zipped.writestr(
            f"continuous-paper-state/{TREND_PAIR_STATE_ROOT}/baseline-execution.sqlite3",
            b"sqlite",
        )
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="candidate execution store",
    ):
        audit._extract_receipts(zip_path, tmp_path)


def test_consistent_receipts_only_verify_archive_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, jobs = _source()
    archive, artifacts = _artifact(tmp_path)
    freeze = both_side_trend_matched_shadow_freeze()
    state: dict[str, object] = {
        "portfolio_shadow_candidate_id": freeze.candidate_id,
        "review_ledger_row_count": 1,
        "review_ledger_latest_row_digest": "f" * 64,
        "promotion_authority": False,
        "execution_authority": False,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
    }
    state["state_digest"] = audit._signed_digest(state)
    summary: dict[str, object] = {
        "trial_id": TRIAL_ID,
        "frozen_forward_not_before_ms": freeze.prospective_not_before_ms,
        "checkpoint_published": True,
        "checkpoint_error": None,
        "checkpoint": state,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
        "promotion_authority": False,
        "execution_authority": False,
        "forward_profitable_signed_account_edge_proven": False,
        "original_mainnet_source_and_gaps_independently_authenticated": False,
    }
    monkeypatch.setattr(
        audit, "_extract_receipts",
        lambda _zip, _tmp: (
            freeze.to_dict(), summary, state, tmp_path / "ledger.jsonl",
        ),
    )
    monkeypatch.setattr(
        audit, "review_ledger_receipt",
        lambda *_args, **_kwargs: {
            "row_count": 1, "latest_row_digest": "f" * 64,
        },
    )
    monkeypatch.setattr(
        audit, "build_paired_shadow_review",
        lambda *_args: {"ready_for_review": False},
    )
    receipt = audit.audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts,
        archive=archive, repository=REPO,
        source_run_id=RUN, source_attempt=ATTEMPT,
    )
    assert receipt["status"] == "archive_checkpoint_lineage_verified"
    assert receipt["verified_checkpoint_count"] == 1
    assert receipt["reasons"] == ["economic_review_not_ready"]
    assert receipt["durable_execution_sqlite_replay_verified"] is False
    assert receipt["full_forward_after_cost_profit_verified"] is False
    assert receipt["independent_mainnet_market_source_authenticated"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["execution_authority"] is False

    state["state_digest"] = "0" * 64
    corrupted = audit.audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts,
        archive=archive, repository=REPO,
        source_run_id=RUN, source_attempt=ATTEMPT,
    )
    assert corrupted["status"] == "unverified"
    assert "digest mismatch" in str(corrupted["reasons"])


def test_independent_audit_workflow_can_never_place_orders() -> None:
    workflow = Path(
        ".github/workflows/independent-both-side-trend-handoff-audit.yml"
    ).read_text()
    assert "workflow_run:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "Continuous Mainnet Paper Trader" in workflow
    assert "head_branch == 'main'" in workflow
    assert "  actions: read" in workflow
    assert "  contents: read" in workflow
    assert "actions: write" not in workflow
    assert "issues: write" not in workflow
    assert "gh workflow run" not in workflow
    assert "gh_api_bounded_retry" in workflow
    assert "--artifact-zip /tmp/trend-paper-audit/source.zip" in workflow
    assert "audit_both_side_trend_paired_handoff.py" in workflow
    assert "original market feed gaps independently authenticated: FALSE" in workflow
    assert "live execution / promotion authority: FALSE / FALSE" in workflow
