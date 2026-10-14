"""Independent v2 archive gate cannot launder broken v1 paper economics."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FROZEN_AT_MS_V2,
    TRIAL_ID_V2,
    both_side_trend_matched_shadow_v2_freeze,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    TREND_PAIR_FREEZE_FILE,
    TREND_PAIR_STATE_ROOT,
    TREND_PAIR_SUMMARY_FILE,
    TREND_V2_FREEZE_FILE,
    TREND_V2_STATE_ROOT,
    TREND_V2_SUMMARY_FILE,
)
from scripts import audit_both_side_trend_paired_handoff as audit

RUN = 40000000001
ATTEMPT = 1
REPO = "Dtwosam/Cocomelon"


def _source() -> tuple[dict[str, object], dict[str, object]]:
    run: dict[str, object] = {
        "id": RUN,
        "run_attempt": ATTEMPT,
        "name": "Continuous Paper · audit fixture",
        "path": ".github/workflows/continuous-paper.yml",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "status": "completed",
        "conclusion": "success",
        "run_started_at": "2026-10-14T00:00:01Z",
        "repository": {"full_name": REPO},
    }
    jobs: dict[str, object] = {
        "jobs": [{
            "run_id": RUN,
            "run_attempt": ATTEMPT,
            "name": "paper",
            "status": "completed",
            "conclusion": "success",
            "steps": [
                {"name": "Run continuous paper trader", "conclusion": "success"},
                {
                    "name": "Verify fresh v2 trend paired account consistency before source ZIP",
                    "conclusion": "success",
                },
                {
                    "name": audit.V2_SOURCE_UPLOAD_STEP,
                    "conclusion": "success",
                },
            ],
        }],
    }
    return run, jobs


def _artifact(
    tmp_path: Path,
    *, prefix: str = audit.V2_ARTIFACT_PREFIX,
    expiry: object = False,
    digest: str | None = None,
) -> tuple[Path, dict[str, object]]:
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("unrelated.txt", "source")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, {
        "artifacts": [{
            "name": f"{prefix}{RUN}-{ATTEMPT}",
            "id": 81234,
            "expired": expiry,
            "digest": digest or f"sha256:{sha}",
        }],
    }


def _failed_but_terminally_archived_v2() -> tuple[
    dict[str, object], dict[str, object],
]:
    run, jobs = _source()
    run["conclusion"] = "failure"
    job = jobs["jobs"][0]
    job["status"] = "completed"
    job["conclusion"] = "failure"
    job["steps"][0] = {
        "name": "Run continuous paper trader",
        "status": "completed",
        "conclusion": "failure",
    }
    job["steps"].extend({
        "name": name, "status": "completed", "conclusion": "success",
    } for name in (
        "Measure durable continuous paper state",
        "Pack fast continuous paper resume state",
        "Upload fast continuous paper resume state",
        "Queue exact successor from fast resume",
        "Pack durable continuous paper state",
        "Upload durable continuous paper state",
    ))
    job["steps"].append({
        "name": "Fail closed on upgrade handoff source",
        "status": "completed", "conclusion": "failure",
    })
    return run, jobs


def test_actual_failed_v2_trader_archived_terminal_accounts_are_auditable() -> None:
    # Observed first Oct 14 v2 worker 38506173767 has exactly these
    # two red steps, followed by successful post-exit custody and ZIP.
    run, jobs = _failed_but_terminally_archived_v2()
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO, run_id=RUN,
        attempt=ATTEMPT, campaign="v2",
    ) == "completed_terminal_archived_trader_failure_worker"
    # Legacy v1 source must never acquire this new exception.
    with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
        audit._source_class(
            run=run, jobs=jobs, repository=REPO, run_id=RUN,
            attempt=ATTEMPT, campaign="v1",
        )


@pytest.mark.parametrize("bad_step", [
    "Verify fresh v2 trend paired account consistency before source ZIP",
    audit.V2_SOURCE_UPLOAD_STEP,
    "Measure durable continuous paper state",
    "Pack fast continuous paper resume state",
    "Upload fast continuous paper resume state",
    "Queue exact successor from fast resume",
    "Pack durable continuous paper state",
    "Upload durable continuous paper state",
    "Fail closed on upgrade handoff source",
])
def test_failed_v2_trader_needs_every_exact_terminal_custody_step(
    bad_step: str,
) -> None:
    run, jobs = _failed_but_terminally_archived_v2()
    jobs["jobs"][0]["steps"] = [
        s for s in jobs["jobs"][0]["steps"] if s["name"] != bad_step
    ]
    with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
        audit._source_class(
            run=run, jobs=jobs, repository=REPO, run_id=RUN,
            attempt=ATTEMPT, campaign="v2",
        )


@pytest.mark.parametrize("defect", [
    "active_run", "cancelled_run", "uncompleted_job", "active_trader",
    "unexpected_failure", "wrong_trader_status", "wrong_job_conclusion",
    "wrong_attempt", "duplicate_paper_job",
])
def test_uncontrolled_v2_trader_failure_never_inherits_terminal_custody(
    defect: str,
) -> None:
    run, jobs = _failed_but_terminally_archived_v2()
    job = jobs["jobs"][0]
    if defect == "active_run":
        run["status"] = "in_progress"
        run["conclusion"] = None
    elif defect == "cancelled_run":
        run["conclusion"] = "cancelled"
    elif defect == "uncompleted_job":
        job["status"] = "in_progress"
    elif defect == "active_trader":
        job["steps"][0]["status"] = "in_progress"
    elif defect == "unexpected_failure":
        job["steps"].append({
            "name": "Unexpected account write failed",
            "status": "completed", "conclusion": "failure",
        })
    elif defect == "wrong_trader_status":
        job["steps"][0]["conclusion"] = "timed_out"
    elif defect == "wrong_job_conclusion":
        job["conclusion"] = "cancelled"
    elif defect == "wrong_attempt":
        job["run_attempt"] = ATTEMPT + 1
    elif defect == "duplicate_paper_job":
        jobs["jobs"].append(json.loads(json.dumps(job)))
    def classify() -> str:
        return audit._source_class(
            run=run, jobs=jobs, repository=REPO,
            run_id=RUN, attempt=ATTEMPT, campaign="v2",
        )
    if defect == "wrong_attempt":
        with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
            classify()
    elif defect == "duplicate_paper_job":
        with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
            classify()
    elif defect == "active_run":
        with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
            classify()
    else:
        with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
            classify()


def test_v2_source_class_requires_prospective_time_and_exact_upload() -> None:
    run, jobs = _source()
    assert audit._source_class(
        run=run, jobs=jobs, repository=REPO, run_id=RUN,
        attempt=ATTEMPT, campaign="v2",
    ) == "completed_successful_worker"
    assert FROZEN_AT_MS_V2 > 0
    assert TRIAL_ID_V2.endswith("shadow-v2")

    run["run_started_at"] = "2026-10-13T23:59:59Z"
    with pytest.raises(audit.TrendPairHandoffAuditError, match="before frozen"):
        audit._source_class(
            run=run, jobs=jobs, repository=REPO, run_id=RUN,
            attempt=ATTEMPT, campaign="v2",
        )
    run["run_started_at"] = "2026-10-14T00:00:01Z"

    steps = jobs["jobs"][0]["steps"]
    steps[2]["name"] = "Upload isolated both-side trend paired-paper evidence"
    with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
        audit._source_class(
            run=run, jobs=jobs, repository=REPO, run_id=RUN,
            attempt=ATTEMPT, campaign="v2",
        )


def test_v2_requires_source_terminal_step_even_when_upload_succeeded() -> None:
    run, jobs = _source()
    jobs["jobs"][0]["steps"].pop(1)
    with pytest.raises(audit.TrendPairHandoffAuditError, match="not both proven"):
        audit._source_class(
            run=run, jobs=jobs, repository=REPO, run_id=RUN,
            attempt=ATTEMPT, campaign="v2",
        )


def test_v2_artifact_authenticates_name_digest_id_and_expiry(
    tmp_path: Path,
) -> None:
    zip_path, artifacts = _artifact(tmp_path)
    got = audit._validate_artifact(
        artifacts, zip_path, run_id=RUN, attempt=ATTEMPT, campaign="v2",
    )
    assert got == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    artifacts["artifacts"][0]["id"] = None
    with pytest.raises(audit.TrendPairHandoffAuditError, match="identity"):
        audit._validate_artifact(
            artifacts, zip_path, run_id=RUN, attempt=ATTEMPT, campaign="v2",
        )
    zip_path, artifacts = _artifact(tmp_path, expiry=True)
    with pytest.raises(audit.TrendPairHandoffAuditError, match="expiry"):
        audit._validate_artifact(
            artifacts, zip_path, run_id=RUN, attempt=ATTEMPT, campaign="v2",
        )
    zip_path, artifacts = _artifact(tmp_path, digest="sha256:" + "a" * 64)
    with pytest.raises(audit.TrendPairHandoffAuditError, match="SHA256"):
        audit._validate_artifact(
            artifacts, zip_path, run_id=RUN, attempt=ATTEMPT, campaign="v2",
        )


def test_renaming_old_v1_zip_cannot_satisfy_frozen_v2_members(
    tmp_path: Path,
) -> None:
    z = tmp_path / "old-v1.zip"
    with zipfile.ZipFile(z, "w") as archive:
        archive.writestr(
            TREND_PAIR_FREEZE_FILE,
            json.dumps(both_side_trend_matched_shadow_v2_freeze().to_dict()),
        )
        archive.writestr(TREND_PAIR_SUMMARY_FILE, "{}")
        archive.writestr(
            f"{TREND_PAIR_STATE_ROOT}/paired-shadow-state.json", "{}",
        )
        archive.writestr(
            f"{TREND_PAIR_STATE_ROOT}/review-ledger.jsonl", "{}\n",
        )
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="missing or ambiguous",
    ):
        audit._extract_receipts(z, tmp_path, campaign="v2")


def test_wrong_v2_freeze_rejected_even_if_member_names_are_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not accept self-consistent old v1 identity under new filenames."""
    from cocomelon.research.prospective_both_side_trend_paired_freeze import (
        both_side_trend_matched_shadow_freeze,
    )

    z = tmp_path / "mismatched-v2.zip"
    with zipfile.ZipFile(z, "w") as archive:
        archive.writestr(
            TREND_V2_FREEZE_FILE,
            json.dumps(both_side_trend_matched_shadow_freeze().to_dict()),
        )
        archive.writestr(TREND_V2_SUMMARY_FILE, "{}")
        archive.writestr(
            f"{TREND_V2_STATE_ROOT}/paired-shadow-state.json", "{}",
        )
        archive.writestr(
            f"{TREND_V2_STATE_ROOT}/review-ledger.jsonl", "{}\n",
        )
    monkeypatch.setattr(audit, "_verify_archived_execution_store", lambda *a, **kw: None)
    with pytest.raises(
        audit.TrendPairHandoffAuditError, match="predeclared",
    ):
        audit._extract_receipts(z, tmp_path, campaign="v2")


