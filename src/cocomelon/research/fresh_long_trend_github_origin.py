"""Strict, OFFLINE original GitHub ZIP/manifest/worker-identity cross-check.

Inputs called "GitHub metadata" are independently fetched API JSON supplied
by a separate controller. Their mere shape does NOT cryptographically attest
GitHub or the Hyperliquid venue. This check is never trading authority.
"""
from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayManifest
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import DecisionEpochEngine

MAX_ORIGINAL_ZIP_BYTES = 512 * 1024 * 1024
MAX_SINGLE_SEGMENT_BYTES = 128 * 1024 * 1024
ZIP_MANIFEST = "replay-manifest.json"
SOURCE_HANDOFF = "source-handoff-receipt.json"
SOURCE_PREFIX = "microstructure/"
WORKFLOW_PATH = ".github/workflows/continuous-paper.yml"
REQUIRED_UPLOAD_STEP = "Upload frozen v3 original microstructure source"
REQUIRED_TRADER_STEP = "Run continuous paper trader"
ARTIFACT_PREFIX = "continuous-paper-v3-microstructure"


class OriginalV3GitHubSourceError(ValueError):
    """Insufficient independent source/worker origin or original ZIP parity."""


def _map(raw: object, name: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or any(not isinstance(k, str) for k in raw):
        raise OriginalV3GitHubSourceError(f"{name} must be an object")
    return cast(dict[str, Any], raw)


def _integer(raw: object, name: str) -> int:
    if type(raw) is not int or raw <= 0:
        raise OriginalV3GitHubSourceError(f"{name} invalid integer")
    return raw


def _sha(raw: object, name: str, *, length: int = 64) -> str:
    if (
        not isinstance(raw, str) or len(raw) != length
        or any(c not in "0123456789abcdef" for c in raw)
    ):
        raise OriginalV3GitHubSourceError(f"{name} is not exact lowercase hex")
    return raw


def _time(raw: object, name: str) -> int:
    if not isinstance(raw, str):
        raise OriginalV3GitHubSourceError(f"{name} not an ISO timestamp")
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OriginalV3GitHubSourceError(f"{name} malformed timestamp") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise OriginalV3GitHubSourceError(f"{name} not timezone-aware")
    return int(stamp.astimezone(UTC).timestamp() * 1000)


def _actual_zip_digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            sha.update(block)
    return sha.hexdigest()


def verify_original_v3_github_zip_source(
    *,
    source_zip: Path,
    recording_root: Path,
    manifest: ReplayManifest,
    expected_manifest_id: str,
    run_metadata: dict[str, object],
    jobs_metadata: dict[str, object],
    artifact_metadata: dict[str, object],
    repository: str,
    forward_not_before_ms: int,
) -> dict[str, object]:
    """Bind one unmodified original ZIP to one exact completed PAPER job.

    Verify original ZIP outer bytes first, then manifest/segment bytes
    against the exact independently pinned manifest and locally available
    recorder files. Never extract ZIP paths or follow archive-supplied names.
    """
    if not repository or repository != "Dtwosam/Cocomelon":
        raise OriginalV3GitHubSourceError("source repository must be canonical")
    if (
        type(forward_not_before_ms) is not int
        or forward_not_before_ms <= 0
        or manifest.manifest_id != expected_manifest_id
        or len(expected_manifest_id) != 24
        or any(c not in "0123456789abcdef" for c in expected_manifest_id)
    ):
        raise OriginalV3GitHubSourceError("source manifest independent pin invalid")
    run = _map(run_metadata, "GitHub workflow run")
    jobs = _map(jobs_metadata, "GitHub workflow jobs")
    artifact = _map(artifact_metadata, "GitHub original artifact")
    run_id = _integer(run.get("id"), "run ID")
    attempt = _integer(run.get("run_attempt"), "run attempt")
    head = _sha(run.get("head_sha"), "run head SHA", length=40)
    if (
        run.get("path") != WORKFLOW_PATH
        or run.get("head_branch") != "main"
        or _map(run.get("head_repository"), "head repository").get("full_name")
        != repository
        or run.get("status") != "completed"
        or run.get("conclusion") not in {"success", "failure"}
    ):
        raise OriginalV3GitHubSourceError("run identity not final main PAPER")
    run_started = _time(run.get("created_at"), "run created_at")
    name = f"{ARTIFACT_PREFIX}-{run_id}-{attempt}"
    if (
        _integer(artifact.get("id"), "artifact ID") <= 0
        or artifact.get("name") != name
        or artifact.get("expired") is not False
        or type(artifact.get("size_in_bytes")) is not int
        or not 0 < artifact["size_in_bytes"] <= MAX_ORIGINAL_ZIP_BYTES
    ):
        raise OriginalV3GitHubSourceError("exact original v3 artifact unavailable")
    audit_meta = _map(artifact.get("workflow_run"), "artifact workflow-run binding")
    if (
        audit_meta.get("id") != run_id
        or audit_meta.get("head_sha") != head
        or audit_meta.get("head_branch") != "main"
    ):
        raise OriginalV3GitHubSourceError("artifact attributed to another worker")
    original_uploaded_ms = _time(artifact.get("created_at"), "artifact created_at")
    if (
        original_uploaded_ms < run_started
        or original_uploaded_ms <= forward_not_before_ms
        or manifest.end_ms > original_uploaded_ms
    ):
        raise OriginalV3GitHubSourceError(
            "artifact chronology cannot contain qualifying future original source"
        )
    if (
        source_zip.is_symlink() or not source_zip.is_file()
        or source_zip.stat().st_size != artifact["size_in_bytes"]
    ):
        raise OriginalV3GitHubSourceError("original ZIP missing or size mismatch")
    published = artifact.get("digest")
    if not isinstance(published, str) or not published.startswith("sha256:"):
        raise OriginalV3GitHubSourceError("GitHub ZIP digest absent")
    expected_zip_sha = _sha(published[7:], "GitHub artifact ZIP SHA256")
    actual_zip_sha = _actual_zip_digest(source_zip)
    if actual_zip_sha != expected_zip_sha:
        raise OriginalV3GitHubSourceError("original GitHub ZIP SHA256 mismatch")

    candidate_jobs = jobs.get("jobs")
    if not isinstance(candidate_jobs, list):
        raise OriginalV3GitHubSourceError("GitHub job list missing")
    paper_jobs = [
        _map(job, "paper job") for job in candidate_jobs
        if isinstance(job, dict) and job.get("name") == "paper"
    ]
    if len(paper_jobs) != 1:
        raise OriginalV3GitHubSourceError("exact worker paper job not unique")
    paper = paper_jobs[0]
    if (
        paper.get("run_id") != run_id
        or paper.get("run_attempt") != attempt
        or paper.get("status") != "completed"
        or paper.get("conclusion") not in {"success", "failure"}
    ):
        raise OriginalV3GitHubSourceError("paper job not exact completed worker")
    steps = paper.get("steps")
    if not isinstance(steps, list):
        raise OriginalV3GitHubSourceError("paper job steps unavailable")
    step_values: dict[str, object] = {}
    for raw in steps:
        step = _map(raw, "job step")
        title = step.get("name")
        if not isinstance(title, str) or title in step_values:
            raise OriginalV3GitHubSourceError("duplicate or invalid job step")
        step_values[title] = step.get("conclusion")
    if (
        step_values.get(REQUIRED_TRADER_STEP) != "success"
        or step_values.get(REQUIRED_UPLOAD_STEP) != "success"
    ):
        raise OriginalV3GitHubSourceError("genuine trader/source upload not complete")

    if not recording_root.is_dir() or recording_root.is_symlink():
        raise OriginalV3GitHubSourceError("original recorder source root invalid")
    allowed = {ZIP_MANIFEST, SOURCE_HANDOFF}
    allowed.update(SOURCE_PREFIX + seg.relative_path for seg in manifest.segments)
    total_unpacked = 0
    try:
        with zipfile.ZipFile(source_zip) as z:
            members = z.infolist()
            if (
                len(members) != len(allowed)
                or {entry.filename for entry in members} != allowed
                or len({entry.filename for entry in members}) != len(members)
            ):
                raise OriginalV3GitHubSourceError(
                    "original ZIP members not the exact pinned segments"
                )
            for entry in members:
                mode = (entry.external_attr >> 16) & 0o170000
                if (
                    entry.is_dir()
                    or mode == stat.S_IFLNK
                    or entry.file_size > MAX_SINGLE_SEGMENT_BYTES
                ):
                    raise OriginalV3GitHubSourceError(
                        "ZIP contains unsafe or oversized source members"
                    )
                total_unpacked += entry.file_size
                if total_unpacked > MAX_ORIGINAL_ZIP_BYTES:
                    raise OriginalV3GitHubSourceError(
                        "ZIP expanded recording exceeds bound"
                    )
            manifest_bytes = z.read(ZIP_MANIFEST)
            try:
                archived_manifest: object = json.loads(manifest_bytes)
            except (UnicodeError, ValueError) as exc:
                raise OriginalV3GitHubSourceError(
                    "ZIP original manifest is invalid JSON"
                ) from exc
            required_manifest = json.loads(json.dumps({
                "manifest_id": manifest.manifest_id,
                "manifest": asdict(manifest),
            }, sort_keys=True, separators=(",", ":"), allow_nan=False))
            if archived_manifest != required_manifest:
                raise OriginalV3GitHubSourceError(
                    "ZIP original manifest differs from independently pinned value"
                )
            try:
                source_link: object = json.loads(z.read(SOURCE_HANDOFF))
            except (UnicodeError, ValueError) as exc:
                raise OriginalV3GitHubSourceError(
                    "original source handoff receipt invalid"
                ) from exc
            handoff = _map(source_link, "original source handoff")
            predecessor_id = handoff.get("declared_predecessor_run_id")
            predecessor_attempt = handoff.get(
                "declared_predecessor_run_attempt"
            )
            original_markets = handoff.get(
                "original_selected_markets_at_worker_start"
            )
            if (
                set(handoff) != {
                    "schema", "worker_run_id", "worker_run_attempt",
                    "worker_head_sha", "declared_predecessor_run_id",
                    "declared_predecessor_run_attempt",
                    "original_journal_sha256", "original_record_count",
                    "original_first_available_at_ms",
                    "original_last_available_at_ms",
                    "original_selected_markets_at_worker_start",
                    "original_resume_chain_independently_verified",
                    "original_exchange_feed_continuity_verified",
                    "research_only", "execution_authority",
                    "promotion_authority",
                }
                or handoff["schema"]
                != "v3-original-paper-source-worker-link-v1"
                or handoff["worker_run_id"] != str(run_id)
                or handoff["worker_run_attempt"] != str(attempt)
                or handoff["worker_head_sha"] != head
                or handoff["original_record_count"]
                != sum(seg.row_count for seg in manifest.segments)
                or handoff["original_first_available_at_ms"] != manifest.start_ms
                or handoff["original_last_available_at_ms"] != manifest.end_ms
                or not isinstance(original_markets, list)
                or not original_markets
                or not all(isinstance(m, str) and m for m in original_markets)
                or original_markets != sorted(set(original_markets))
                or (predecessor_id is None) != (predecessor_attempt is None)
                or handoff["original_resume_chain_independently_verified"]
                is not False
                or handoff["original_exchange_feed_continuity_verified"]
                is not False
                or handoff["research_only"] is not True
                or handoff["execution_authority"] is not False
                or handoff["promotion_authority"] is not False
            ):
                raise OriginalV3GitHubSourceError(
                    "original source handoff identity or continuity claim invalid"
                )
            _sha(handoff.get("original_journal_sha256"), "original journal SHA")
            if predecessor_id is not None and (
                type(predecessor_id) is not str
                or not predecessor_id.isdecimal()
                or int(predecessor_id) <= 0
                or predecessor_id == str(run_id)
                or type(predecessor_attempt) is not str
                or not predecessor_attempt.isdecimal()
                or int(predecessor_attempt) <= 0
            ):
                raise OriginalV3GitHubSourceError(
                    "original source predecessor hint invalid"
                )
            for segment in manifest.segments:
                file = recording_root / segment.relative_path
                if not file.is_file() or file.is_symlink():
                    raise OriginalV3GitHubSourceError(
                        "local original recording segment absent"
                    )
                if file.stat().st_size != segment.byte_count:
                    raise OriginalV3GitHubSourceError(
                        "local recording segment size drift"
                    )
                sha_local = hashlib.sha256()
                sha_zip = hashlib.sha256()
                with file.open("rb") as local, z.open(
                    SOURCE_PREFIX + segment.relative_path
                ) as entry_file:
                    while block := local.read(1024 * 1024):
                        sha_local.update(block)
                    while block := entry_file.read(1024 * 1024):
                        sha_zip.update(block)
                if (
                    sha_local.hexdigest() != segment.sha256
                    or sha_zip.hexdigest() != segment.sha256
                ):
                    raise OriginalV3GitHubSourceError(
                        "original ZIP/local/manifest segment SHA mismatch"
                    )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise OriginalV3GitHubSourceError(
            "cannot read immutable original source ZIP"
        ) from exc
    return {
        "schema": "v3-original-github-zip-run-segment-crosscheck-v1",
        "run_id": run_id,
        "run_attempt": attempt,
        "run_head_sha": head,
        "original_artifact_id": artifact["id"],
        "original_zip_sha256": actual_zip_sha,
        "manifest_id": manifest.manifest_id,
        "original_segment_count": len(manifest.segments),
        "declared_predecessor_run_id": predecessor_id,
        "declared_predecessor_run_attempt": predecessor_attempt,
        "original_worker_link_receipt_matches_run": True,
        "source_records_not_changed_by_audit": True,
        "original_zip_bytes_match_supplied_github_digest": True,
        "supplied_github_run_job_artifact_identity_crosschecked": True,
        "independently_fetched_github_metadata_proven": False,
        "original_exchange_event_completeness_proven": False,
        "signed_cross_worker_handoff_proven": False,
        "net_after_cost_profitability_proven": False,
        "research_only": True,
        "paper_only": True,
        "promotion_authority": False,
        "execution_authority": False,
    }


def run_original_zip_bound_fresh_long_trend_paper(
    *,
    source_zip: Path,
    recording_root: Path,
    manifest: ReplayManifest,
    expected_manifest_id: str,
    run_metadata: dict[str, object],
    jobs_metadata: dict[str, object],
    artifact_metadata: dict[str, object],
    repository: str,
    config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    account_root: Path,
    decision_engine_factory: Callable[[], DecisionEpochEngine] | None = None,
) -> dict[str, object]:
    """Require the original ZIP/worker source preflight BEFORE new accounts."""
    from cocomelon.research.fresh_long_trend_forward_pair import (
        FORWARD_NOT_BEFORE_MS,
        run_digest_pinned_long_trend_matched_paper,
    )

    receipt = verify_original_v3_github_zip_source(
        source_zip=source_zip,
        recording_root=recording_root,
        manifest=manifest,
        expected_manifest_id=expected_manifest_id,
        run_metadata=run_metadata,
        jobs_metadata=jobs_metadata,
        artifact_metadata=artifact_metadata,
        repository=repository,
        forward_not_before_ms=FORWARD_NOT_BEFORE_MS,
    )
    outcome = run_digest_pinned_long_trend_matched_paper(
        source_root=recording_root,
        manifest=manifest,
        expected_manifest_id=expected_manifest_id,
        config=config,
        selected_markets=selected_markets,
        account_root=account_root,
        decision_engine_factory=decision_engine_factory,
    )
    result = dict(outcome)
    result["offline_original_github_zip_source_crosscheck"] = receipt
    result["original_exchange_feed_independently_authenticated"] = False
    result["promotion_authority"] = False
    result["execution_authority"] = False
    return result
