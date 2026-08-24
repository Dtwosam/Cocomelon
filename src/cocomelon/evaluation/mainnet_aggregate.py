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

from cocomelon.evaluation.aggregate import (
    FACTS_NAME,
    JOURNAL_NAME,
    EvidenceAggregationError,
    EvidenceAggregationResult,
    _load_source,
    aggregate_evaluation_evidence,
)

SUMMARY_NAME = "cohort-summary.json"
RECORD_NAME = "record.json"
REPLAY_NAME = "replay.json"
CORPUS_NAME = "genuine-mainnet-corpus.json"
EVIDENCE_KIND = "genuine_public_hyperliquid_mainnet"
CORPUS_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GenuineMainnetAttestation:
    run_id: str
    code_revision: str
    recording_session_id: str
    closed_trade_count: int
    metadata_sha256: str
    journal_sha256: str
    facts_sha256: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "code_revision": self.code_revision,
            "recording_session_id": self.recording_session_id,
            "closed_trade_count": self.closed_trade_count,
            "metadata_sha256": self.metadata_sha256,
            "journal_sha256": self.journal_sha256,
            "facts_sha256": self.facts_sha256,
        }


def corpus_attestation_path(journal_path: str | Path) -> Path:
    return Path(journal_path).with_name(CORPUS_NAME)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    if not path.is_file():
        raise EvidenceAggregationError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceAggregationError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceAggregationError(f"{label} must be a JSON object: {path}")
    return {str(key): item for key, item in value.items()}


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceAggregationError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceAggregationError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceAggregationError(f"{field} must be a boolean")
    return value


