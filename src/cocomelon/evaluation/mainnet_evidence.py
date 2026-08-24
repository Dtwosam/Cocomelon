from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cocomelon.domain.replay import ReplayManifest, ReplayResult
from cocomelon.evaluation.aggregate import (
    EvidenceAggregationError,
    EvidenceAggregationResult,
    aggregate_evaluation_evidence,
)
from cocomelon.journal.store import JournalConsistencyError, JournalStore

MAINNET_EVIDENCE_KIND = "genuine_public_hyperliquid_mainnet"
MAINNET_API_URL = "https://api.hyperliquid.xyz"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
ATTESTATION_NAME = "mainnet-attestation.json"


class MainnetEvidenceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ValidatedCohort:
    root: Path
    manifest: ReplayManifest
    result: ReplayResult
    recording_session_id: str
    workflow_head_sha: str
    trigger_head_sha: str
    source_digest: str


def _read_mapping(path: Path, field: str) -> dict[str, Any]:
    if not path.is_file():
        raise MainnetEvidenceError(f"{field} is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainnetEvidenceError(f"{field} must contain valid JSON") from exc
    if not isinstance(raw, dict):
        raise MainnetEvidenceError(f"{field} must contain a JSON object")
    return {str(key): value for key, value in raw.items()}


def _read_text(path: Path, field: str) -> str:
    if not path.is_file():
        raise MainnetEvidenceError(f"{field} is missing: {path}")
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MainnetEvidenceError(f"unable to read {field}") from exc
    if not value:
        raise MainnetEvidenceError(f"{field} must not be empty")
    return value


def _require_bool(value: object, expected: bool, field: str) -> None:
    if value is not expected:
        raise MainnetEvidenceError(f"{field} must be {str(expected).lower()}")


def _require_zero(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise MainnetEvidenceError(f"{field} must be zero")


def _require_equal(value: object, expected: object, field: str) -> None:
    if value != expected:
        raise MainnetEvidenceError(f"{field} does not match canonical evidence")


def _require_sha(value: str, field: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise MainnetEvidenceError(f"{field} must be a 40-character commit SHA")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise MainnetEvidenceError(f"unable to hash evidence file: {path}") from exc
    return digest.hexdigest()


def _canonical_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_canonical_replay(source_root: Path) -> tuple[ReplayManifest, ReplayResult]:
    source_journal = source_root / "journal.sqlite3"
    if not source_journal.is_file():
        raise MainnetEvidenceError(f"source journal is missing: {source_journal}")
    before = _sha256(source_journal)
    with tempfile.TemporaryDirectory(prefix="cocomelon-mainnet-attestation-") as temporary:
        work_journal = Path(temporary) / "journal.sqlite3"
        shutil.copy2(source_journal, work_journal)
        if _sha256(work_journal) != before:
            raise MainnetEvidenceError("source journal copy checksum mismatch")
        journal = JournalStore(work_journal)
        try:
            results = tuple(journal.iter_replay_results())
            if len(results) != 1:
                raise MainnetEvidenceError(
                    "mainnet cohort must contain exactly one finished replay result"
                )
            result = results[0]
            manifest = journal.load_manifest(result.manifest_id)
            if manifest is None:
                raise MainnetEvidenceError("mainnet cohort replay manifest is missing")
        except JournalConsistencyError as exc:
            raise MainnetEvidenceError("mainnet cohort journal is invalid") from exc
        finally:
            journal.close()
    if _sha256(source_journal) != before:
        raise MainnetEvidenceError("source journal changed during attestation")
    return manifest, result


def _cohort_source_digest(source_root: Path, recording_session_path: Path) -> str:
    paths = {
        "bundle.json": source_root / "bundle.json",
        "cohort-summary.json": source_root / "cohort-summary.json",
        "facts.sqlite3": source_root / "facts.sqlite3",
        "freeze.json": source_root / "freeze.json",
        "journal.sqlite3": source_root / "journal.sqlite3",
        "record.json": source_root / "record.json",
        "recording/recording-session.json": recording_session_path,
        "replay.json": source_root / "replay.json",
        "trigger-head.txt": source_root / "trigger-head.txt",
        "workflow-head.txt": source_root / "workflow-head.txt",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise MainnetEvidenceError(f"mainnet cohort evidence file is missing: {missing[0]}")
    return _canonical_digest({name: _sha256(path) for name, path in sorted(paths.items())})


def _validate_complete_mainnet_cohort(source_root: Path) -> _ValidatedCohort:
    summary = _read_mapping(source_root / "cohort-summary.json", "cohort summary")
    if summary.get("evidence_kind") != MAINNET_EVIDENCE_KIND:
        raise MainnetEvidenceError("cohort must be genuine public Hyperliquid mainnet evidence")
    if summary.get("economic_claim") != "none":
        raise MainnetEvidenceError("source cohort must not contain an economic claim")
    _require_bool(summary.get("data_complete"), True, "cohort data_complete")
    _require_zero(summary.get("recorded_gap_count"), "cohort recorded_gap_count")
    _require_zero(summary.get("recorded_duplicate_count"), "cohort recorded_duplicate_count")

    record = _read_mapping(source_root / "record.json", "record result")
    _require_bool(record.get("network_access"), True, "record network_access")
    _require_bool(record.get("live_orders"), False, "record live_orders")
    _require_zero(record.get("gap_count"), "record gap_count")
    _require_zero(record.get("duplicate_count"), "record duplicate_count")
    _require_zero(record.get("anomaly_count"), "record anomaly_count")

    replay = _read_mapping(source_root / "replay.json", "replay result")
    _require_bool(replay.get("network_access"), False, "replay network_access")
    _require_bool(replay.get("live_orders"), False, "replay live_orders")
    _require_bool(replay.get("data_complete"), True, "replay data_complete")

    freeze = _read_mapping(source_root / "freeze.json", "freeze result")
    _require_bool(freeze.get("network_access"), False, "freeze network_access")
    _require_bool(freeze.get("live_orders"), False, "freeze live_orders")

    bundle = _read_mapping(source_root / "bundle.json", "replay bundle")
    bundle_manifest = bundle.get("manifest")
    if not isinstance(bundle_manifest, dict):
        raise MainnetEvidenceError("replay bundle manifest must be an object")
    if bundle.get("source_root_relative") != "../recording":
        raise MainnetEvidenceError("replay bundle must point to its sibling recording")

    recording_session_path = source_root.parent / "recording" / "recording-session.json"
    session = _read_mapping(recording_session_path, "recording session")
    if session.get("api_url") != MAINNET_API_URL or session.get("ws_url") != MAINNET_WS_URL:
        raise MainnetEvidenceError("recording session must use public Hyperliquid mainnet")

    workflow_head = _read_text(source_root / "workflow-head.txt", "workflow head")
    trigger_head = _read_text(source_root / "trigger-head.txt", "trigger head")
    _require_sha(workflow_head, "workflow head")
    _require_sha(trigger_head, "trigger head")

    manifest, result = _load_canonical_replay(source_root)
    if result.data_complete is not True or result.processed_gaps != 0 or manifest.gap_refs:
        raise MainnetEvidenceError("canonical replay must be complete and gap-free")

    _require_equal(
        summary.get("checked_out_code_revision"),
        manifest.code_revision,
        "code_revision",
    )
    _require_equal(summary.get("replay_run_id"), result.run_id, "replay run_id")
    _require_equal(summary.get("replay_result_digest"), result.result_digest, "result_digest")
    _require_equal(summary.get("recorded_event_count"), record.get("event_count"), "event count")
    _require_equal(summary.get("recording_session_id"), record.get("session_id"), "session_id")
    _require_equal(
        summary.get("strategy_decisions"),
        result.strategy_decisions,
        "strategy decisions",
    )
    _require_equal(summary.get("risk_approvals"), result.risk_approvals, "risk approvals")
    _require_equal(summary.get("risk_rejections"), result.risk_rejections, "risk rejections")
    _require_equal(
        summary.get("execution_attempts"),
        result.execution_attempts,
        "execution attempts",
    )
    _require_equal(summary.get("fills"), result.fills, "fills")
    _require_equal(summary.get("opened_positions"), result.opened_positions, "opened positions")
    _require_equal(summary.get("closed_positions"), result.closed_positions, "closed positions")
    _require_equal(summary.get("closed_trade_count"), len(result.closed_trade_ids), "closed trades")

    _require_equal(replay.get("manifest_id"), manifest.manifest_id, "replay manifest_id")
    _require_equal(replay.get("run_id"), result.run_id, "replay run_id")
    _require_equal(replay.get("result_digest"), result.result_digest, "replay result_digest")
    _require_equal(replay.get("strategy_decisions"), result.strategy_decisions, "replay decisions")
    _require_equal(replay.get("risk_approvals"), result.risk_approvals, "replay approvals")
    _require_equal(replay.get("risk_rejections"), result.risk_rejections, "replay rejections")
    _require_equal(replay.get("execution_attempts"), result.execution_attempts, "replay attempts")
    _require_equal(replay.get("fills"), result.fills, "replay fills")
    _require_equal(
        replay.get("opened_positions"),
        result.opened_positions,
        "replay opened positions",
    )
    _require_equal(
        replay.get("closed_positions"),
        result.closed_positions,
        "replay closed positions",
    )
    _require_equal(
        replay.get("closed_trade_ids"),
        list(result.closed_trade_ids),
        "replay closed trades",
    )

    session_id = str(summary.get("recording_session_id"))
    _require_equal(session.get("session_id"), session_id, "recording session_id")
    _require_equal(
        session.get("recorder_code_revision"),
        manifest.code_revision,
        "recorder code_revision",
    )
    _require_equal(freeze.get("code_revision"), manifest.code_revision, "freeze code_revision")
    _require_equal(freeze.get("manifest_id"), manifest.manifest_id, "freeze manifest_id")
    _require_equal(
        freeze.get("recording_session_digest"),
        session_id,
        "freeze recording session",
    )
    _require_equal(
        bundle_manifest.get("code_revision"),
        manifest.code_revision,
        "bundle code_revision",
    )
    _require_equal(bundle_manifest.get("manifest_id"), manifest.manifest_id, "bundle manifest_id")
    _require_equal(bundle_manifest.get("gap_refs"), [], "bundle gap_refs")
    _require_equal(bundle.get("recording_session_digest"), session_id, "bundle recording session")
    _require_equal(workflow_head, manifest.code_revision, "workflow head")
    _require_equal(summary.get("trigger_head_sha"), trigger_head, "trigger head")

    return _ValidatedCohort(
        root=source_root,
        manifest=manifest,
        result=result,
        recording_session_id=session_id,
        workflow_head_sha=workflow_head,
        trigger_head_sha=trigger_head,
        source_digest=_cohort_source_digest(source_root, recording_session_path),
    )


def _attestation_payload(
    aggregation: EvidenceAggregationResult,
    cohorts: Sequence[_ValidatedCohort],
) -> dict[str, object]:
    sources = [
        {
            "manifest_id": cohort.manifest.manifest_id,
            "recording_session_id": cohort.recording_session_id,
            "result_digest": cohort.result.result_digest,
            "run_id": cohort.result.run_id,
            "source_digest": cohort.source_digest,
            "trigger_head_sha": cohort.trigger_head_sha,
            "workflow_head_sha": cohort.workflow_head_sha,
        }
        for cohort in sorted(cohorts, key=lambda item: item.result.run_id)
    ]
    base: dict[str, object] = {
        "schema_version": 1,
        "evidence_kind": MAINNET_EVIDENCE_KIND,
        "economic_claim": "none",
        "real_evidence_eligible": True,
        "code_revision": aggregation.code_revision,
        "run_ids": list(aggregation.run_ids),
        "source_count": len(sources),
        "sources": sources,
    }
    return {**base, "attestation_id": _canonical_digest(base)}


def _write_attestation(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError as exc:
        raise MainnetEvidenceError("unable to commit mainnet evidence attestation") from exc
    finally:
        temporary.unlink(missing_ok=True)


def aggregate_mainnet_evaluation_evidence(
    target_journal_path: str | Path,
    target_facts_path: str | Path,
    source_roots: Sequence[str | Path],
) -> EvidenceAggregationResult:
    if not source_roots:
        raise MainnetEvidenceError("at least one mainnet source root is required")
    target_journal = Path(target_journal_path)
    target_facts = Path(target_facts_path)
    if target_journal.parent.resolve() != target_facts.parent.resolve():
        raise MainnetEvidenceError("mainnet aggregation targets must share one directory")
    attestation_path = target_journal.parent / ATTESTATION_NAME
    if target_journal.exists() or target_facts.exists() or attestation_path.exists():
        raise MainnetEvidenceError(
            "existing mainnet aggregate requires a verified attestation merge"
        )

    roots = tuple(Path(item).resolve() for item in source_roots)
    cohorts = tuple(_validate_complete_mainnet_cohort(root) for root in roots)
    revisions = {item.manifest.code_revision for item in cohorts}
    if len(revisions) != 1:
        raise MainnetEvidenceError("mainnet cohorts must use one fixed code revision")

    try:
        aggregation = aggregate_evaluation_evidence(target_journal, target_facts, roots)
    except EvidenceAggregationError as exc:
        raise MainnetEvidenceError("unable to aggregate validated mainnet evidence") from exc
    _write_attestation(attestation_path, _attestation_payload(aggregation, cohorts))
    return aggregation
