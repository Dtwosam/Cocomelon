"""Original v3 GitHub outer ZIP/run/manifest must precede any PAPER accounts."""
from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    SourceSegment,
)
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.fresh_long_trend_forward_pair import (
    FORWARD_NOT_BEFORE_MS,
)
from cocomelon.research.fresh_long_trend_github_origin import (
    OriginalV3GitHubSourceError,
    run_original_zip_bound_fresh_long_trend_paper,
    verify_original_v3_github_zip_source,
)

REPOSITORY = "Dtwosam/Cocomelon"
RUN_ID = 39234567890
HEAD = "a" * 40
FILE = "events/2026-10-16/l2_book/TEST/segment-000001.jsonl"
SOURCE_BYTES = b'{"source":"original-captured-book","test":true}\n'


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "recording"
    local = root / FILE
    local.parent.mkdir(parents=True)
    local.write_bytes(SOURCE_BYTES)
    at = FORWARD_NOT_BEFORE_MS + 1000
    segment = SourceSegment(
        relative_path=FILE,
        partition="events/2026-10-16/l2_book/TEST",
        sha256=hashlib.sha256(SOURCE_BYTES).hexdigest(),
        byte_count=len(SOURCE_BYTES),
        row_count=1,
        schema_version=1,
        first_available_at_ms=at,
        last_available_at_ms=at,
    )
    manifest = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=FORWARD_NOT_BEFORE_MS - 1000,
        end_ms=FORWARD_NOT_BEFORE_MS + 2000,
        segments=(segment,),
        gap_refs=(),
        code_revision=HEAD,
        config_digest="f" * 64,
        feature_version="v1",
        strategy_version="v1",
        risk_version="v1",
        execution_config_version="v1",
        fee_schedule_id="fees-v1",
        replay_engine_version="v1",
        dataset_manifest_id=None,
    )
    zip_path = tmp_path / "original-github-upload.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        from dataclasses import asdict

        archive.writestr(
            "replay-manifest.json",
            json.dumps({
                "manifest_id": manifest.manifest_id,
                "manifest": asdict(manifest),
            }),
        )
        archive.writestr("microstructure/" + FILE, SOURCE_BYTES)
    run = {
        "id": RUN_ID,
        "run_attempt": 1,
        "head_sha": HEAD,
        "path": ".github/workflows/continuous-paper.yml",
        "head_branch": "main",
        "head_repository": {"full_name": REPOSITORY},
        "status": "completed",
        "conclusion": "failure",
        "created_at": "2026-10-16T05:58:00Z",
    }
    jobs = {"jobs": [{
        "name": "paper",
        "run_id": RUN_ID,
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "steps": [
            {"name": "Run continuous paper trader", "conclusion": "success"},
            {
                "name": "Upload frozen v3 original microstructure source",
                "conclusion": "success",
            },
        ],
    }]}
    artifact = {
        "id": 12000000001,
        "name": f"continuous-paper-v3-microstructure-{RUN_ID}-1",
        "size_in_bytes": zip_path.stat().st_size,
        "expired": False,
        "digest": "sha256:" + hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "created_at": "2026-10-16T06:10:00Z",
        "workflow_run": {
            "id": RUN_ID,
            "head_sha": HEAD,
            "head_branch": "main",
        },
    }
    return {
        "source_zip": zip_path,
        "recording_root": root,
        "manifest": manifest,
        "expected_manifest_id": manifest.manifest_id,
        "run_metadata": run,
        "jobs_metadata": jobs,
        "artifact_metadata": artifact,
        "repository": REPOSITORY,
        "forward_not_before_ms": FORWARD_NOT_BEFORE_MS,
    }


def test_exact_original_zip_and_git_metadata_are_read_only_and_unpromotable(
    tmp_path: Path,
) -> None:
    kw = _fixture(tmp_path)
    source_zip = kw["source_zip"]
    assert isinstance(source_zip, Path)
    before = source_zip.read_bytes()
    receipt = verify_original_v3_github_zip_source(**kw)
    assert receipt["run_id"] == RUN_ID
    assert receipt["run_attempt"] == 1
    assert receipt["run_head_sha"] == HEAD
    assert receipt["manifest_id"] == kw["expected_manifest_id"]
    assert receipt["original_zip_bytes_match_supplied_github_digest"] is True
    for flag in (
        "independently_fetched_github_metadata_proven",
        "original_exchange_event_completeness_proven",
        "signed_cross_worker_handoff_proven",
        "net_after_cost_profitability_proven",
        "promotion_authority",
        "execution_authority",
    ):
        assert receipt[flag] is False
    assert source_zip.read_bytes() == before


