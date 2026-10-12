from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from scripts.attest_paper_short_rank_artifact import (
    REQUIRED_SUCCESSFUL_PAPER_STEPS,
)
from scripts.audit_paper_short_rank_handoff import (
    audit_completed_original_rank_handoff,
)
from scripts.seal_paper_short_rank_archive import (
    ARCHIVE_NAME,
    RECEIPT_NAME,
    seal_completed_short_rank_archive,
)

PREDECESSOR_ID = 38162541394
SUCCESSOR_ID = 38166151613
REPO = "Dtwosam/Cocomelon"
FIRST = 1_790_000_000_000


def _snapshot(at_ms: int, market: str, score: str = "0.7") -> FirstSeenRankSnapshot:
    return FirstSeenRankSnapshot(
        observed_at_ms=at_ms,
        captured_at_ms=at_ms + 100,
        features=((market, f"feature-{market}-{at_ms}", at_ms - 200),),
        ranks=((market, 1, score, ("source-fixture",)),),
    )


def _side(
    root: Path,
    *,
    run_id: int,
    head: str,
    rows: tuple[FirstSeenRankSnapshot, ...],
    restored_from_id: int | None = None,
    restored_from_attempt: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]:
    state = root / "state"
    out = root / "published"
    archive = FirstSeenRankSnapshotStore(
        state / "prospective-short-rank-first-seen"
    )
    for row in rows:
        archive.append(row)
    seal = seal_completed_short_rank_archive(
        state, out, worker_run_id=run_id, worker_run_attempt=1,
        worker_head_sha=head, restored_from_run_id=restored_from_id,
        restored_from_run_attempt=restored_from_attempt,
        sealed_at_ms=FIRST + 20_000,
    )
    assert seal["rank_source_status"] == "locally_sealed"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_STORED) as outer:
        outer.writestr(RECEIPT_NAME, (out / RECEIPT_NAME).read_bytes())
        outer.writestr(ARCHIVE_NAME, (out / ARCHIVE_NAME).read_bytes())
    data = zip_buffer.getvalue()
    title_run = restored_from_id or run_id
    run: dict[str, Any] = {
        "id": run_id, "status": "completed", "conclusion": "success",
        "head_branch": "main", "path": ".github/workflows/continuous-paper.yml",
        "event": "workflow_dispatch", "run_attempt": 1, "head_sha": head,
        "display_title": f"Continuous Paper · {title_run}",
        "created_at": (
            "2026-10-11T18:08:14Z"
            if run_id == PREDECESSOR_ID else "2026-10-11T19:00:02Z"
        ),
        "repository": {"full_name": REPO},
        "head_repository": {"full_name": REPO},
    }
    jobs: dict[str, Any] = {
        "jobs": [{
            "name": "paper", "run_attempt": 1,
            "status": "completed", "conclusion": "success",
            "steps": [
                {"name": name, "conclusion": "success"}
                for name in REQUIRED_SUCCESSFUL_PAPER_STEPS
            ],
        }],
    }
    artifacts: dict[str, Any] = {
        "artifacts": [{
            "id": run_id + 200,
            "name": f"continuous-paper-first-seen-short-rank-{run_id}-1",
            "size_in_bytes": len(data),
            "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
            "expired": False,
            "workflow_run": {"id": run_id, "head_sha": head},
        }],
    }
    return run, jobs, artifacts, data


def _both(
    tmp_path: Path, *, edited_prefix: bool = False,
) -> tuple[
    tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes],
    tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes],
]:
    history = (
        _snapshot(FIRST, "BTC"),
        _snapshot(FIRST + 1_000, "ETH"),
    )
    new_history = (
        (
            _snapshot(FIRST, "BTC", score="0.8"),
            history[1],
        ) if edited_prefix else history
    )
    first = _side(
        tmp_path / "original", run_id=PREDECESSOR_ID,
        head="a" * 40, rows=history,
    )
    second = _side(
        tmp_path / "successor", run_id=SUCCESSOR_ID,
        head="b" * 40,
        rows=new_history + (_snapshot(FIRST + 2_000, "SOL"),),
        restored_from_id=PREDECESSOR_ID,
        restored_from_attempt=1,
    )
    return first, second


def _audit(
    prior: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes],
    successor: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes],
) -> dict[str, object]:
    return audit_completed_original_rank_handoff(
        source_run_id=SUCCESSOR_ID,
        source_run_attempt=1,
        source_run_json=successor[0],
        source_jobs_json=successor[1],
        source_artifacts_json=successor[2],
        source_artifact_zip=successor[3],
        predecessor_run_json=prior[0],
        predecessor_jobs_json=prior[1],
        predecessor_artifacts_json=prior[2],
        predecessor_artifact_zip=prior[3],
        expected_repository=REPO,
    )