def _metadata_digest(
    summary: Mapping[str, object],
    record: Mapping[str, object],
    replay: Mapping[str, object],
) -> str:
    encoded = json.dumps(
        {"summary": summary, "record": record, "replay": replay},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_attestation(root: Path) -> GenuineMainnetAttestation:
    summary = _load_json_object(root / SUMMARY_NAME, "cohort summary")
    record = _load_json_object(root / RECORD_NAME, "recording summary")
    replay = _load_json_object(root / REPLAY_NAME, "replay summary")

    if summary.get("evidence_kind") != EVIDENCE_KIND:
        raise EvidenceAggregationError(
            "source is not genuine public Hyperliquid mainnet evidence"
        )
    if summary.get("economic_claim") != "none":
        raise EvidenceAggregationError("source cohort must not carry an economic claim")

    summary_complete = _boolean(
        summary.get("data_complete"),
        "summary.data_complete",
    )
    replay_complete = _boolean(
        replay.get("data_complete"),
        "replay.data_complete",
    )
    recorded_gaps = _integer(
        summary.get("recorded_gap_count"),
        "summary.recorded_gap_count",
    )
    record_gaps = _integer(record.get("gap_count"), "record.gap_count")
    recorded_duplicates = _integer(
        summary.get("recorded_duplicate_count"),
        "summary.recorded_duplicate_count",
    )
    record_duplicates = _integer(
        record.get("duplicate_count"),
        "record.duplicate_count",
    )
    record_anomalies = _integer(
        record.get("anomaly_count"),
        "record.anomaly_count",
    )
    if (
        not summary_complete
        or not replay_complete
        or recorded_gaps != 0
        or record_gaps != 0
    ):
        raise EvidenceAggregationError(
            "genuine mainnet source must be complete and gap-free"
        )
    if recorded_duplicates != record_duplicates:
        raise EvidenceAggregationError(
            "attested duplicate count does not match recording summary"
        )
    if record_duplicates != 0 or record_anomalies != 0:
        raise EvidenceAggregationError(
            "genuine mainnet source must be duplicate-free and anomaly-free"
        )

    if _boolean(record.get("live_orders"), "record.live_orders"):
        raise EvidenceAggregationError(
            "genuine mainnet economic evidence must be paper-only"
        )
    if not _boolean(record.get("network_access"), "record.network_access"):
        raise EvidenceAggregationError(
            "genuine mainnet recording must use public network evidence"
        )
    if _boolean(replay.get("live_orders"), "replay.live_orders"):
        raise EvidenceAggregationError(
            "genuine mainnet economic evidence must be paper-only"
        )
    if _boolean(replay.get("network_access"), "replay.network_access"):
        raise EvidenceAggregationError("genuine mainnet replay must be offline")

    run_id = _string(summary.get("replay_run_id"), "summary.replay_run_id")
    if _string(replay.get("run_id"), "replay.run_id") != run_id:
        raise EvidenceAggregationError(
            "attested replay run id does not match replay summary"
        )
    session_id = _string(
        summary.get("recording_session_id"),
        "summary.recording_session_id",
    )
    if _string(record.get("session_id"), "record.session_id") != session_id:
        raise EvidenceAggregationError(
            "attested recording session does not match recording summary"
        )

    code_revision = _string(
        summary.get("checked_out_code_revision"),
        "summary.checked_out_code_revision",
    )
    closed_trade_count = _integer(
        summary.get("closed_trade_count"),
        "summary.closed_trade_count",
    )
    dataset_trade_count = _integer(
        summary.get("dataset_trade_count"),
        "summary.dataset_trade_count",
    )
    closed_trade_ids = replay.get("closed_trade_ids")
    if not isinstance(closed_trade_ids, list) or not all(
        isinstance(item, str) for item in closed_trade_ids
    ):
        raise EvidenceAggregationError(
            "replay.closed_trade_ids must be a string array"
        )
    if (
        dataset_trade_count != closed_trade_count
        or len(closed_trade_ids) != closed_trade_count
    ):
        raise EvidenceAggregationError("attested closed-trade counts do not agree")

    journal_path = root / JOURNAL_NAME
    facts_path = root / FACTS_NAME
    if not journal_path.is_file() or not facts_path.is_file():
        raise EvidenceAggregationError(
            "attested source is missing journal or fact stores"
        )

    return GenuineMainnetAttestation(
        run_id=run_id,
        code_revision=code_revision,
        recording_session_id=session_id,
        closed_trade_count=closed_trade_count,
        metadata_sha256=_metadata_digest(summary, record, replay),
        journal_sha256=_sha256(journal_path),
        facts_sha256=_sha256(facts_path),
    )


def _validate_attested_store(
    root: Path,
    attestation: GenuineMainnetAttestation,
) -> None:
    snapshot = _load_source(root)
    if len(snapshot.results) != 1 or len(snapshot.manifests) != 1:
        raise EvidenceAggregationError(
            "each attested cohort source must contain exactly one replay run"
        )
    result = snapshot.results[0]
    manifest = snapshot.manifests[0]
    if result.run_id != attestation.run_id:
        raise EvidenceAggregationError(
            "attested replay run id does not match source store run id"
        )
    if manifest.code_revision != attestation.code_revision:
        raise EvidenceAggregationError(
            "attested code revision does not match source replay manifest"
        )
    if not result.data_complete or result.processed_gaps != 0 or manifest.gap_refs:
        raise EvidenceAggregationError(
            "attested replay store must be complete and gap-free"
        )
    if len(result.closed_trade_ids) != attestation.closed_trade_count:
        raise EvidenceAggregationError(
            "attested closed-trade count does not match source store"
        )


def _target_root(journal_path: Path, facts_path: Path) -> Path:
    if journal_path.name != JOURNAL_NAME or facts_path.name != FACTS_NAME:
        raise EvidenceAggregationError(
            f"strict corpus targets must be named {JOURNAL_NAME} and {FACTS_NAME}"
        )
    if journal_path.parent.resolve() != facts_path.parent.resolve():
        raise EvidenceAggregationError(
            "strict corpus targets must share one directory"
        )
    return journal_path.parent


def _load_corpus_payload(path: Path) -> dict[str, object]:
    payload = _load_json_object(path, "genuine mainnet corpus attestation")
    if payload.get("schema_version") != CORPUS_SCHEMA_VERSION:
        raise EvidenceAggregationError("unsupported genuine mainnet corpus schema")
    if payload.get("evidence_kind") != EVIDENCE_KIND:
        raise EvidenceAggregationError(
            "target corpus is not genuine public mainnet evidence"
        )
    return payload


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise EvidenceAggregationError(f"{field} must be a string array")
    return tuple(value)


def _existing_attestations(
    payload: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    raw = payload.get("source_attestations")
    if not isinstance(raw, list):
        raise EvidenceAggregationError(
            "corpus source_attestations must be an array"
        )
    attestations: dict[str, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise EvidenceAggregationError(
                "corpus source attestation must be an object"
            )
        normalized = {str(key): value for key, value in item.items()}
        run_id = _string(normalized.get("run_id"), "corpus source run_id")
        if run_id in attestations and attestations[run_id] != normalized:
            raise EvidenceAggregationError(
                f"conflicting corpus attestation for run: {run_id}"
            )
        attestations[run_id] = normalized
    return attestations


def _validate_existing_corpus(
    root: Path,
) -> tuple[str, dict[str, dict[str, object]]]:
    payload = _load_corpus_payload(root / CORPUS_NAME)
    snapshot = _load_source(root)
    revisions = {item.code_revision for item in snapshot.manifests}
    if len(revisions) != 1:
        raise EvidenceAggregationError(
            "existing genuine mainnet corpus has mixed code revisions"
        )
    code_revision = next(iter(revisions))
    if _string(
        payload.get("code_revision"),
        "corpus.code_revision",
    ) != code_revision:
        raise EvidenceAggregationError(
            "corpus attestation code revision does not match target stores"
        )
    actual_run_ids = tuple(sorted(item.run_id for item in snapshot.results))
    attested_run_ids = tuple(
        sorted(_string_list(payload.get("run_ids"), "corpus.run_ids"))
    )
    if actual_run_ids != attested_run_ids:
        raise EvidenceAggregationError(
            "corpus attestation run ids do not match target stores"
        )
    for result, manifest in zip(
        snapshot.results,
        snapshot.manifests,
        strict=True,
    ):
        if (
            not result.data_complete
            or result.processed_gaps != 0
            or manifest.gap_refs
        ):
            raise EvidenceAggregationError(
                "existing genuine mainnet corpus contains incomplete evidence"
            )
    attestations = _existing_attestations(payload)
    if tuple(sorted(attestations)) != actual_run_ids:
        raise EvidenceAggregationError(
            "corpus source attestations do not cover every target run"
        )
    return code_revision, attestations


def validate_genuine_mainnet_corpus(
    journal_path: str | Path,
    facts_path: str | Path,
) -> EvidenceAggregationResult:
    journal = Path(journal_path)
    facts = Path(facts_path)
    root = _target_root(journal, facts)
    present = (
        journal.exists(),
        facts.exists(),
        (root / CORPUS_NAME).exists(),
    )
    if present != (True, True, True):
        raise EvidenceAggregationError(
            "genuine mainnet corpus requires both stores and attestation"
        )
    code_revision, _ = _validate_existing_corpus(root)
    snapshot = _load_source(root)
    run_ids = tuple(sorted(item.run_id for item in snapshot.results))
    return EvidenceAggregationResult(
        code_revision=code_revision,
        run_ids=run_ids,
        source_count=len(run_ids),
        trade_count=len(snapshot.trades),
        observation_count=len(snapshot.observations),
        decision_fact_count=len(snapshot.decision_facts),
        equity_fact_count=len(snapshot.equity_facts),
    )


def _corpus_payload(
    result: EvidenceAggregationResult,
    attestations: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "evidence_kind": EVIDENCE_KIND,
        "code_revision": result.code_revision,
        "run_ids": list(result.run_ids),
        "source_attestations": [
            attestations[run_id] for run_id in sorted(attestations)
        ],
    }


def _commit_staged_corpus(
    staging: Path,
    target: Path,
    *,
    existed: bool,
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    names = (JOURNAL_NAME, FACTS_NAME, CORPUS_NAME)
    token = uuid.uuid4().hex
    backups = {name: target / f".{name}.{token}.bak" for name in names}
    try:
        if existed:
            for name in names:
                shutil.copy2(target / name, backups[name])
        try:
            for name in names:
                os.replace(staging / name, target / name)
        except Exception:
            if existed:
                for name in names:
                    if backups[name].exists():
                        os.replace(backups[name], target / name)
            else:
                for name in names:
                    (target / name).unlink(missing_ok=True)
            raise
    finally:
        for path in backups.values():
            path.unlink(missing_ok=True)


def aggregate_genuine_mainnet_evidence(
    target_journal_path: str | Path,
    target_facts_path: str | Path,
    source_roots: Sequence[str | Path],
) -> EvidenceAggregationResult:
    target_journal = Path(target_journal_path)
    target_facts = Path(target_facts_path)
    target_root = _target_root(target_journal, target_facts)
    if not source_roots:
        raise EvidenceAggregationError(
            "at least one genuine mainnet source root is required"
        )

    roots = tuple(Path(item).resolve() for item in source_roots)
    if len(set(roots)) != len(roots):
        raise EvidenceAggregationError(
            "genuine mainnet source roots must be unique"
        )

    new_attestations: dict[str, GenuineMainnetAttestation] = {}
    revisions: set[str] = set()
    for root in roots:
        attestation = _load_attestation(root)
        _validate_attested_store(root, attestation)
        existing_new = new_attestations.get(attestation.run_id)
        if existing_new is not None and existing_new != attestation:
            raise EvidenceAggregationError(
                "conflicting genuine mainnet attestation for run: "
                f"{attestation.run_id}"
            )
        new_attestations[attestation.run_id] = attestation
        revisions.add(attestation.code_revision)
    if len(revisions) != 1:
        raise EvidenceAggregationError(
            "genuine mainnet sources must share one code revision"
        )
    source_revision = next(iter(revisions))

    corpus_path = target_root / CORPUS_NAME
    present = (
        target_journal.exists(),
        target_facts.exists(),
        corpus_path.exists(),
    )
    if any(present) and not all(present):
        raise EvidenceAggregationError(
            "genuine mainnet corpus target is partially initialized"
        )
    existed = all(present)

    existing_attestations: dict[str, dict[str, object]] = {}
    if existed:
        existing_revision, existing_attestations = _validate_existing_corpus(
            target_root
        )
        if existing_revision != source_revision:
            raise EvidenceAggregationError(
                "target genuine mainnet corpus must share the source code revision"
            )

    merged_attestations = dict(existing_attestations)
    for run_id, attestation in new_attestations.items():
        payload = attestation.canonical_payload()
        existing_payload = merged_attestations.get(run_id)
        if existing_payload is not None and existing_payload != payload:
            raise EvidenceAggregationError(
                f"conflicting genuine mainnet source bytes for run: {run_id}"
            )
        merged_attestations[run_id] = payload

    with tempfile.TemporaryDirectory(
        prefix="cocomelon-mainnet-corpus-"
    ) as temporary:
        staging = Path(temporary)
        staging_journal = staging / JOURNAL_NAME
        staging_facts = staging / FACTS_NAME
        if existed:
            shutil.copy2(target_journal, staging_journal)
            shutil.copy2(target_facts, staging_facts)
        result = aggregate_evaluation_evidence(
            staging_journal,
            staging_facts,
            roots,
        )
        if result.code_revision != source_revision:
            raise EvidenceAggregationError(
                "aggregated corpus revision does not match attestation"
            )
        if set(result.run_ids) != set(merged_attestations):
            raise EvidenceAggregationError(
                "aggregated corpus runs do not match source attestations"
            )
        (staging / CORPUS_NAME).write_text(
            json.dumps(
                _corpus_payload(result, merged_attestations),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            _commit_staged_corpus(staging, target_root, existed=existed)
        except OSError as exc:
            raise EvidenceAggregationError(
                "unable to commit genuine mainnet corpus"
            ) from exc
    return result