@pytest.mark.parametrize("change", [
    "wrong_run_id", "wrong_attempt", "wrong_repo", "wrong_commit",
    "unfinished", "non_paper_workflow", "bad_artifact_name",
    "missing_digest", "missing_upload_step", "duplicate_upload_step",
    "artifact_wrong_run", "tampered_outer_zip", "tampered_local_segment",
    "wrong_manifest", "stale_artifact", "source_after_artifact",
])
def test_mutated_run_artifact_or_bytes_cannot_qualify(
    tmp_path: Path, change: str,
) -> None:
    kw = _fixture(tmp_path)
    run = kw["run_metadata"]
    artifact = kw["artifact_metadata"]
    jobs = kw["jobs_metadata"]
    assert isinstance(run, dict) and isinstance(artifact, dict)
    assert isinstance(jobs, dict)
    kw["run_metadata"] = copy.deepcopy(run)
    kw["jobs_metadata"] = copy.deepcopy(jobs)
    kw["artifact_metadata"] = copy.deepcopy(artifact)
    run = kw["run_metadata"]
    jobs = kw["jobs_metadata"]
    artifact = kw["artifact_metadata"]
    assert isinstance(run, dict) and isinstance(artifact, dict)
    assert isinstance(jobs, dict)
    job = jobs["jobs"][0]
    if change == "wrong_run_id":
        run["id"] = RUN_ID + 1
    elif change == "wrong_attempt":
        run["run_attempt"] = 2
    elif change == "wrong_repo":
        run["head_repository"]["full_name"] = "outsider/Cocomelon"
    elif change == "wrong_commit":
        run["head_sha"] = "b" * 40
    elif change == "unfinished":
        run["status"] = "in_progress"
    elif change == "non_paper_workflow":
        run["path"] = ".github/workflows/ci.yml"
    elif change == "bad_artifact_name":
        artifact["name"] += "-retrospectively-picked"
    elif change == "missing_digest":
        artifact["digest"] = None
    elif change == "missing_upload_step":
        job["steps"][1]["conclusion"] = "failure"
    elif change == "duplicate_upload_step":
        job["steps"].append(copy.deepcopy(job["steps"][1]))
    elif change == "artifact_wrong_run":
        artifact["workflow_run"]["id"] = RUN_ID - 1
    elif change == "tampered_outer_zip":
        source = kw["source_zip"]
        assert isinstance(source, Path)
        source.write_bytes(source.read_bytes() + b"extra original bytes")
        artifact["size_in_bytes"] += len(b"extra original bytes")
    elif change == "tampered_local_segment":
        local = kw["recording_root"]
        assert isinstance(local, Path)
        (local / FILE).write_bytes(b"forged future fill")
    elif change == "wrong_manifest":
        kw["expected_manifest_id"] = "f" * 24
    elif change == "stale_artifact":
        artifact["created_at"] = "2026-10-16T05:59:00Z"
    else:
        artifact["created_at"] = "2026-10-16T06:00:00Z"
    with pytest.raises(OriginalV3GitHubSourceError):
        verify_original_v3_github_zip_source(**kw)


def test_source_bound_runner_refuses_bad_metadata_before_account_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cocomelon.research import fresh_long_trend_forward_pair as local

    kw = _fixture(tmp_path)
    metadata = kw["artifact_metadata"]
    assert isinstance(metadata, dict)
    metadata["digest"] = "sha256:" + "0" * 64

    invoked = []

    def local_replay(**args: object) -> dict[str, object]:
        invoked.append(args)
        return {"promotion_authority": False, "execution_authority": False}

    monkeypatch.setattr(local, "run_digest_pinned_long_trend_matched_paper", local_replay)
    kw.pop("forward_not_before_ms")
    with pytest.raises(OriginalV3GitHubSourceError, match="ZIP SHA256 mismatch"):
        run_original_zip_bound_fresh_long_trend_paper(
            **kw,
            config=BaselineReplayConfig(),
            selected_markets=[MarketId("", "TEST")],
            account_root=tmp_path / "fresh-accounts",
        )
    assert invoked == []
    assert not (tmp_path / "fresh-accounts").exists()


def test_valid_wrapper_cannot_misstate_source_or_trade_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cocomelon.research import fresh_long_trend_forward_pair as local

    kw = _fixture(tmp_path)
    kw.pop("forward_not_before_ms")
    invoked: list[dict[str, object]] = []

    def local_replay(**args: object) -> dict[str, object]:
        invoked.append(args)
        return {"promotion_authority": True, "execution_authority": True}

    monkeypatch.setattr(local, "run_digest_pinned_long_trend_matched_paper", local_replay)
    result = run_original_zip_bound_fresh_long_trend_paper(
        **kw,
        config=BaselineReplayConfig(),
        selected_markets=[MarketId("", "TEST")],
        account_root=tmp_path / "fresh-accounts",
    )
    assert len(invoked) == 1
    assert result["offline_original_github_zip_source_crosscheck"][
        "original_zip_bytes_match_supplied_github_digest"
    ] is True
    assert result["original_exchange_feed_independently_authenticated"] is False
    assert result["promotion_authority"] is False
    assert result["execution_authority"] is False