def test_v2_missing_archive_never_gets_positive_status(tmp_path: Path) -> None:
    run, jobs = _source()
    _, artifacts = _artifact(tmp_path)
    receipt = audit.audit_trend_handoff(
        run=run, jobs=jobs, artifacts=artifacts,
        archive=tmp_path / "nonexistent.zip",
        repository=REPO, source_run_id=RUN, source_attempt=ATTEMPT,
        campaign="v2",
    )
    assert receipt["status"] == "unverified"
    assert receipt["source_v2_terminal_receipt_verified"] is False
    assert receipt["archived_execution_economics_reconciled"] is False
    assert receipt["full_forward_after_cost_profit_verified"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["execution_authority"] is False


def test_v2_independent_workflow_cannot_execute_or_claim_profit() -> None:
    workflow = Path(
        ".github/workflows/independent-fresh-trend-v2-source-audit.yml"
    ).read_text()
    assert "--campaign v2" in workflow
    assert "source.zip" in workflow
    assert "workflow_dispatch:" in workflow
    assert 'cron: "27 */3 * * *"' in workflow
    assert "full_forward_after_cost_profit_verified" not in workflow
    assert "UNVERIFIED / UNVERIFIED" in workflow
    assert "LIVE" not in workflow
    assert "COCOMELON_EXECUTION_MODE: live" not in workflow
    assert "HYPERLIQUID_PRIVATE_KEY" not in workflow
    assert "place_order" not in workflow


def test_matching_v2_archive_members_can_open_only_exact_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    z = tmp_path / "matched-v2.zip"
    freeze = both_side_trend_matched_shadow_v2_freeze()
    with zipfile.ZipFile(z, "w") as archive:
        archive.writestr(TREND_V2_FREEZE_FILE, json.dumps(freeze.to_dict()))
        archive.writestr(TREND_V2_SUMMARY_FILE, '{"trial_id": "v2"}')
        archive.writestr(
            f"{TREND_V2_STATE_ROOT}/paired-shadow-state.json",
            '{"schema_version": 2}',
        )
        archive.writestr(
            f"{TREND_V2_STATE_ROOT}/review-ledger.jsonl", "{}\n",
        )
    monkeypatch.setattr(audit, "_verify_archived_execution_store", lambda *a, **kw: None)
    frozen, summary, state, ledger = audit._extract_receipts(
        z, tmp_path, campaign="v2",
    )
    assert frozen["candidate_id"] == freeze.candidate_id
    assert summary["trial_id"] == "v2"
    assert state["schema_version"] == 2
    assert ledger.read_text() == "{}\n"
