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
from cocomelon.evaluation.cli_support import freeze_evaluation_dataset_payload
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


@dataclass(frozen=True, slots=True)
class _VerifiedAttestation:
    attestation_id: str
    code_revision: str
    run_ids: tuple[str, ...]
    sources: tuple[dict[str, str], ...]


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


def _require_digest(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
        raise MainnetEvidenceError(f"{field} must be a 64-character digest")


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


def _load_replay_pairs(journal_path: Path) -> tuple[tuple[ReplayManifest, ReplayResult], ...]:
    if not journal_path.is_file():
        raise MainnetEvidenceError(f"source journal is missing: {journal_path}")
    before = _sha256(journal_path)
    with tempfile.TemporaryDirectory(prefix="cocomelon-mainnet-attestation-") as temporary:
        work_journal = Path(temporary) / "journal.sqlite3"
        shutil.copy2(journal_path, work_journal)
        if _sha256(work_journal) != before:
            raise MainnetEvidenceError("source journal copy checksum mismatch")
        journal = JournalStore(work_journal)
        try:
            results = tuple(journal.iter_replay_results())
            pairs: list[tuple[ReplayManifest, ReplayResult]] = []
            for result in results:
                manifest = journal.load_manifest(result.manifest_id)
                if manifest is None:
                    raise MainnetEvidenceError("mainnet cohort replay manifest is missing")
                pairs.append((manifest, result))
        except JournalConsistencyError as exc:
            raise MainnetEvidenceError("mainnet cohort journal is invalid") from exc
        finally:
            journal.close()
    if _sha256(journal_path) != before:
        raise MainnetEvidenceError("source journal changed during attestation")
    return tuple(pairs)


def _load_canonical_replay(source_root: Path) -> tuple[ReplayManifest, ReplayResult]:
    pairs = _load_replay_pairs(source_root / "journal.sqlite3")
    if len(pairs) != 1:
        raise MainnetEvidenceError(
            "mainnet cohort must contain exactly one finished replay result"
        )
    return pairs[0]


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


def _cohort_source_payload(cohort: _ValidatedCohort) -> dict[str, str]:
    return {
        "manifest_id": cohort.manifest.manifest_id,
        "recording_session_id": cohort.recording_session_id,
        "result_digest": cohort.result.result_digest,
        "run_id": cohort.result.run_id,
        "source_digest": cohort.source_digest,
        "trigger_head_sha": cohort.trigger_head_sha,
        "workflow_head_sha": cohort.workflow_head_sha,
    }


def _attestation_payload(
    code_revision: str,
    run_ids: Sequence[str],
    sources: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    source_payloads = [dict(item) for item in sorted(sources, key=lambda item: item["run_id"])]
    base: dict[str, object] = {
        "schema_version": 1,
        "evidence_kind": MAINNET_EVIDENCE_KIND,
        "economic_claim": "none",
        "real_evidence_eligible": True,
        "code_revision": code_revision,
        "run_ids": sorted(run_ids),
        "source_count": len(source_payloads),
        "sources": source_payloads,
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


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise MainnetEvidenceError(f"{field} must be a non-empty string array")
    return tuple(str(item) for item in value)


def _attestation_source(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MainnetEvidenceError("attestation source must be an object")
    required = {
        "manifest_id",
        "recording_session_id",
        "result_digest",
        "run_id",
        "source_digest",
        "trigger_head_sha",
        "workflow_head_sha",
    }
    if set(value) != required:
        raise MainnetEvidenceError("attestation source fields are invalid")
    result: dict[str, str] = {}
    for field in sorted(required):
        raw = value[field]
        if not isinstance(raw, str) or not raw:
            raise MainnetEvidenceError(f"attestation source {field} must be a string")
        result[field] = raw
    _require_digest(result["result_digest"], "attestation source result_digest")
    _require_digest(result["source_digest"], "attestation source source_digest")
    _require_sha(result["trigger_head_sha"], "attestation source trigger_head_sha")
    _require_sha(result["workflow_head_sha"], "attestation source workflow_head_sha")
    return result


def _read_verified_attestation(path: Path) -> _VerifiedAttestation:
    raw = _read_mapping(path, "mainnet attestation")
    required = {
        "attestation_id",
        "code_revision",
        "economic_claim",
        "evidence_kind",
        "real_evidence_eligible",
        "run_ids",
        "schema_version",
        "source_count",
        "sources",
    }
    if set(raw) != required:
        raise MainnetEvidenceError("mainnet attestation fields are invalid")
    if raw.get("schema_version") != 1:
        raise MainnetEvidenceError("mainnet attestation schema version is unsupported")
    if raw.get("evidence_kind") != MAINNET_EVIDENCE_KIND:
        raise MainnetEvidenceError("mainnet attestation evidence kind is invalid")
    if raw.get("economic_claim") != "none":
        raise MainnetEvidenceError("mainnet attestation economic claim must be none")
    _require_bool(raw.get("real_evidence_eligible"), True, "real_evidence_eligible")

    code_revision = raw.get("code_revision")
    attestation_id = raw.get("attestation_id")
    if not isinstance(code_revision, str):
        raise MainnetEvidenceError("mainnet attestation code_revision must be a string")
    if not isinstance(attestation_id, str):
        raise MainnetEvidenceError("mainnet attestation attestation_id must be a string")
    _require_sha(code_revision, "mainnet attestation code_revision")
    _require_digest(attestation_id, "mainnet attestation attestation_id")

    run_ids = _string_list(raw.get("run_ids"), "mainnet attestation run_ids")
    if tuple(sorted(set(run_ids))) != run_ids:
        raise MainnetEvidenceError("mainnet attestation run_ids must be sorted and unique")
    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise MainnetEvidenceError("mainnet attestation sources must be a non-empty array")
    sources = tuple(_attestation_source(item) for item in raw_sources)
    if tuple(sorted(item["run_id"] for item in sources)) != run_ids:
        raise MainnetEvidenceError("mainnet attestation sources must match run_ids")
    if raw.get("source_count") != len(sources):
        raise MainnetEvidenceError("mainnet attestation source_count is invalid")

    base = {key: value for key, value in raw.items() if key != "attestation_id"}
    if _canonical_digest(base) != attestation_id:
        raise MainnetEvidenceError("mainnet attestation digest is invalid")
    return _VerifiedAttestation(
        attestation_id=attestation_id,
        code_revision=code_revision,
        run_ids=run_ids,
        sources=sources,
    )


def _verify_attested_target(
    target_journal: Path,
    target_facts: Path,
    attestation_path: Path,
) -> _VerifiedAttestation:
    exists = (target_journal.exists(), target_facts.exists(), attestation_path.exists())
    if exists != (True, True, True):
        raise MainnetEvidenceError(
            "existing mainnet aggregate requires journal, facts, and attestation"
        )
    if not target_facts.is_file():
        raise MainnetEvidenceError("mainnet aggregate facts must be a regular file")
    attestation = _read_verified_attestation(attestation_path)
    pairs = _load_replay_pairs(target_journal)
    if not pairs:
        raise MainnetEvidenceError("mainnet aggregate must contain finished replay results")
    by_run = {result.run_id: (manifest, result) for manifest, result in pairs}
    if tuple(sorted(by_run)) != attestation.run_ids:
        raise MainnetEvidenceError("mainnet attestation run set does not match aggregate")
    if {manifest.code_revision for manifest, _ in pairs} != {attestation.code_revision}:
        raise MainnetEvidenceError("mainnet attestation revision does not match aggregate")
    for source in attestation.sources:
        manifest, result = by_run[source["run_id"]]
        _require_equal(source["manifest_id"], manifest.manifest_id, "attested manifest_id")
        _require_equal(source["result_digest"], result.result_digest, "attested result_digest")
        _require_equal(
            source["workflow_head_sha"],
            manifest.code_revision,
            "attested workflow head",
        )
    return attestation


def _merge_sources(
    existing: Sequence[Mapping[str, str]],
    incoming: Sequence[_ValidatedCohort],
) -> tuple[dict[str, str], ...]:
    merged = {item["run_id"]: dict(item) for item in existing}
    for cohort in incoming:
        source = _cohort_source_payload(cohort)
        current = merged.get(source["run_id"])
        if current is not None and current != source:
            raise MainnetEvidenceError(
                f"conflicting mainnet attestation source: {source['run_id']}"
            )
        merged[source["run_id"]] = source
    return tuple(merged[run_id] for run_id in sorted(merged))


def _reject_reused_or_overlapping_cohorts(
    target_journal: Path,
    existing_attestation: _VerifiedAttestation | None,
    incoming: Sequence[_ValidatedCohort],
) -> None:
    existing_run_ids = (
        set() if existing_attestation is None else set(existing_attestation.run_ids)
    )
    new_cohorts = tuple(
        cohort for cohort in incoming if cohort.result.run_id not in existing_run_ids
    )
    existing_sessions = (
        set()
        if existing_attestation is None
        else {item["recording_session_id"] for item in existing_attestation.sources}
    )
    seen_sessions = set(existing_sessions)
    intervals: list[tuple[str, int, int]] = []
    if existing_attestation is not None:
        intervals.extend(
            (result.run_id, manifest.start_ms, manifest.end_ms)
            for manifest, result in _load_replay_pairs(target_journal)
        )

    for cohort in new_cohorts:
        if cohort.recording_session_id in seen_sessions:
            raise MainnetEvidenceError("mainnet recording session was already aggregated")
        for run_id, start_ms, end_ms in intervals:
            if cohort.manifest.start_ms < end_ms and start_ms < cohort.manifest.end_ms:
                raise MainnetEvidenceError(
                    "mainnet cohort time windows overlap: "
                    f"{run_id} and {cohort.result.run_id}"
                )
        seen_sessions.add(cohort.recording_session_id)
        intervals.append(
            (cohort.result.run_id, cohort.manifest.start_ms, cohort.manifest.end_ms)
        )


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

    existing_attestation: _VerifiedAttestation | None = None
    any_target = target_journal.exists() or target_facts.exists() or attestation_path.exists()
    if any_target:
        existing_attestation = _verify_attested_target(
            target_journal,
            target_facts,
            attestation_path,
        )

    roots = tuple(Path(item).resolve() for item in source_roots)
    cohorts = tuple(_validate_complete_mainnet_cohort(root) for root in roots)
    revisions = {item.manifest.code_revision for item in cohorts}
    if len(revisions) != 1:
        raise MainnetEvidenceError("mainnet cohorts must use one fixed code revision")
    incoming_revision = next(iter(revisions))
    if existing_attestation is not None:
        _require_equal(
            incoming_revision,
            existing_attestation.code_revision,
            "mainnet aggregate code revision",
        )
    sources = _merge_sources(
        () if existing_attestation is None else existing_attestation.sources,
        cohorts,
    )
    _reject_reused_or_overlapping_cohorts(target_journal, existing_attestation, cohorts)

    try:
        aggregation = aggregate_evaluation_evidence(target_journal, target_facts, roots)
    except EvidenceAggregationError as exc:
        raise MainnetEvidenceError("unable to aggregate validated mainnet evidence") from exc
    payload = _attestation_payload(aggregation.code_revision, aggregation.run_ids, sources)
    _write_attestation(attestation_path, payload)
    return aggregation


def freeze_mainnet_evaluation_dataset_payload(
    journal_path: str | Path,
    facts_path: str | Path,
    replay_run_ids: tuple[str, ...],
) -> dict[str, object]:
    journal = Path(journal_path)
    facts = Path(facts_path)
    if journal.parent.resolve() != facts.parent.resolve():
        raise MainnetEvidenceError("mainnet dataset stores must share one directory")
    attestation = _verify_attested_target(
        journal,
        facts,
        journal.parent / ATTESTATION_NAME,
    )
    requested = tuple(sorted(set(replay_run_ids)))
    if requested != attestation.run_ids:
        raise MainnetEvidenceError("dataset freeze requires the exact attested run set")

    payload = freeze_evaluation_dataset_payload(journal, facts, requested)
    if payload.get("data_complete") is not True or payload.get("gap_refs") != []:
        raise MainnetEvidenceError("attested mainnet dataset must remain complete and gap-free")
    _require_equal(
        payload.get("code_revision"),
        attestation.code_revision,
        "mainnet dataset code revision",
    )
    return {
        **payload,
        "evidence_kind": MAINNET_EVIDENCE_KIND,
        "economic_claim": "none",
        "real_evidence_eligible": True,
        "mainnet_attestation_id": attestation.attestation_id,
        "live_orders": False,
    }


def verify_mainnet_evidence_cohort_payload(
    source_root: str | Path,
) -> dict[str, object]:
    cohort = _validate_complete_mainnet_cohort(Path(source_root).resolve())
    return {
        "evidence_kind": MAINNET_EVIDENCE_KIND,
        "economic_claim": "none",
        "real_evidence_eligible": True,
        "code_revision": cohort.manifest.code_revision,
        "run_id": cohort.result.run_id,
        "manifest_id": cohort.manifest.manifest_id,
        "recording_session_id": cohort.recording_session_id,
        "source_digest": cohort.source_digest,
        "result_digest": cohort.result.result_digest,
        "workflow_head_sha": cohort.workflow_head_sha,
        "trigger_head_sha": cohort.trigger_head_sha,
        "start_ms": cohort.manifest.start_ms,
        "end_ms": cohort.manifest.end_ms,
        "duration_ms": cohort.manifest.end_ms - cohort.manifest.start_ms,
        "strategy_decisions": cohort.result.strategy_decisions,
        "risk_approvals": cohort.result.risk_approvals,
        "risk_rejections": cohort.result.risk_rejections,
        "execution_attempts": cohort.result.execution_attempts,
        "fills": cohort.result.fills,
        "opened_positions": cohort.result.opened_positions,
        "closed_positions": cohort.result.closed_positions,
        "closed_trade_count": len(cohort.result.closed_trade_ids),
        "data_complete": cohort.result.data_complete,
        "network_access": False,
        "live_orders": False,
    }