def test_real_github_source_and_predecessor_sha_bind_complete_original_prefix(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path)
    proof = _audit(prior, successor)
    assert proof["rank_handoff_status"] == "github_api_bound_immutable_prefix"
    assert proof["both_github_original_rank_artifacts_verified"] is True
    assert proof["original_rank_history_exact_prefix_reconciled"] is True
    assert proof["original_predecessor_snapshot_count"] == 2
    assert proof["original_successor_snapshot_count"] == 3
    assert proof["new_complete_rank_snapshots"] == 1
    assert proof["predecessor_worker_run_id_claimed"] == PREDECESSOR_ID
    assert proof["source_worker_run_id_claimed"] == SUCCESSOR_ID
    assert proof["full_account_trial"] is False
    assert proof["ready_for_review"] is False
    assert proof["source_market_gaps_and_feature_lineage_authenticated"] is False
    assert proof["risk_matched_account_economics_mature"] is False
    assert proof["promotion_authority"] is False
    assert proof["execution_authority"] is False


def test_valid_separately_sealed_mutated_rank_prefix_fails_cross_worker_check(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path, edited_prefix=True)
    proof = _audit(prior, successor)
    assert proof["failure_reason_code"] == (
        "original_rank_handoff_provenance_or_prefix_invalid"
    )
    assert proof["rank_handoff_status"] == "unverified"
    assert proof["original_rank_history_exact_prefix_reconciled"] is False


def test_missing_original_predecessor_artifact_never_receives_positive_receipt(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path)
    bad = audit_completed_original_rank_handoff(
        source_run_id=SUCCESSOR_ID,
        source_run_attempt=1,
        source_run_json=successor[0],
        source_jobs_json=successor[1],
        source_artifacts_json=successor[2],
        source_artifact_zip=successor[3],
        predecessor_run_json=prior[0],
        predecessor_jobs_json=prior[1],
        predecessor_artifacts_json=prior[2],
        predecessor_artifact_zip=None,
        expected_repository=REPO,
    )
    assert bad["failure_reason_code"] == (
        "exact_predecessor_source_or_artifact_missing"
    )
    assert bad["ready_for_review"] is False


def test_failed_original_trader_step_and_wrong_head_never_pass(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path)
    bad_steps = {
        "jobs": [{
            "name": "paper",
            "steps": [
                {
                    "name": name,
                    "conclusion": (
                        "failure" if name == "Run continuous paper trader"
                        else "success"
                    ),
                }
                for name in REQUIRED_SUCCESSFUL_PAPER_STEPS
            ],
        }],
    }
    proof = _audit(prior, (
        successor[0], bad_steps, successor[2], successor[3],
    ))
    assert proof["failure_reason_code"] == "successor_rank_source_unverified"
    wrong_head = {
        **prior[0], "head_sha": "f" * 40,
    }
    proof = _audit((
        wrong_head, prior[1], prior[2], prior[3],
    ), successor)
    assert proof["failure_reason_code"] == "predecessor_rank_source_unverified"


def test_wrong_successor_dispatch_title_and_attempt_fail_closed(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path)
    wrong_title = {**successor[0], "display_title": "Continuous Paper · 9"}
    result = _audit(prior, (
        wrong_title, successor[1], successor[2], successor[3],
    ))
    assert result["rank_handoff_status"] == "unverified"
    assert result["failure_reason_code"] == (
        "original_rank_handoff_provenance_or_prefix_invalid"
    )
    changed_attempt = {**successor[0], "run_attempt": 2}
    result = _audit(prior, (
        changed_attempt, successor[1], successor[2], successor[3],
    ))
    assert result["failure_reason_code"] == "successor_rank_source_unverified"


def test_completed_worker_audit_workflow_publishes_separate_chain_proof() -> None:
    workflow = Path(
        ".github/workflows/original-short-rank-source-audit.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_run:" in workflow
    assert "types:\n      - completed" in workflow
    assert "actions: read" in workflow
    assert "permissions:\n  actions: read\n  contents: read" in workflow
    assert "/tmp/original-short-rank-predecessor/run.json" in workflow
    assert (
        "gh_api_bounded_retry \"repos/$GITHUB_REPOSITORY/actions/runs/"
        "$PREDECESSOR_RUN_ID\""
    ) in workflow
    assert "jq -r '.display_title // \"\"'" in workflow
    assert "python -m scripts.audit_paper_short_rank_handoff" in workflow
    assert "python scripts/audit_paper_short_rank_handoff.py" not in workflow
    assert "original-first-seen-short-rank-handoff-audit-" in workflow
    assert "first-seen-short-rank-handoff-audit.json" in workflow
    assert "continuous-paper-trader --" not in workflow



def _upgrade_source(
    item: tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]:
    run, jobs, artifacts, raw = item
    original_paper = jobs["jobs"][0]
    return (
        {**run, "conclusion": "failure"},
        {"jobs": [{
            **original_paper,
            "conclusion": "failure",
            "steps": [
                *original_paper["steps"],
                {
                    "name": "Upload durable continuous paper state",
                    "conclusion": "success",
                },
                {
                    "name": "Fail closed on upgrade handoff source",
                    "conclusion": "failure",
                },
            ],
        }]},
        artifacts,
        raw,
    )


def test_real_upgrade_predecessor_is_rank_integrity_only_not_economic_success(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path)
    result = _audit(_upgrade_source(prior), successor)
    assert result["rank_handoff_status"] == (
        "github_api_bound_upgrade_handoff_prefix_only"
    )
    assert result["predecessor_worker_run_source_class"] == "upgrade_handoff_only"
    assert result["successor_worker_run_source_class"] == "successful_research_run"
    assert result["source_chain_contains_upgrade_only_worker"] is True
    assert result["chain_is_successful_research_source"] is False
    assert result["both_github_original_rank_artifacts_verified"] is True
    assert result["original_rank_history_exact_prefix_reconciled"] is True
    assert result["full_account_trial"] is False
    assert result["ready_for_review"] is False
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_upgrade_successor_is_also_not_solo_clean_economic_research(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path)
    result = _audit(prior, _upgrade_source(successor))
    assert result["source_chain_contains_upgrade_only_worker"] is True
    assert result["chain_is_successful_research_source"] is False
    assert result["successor_worker_run_source_class"] == "upgrade_handoff_only"


def test_unexpected_failed_predecessor_rejected_even_with_intact_archive(
    tmp_path: Path,
) -> None:
    prior, successor = _both(tmp_path)
    run, jobs, artifacts, raw = _upgrade_source(prior)
    paper = jobs["jobs"][0]
    forged = {
        "jobs": [{
            **paper,
            "steps": [
                *paper["steps"],
                {"name": "Unexpected data consistency failure",
                 "conclusion": "failure"},
            ],
        }],
    }
    result = _audit((run, forged, artifacts, raw), successor)
    assert result["rank_handoff_status"] == "unverified"
    assert result["failure_reason_code"] == "predecessor_rank_source_unverified"
    assert result["ready_for_review"] is False


def test_real_audit_module_startup_can_publish_immutable_negative_receipt(
    tmp_path: Path,
) -> None:
    """Regression: actual CI job previously failed before audit due to
    'ModuleNotFoundError: No module named scripts' on script-path invocation.
    """
    receipt = tmp_path / "rank-source-unverified.json"
    command = [
        sys.executable,
        "-m",
        "scripts.audit_paper_short_rank_handoff",
        "--source-run-id",
        str(SUCCESSOR_ID),
        "--source-run-attempt",
        "1",
        "--repository",
        REPO,
        "--source-dir",
        str(tmp_path / "missing-successor"),
        "--predecessor-dir",
        str(tmp_path / "missing-predecessor"),
        "--output",
        str(receipt),
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["rank_handoff_status"] == "unverified"
    assert payload["failure_reason_code"] == (
        "exact_predecessor_source_or_artifact_missing"
    )
    assert payload["both_github_original_rank_artifacts_verified"] is False
    assert payload["original_rank_history_exact_prefix_reconciled"] is False
    assert payload["ready_for_review"] is False
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert json.loads(result.stdout.strip()) == payload


def test_handoff_cli_corrupt_predecessor_metadata_is_durable_unverified(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    predecessor = tmp_path / "predecessor"
    source.mkdir()
    predecessor.mkdir()
    (predecessor / "run.json").write_bytes(b"\\xff\\xfe")
    receipt = tmp_path / "handoff-invalid-source.json"
    result = subprocess.run([
        sys.executable, "-m", "scripts.audit_paper_short_rank_handoff",
        "--source-run-id", str(SUCCESSOR_ID),
        "--source-run-attempt", "1",
        "--repository", REPO,
        "--source-dir", str(source),
        "--predecessor-dir", str(predecessor),
        "--output", str(receipt),
    ], check=False, capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stderr
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert json.loads(result.stdout.strip()) == payload
    assert payload["rank_handoff_status"] == "unverified"
    assert payload["failure_reason_code"] == (
        "exact_predecessor_source_or_artifact_missing"
    )
    assert payload["ready_for_review"] is False
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
