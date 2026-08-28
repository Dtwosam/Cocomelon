from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path

from cocomelon.domain.evaluation import CandidateDefinition, EvaluationPolicy, FrozenCandidateSet
from cocomelon.evaluation.cli_support import (
    evaluation_result_payload,
    freeze_evaluation_dataset_payload,
    freeze_evaluation_splits_payload,
    run_evaluation,
)
from cocomelon.evaluation.mainnet_evidence import (
    ATTESTATION_NAME,
    mainnet_evidence_progress_payload,
)
from cocomelon.evaluation.mainnet_phase9 import (
    SNAPSHOT_SCHEMA_VERSION,
    MainnetPhase9Error,
    _attested_sources,
    _build_dataset,
    _canonical_digest,
    _candidate_from_sources,
    _partition_payload,
    _policy_payload,
    _read_attested_run_ids,
    _read_mapping,
    _readiness_payload,
    _sha256,
    _verify_snapshot_files,
    _write_json,
)
from cocomelon.evaluation.mainnet_protocol import (
    build_v2_protocol,
    evaluate_v2_readiness,
    select_v2_snapshot_run_ids,
)
from cocomelon.evaluation.sensitivity import predeclared_cost_stress_profiles

V3_SNAPSHOT_NAME = "v3-phase9-frozen-snapshot"
V3_EVALUATION_NAME = "v3-phase9-evaluation"
V3_CANDIDATE_NAME = "v3-baseline-fixed"
V3_SOURCE_PROTOCOL: dict[str, object] = {
    "schema_version": 1,
    "protocol": "v3-lifecycle-aware-mainnet",
    "pinned_code_revision": "f8f84200dbc8b6fb262c5f6f99993b40714357be",
    "replay_engine_version": "phase8-v2-lifecycle-aware",
    "config_version": "phase9-baseline-replay-v2-lifecycle-aware",
    "entry_window_seconds": 2700,
    "capture_window_seconds": 14400,
    "economic_claim": "none",
    "live_orders": False,
}


def _read_v3_corpus_protocol(corpus_root: str | Path) -> dict[str, object]:
    root = Path(corpus_root).resolve()
    protocol = _read_mapping(root / "protocol.json", "V3 corpus protocol")
    if protocol != V3_SOURCE_PROTOCOL:
        raise MainnetPhase9Error("V3 corpus protocol identity is invalid")
    return protocol


def _v3_candidate_from_sources(
    journal_path: Path,
    run_ids: tuple[str, ...],
) -> CandidateDefinition:
    base = _candidate_from_sources(journal_path, run_ids)
    return CandidateDefinition(
        name=V3_CANDIDATE_NAME,
        strategy_version=base.strategy_version,
        risk_version=base.risk_version,
        execution_config_version=base.execution_config_version,
        code_revision=base.code_revision,
        config_digest=base.config_digest,
    )


def _v3_snapshot_hashes(root: Path) -> dict[str, str]:
    names = (
        "journal.sqlite3",
        "facts.sqlite3",
        ATTESTATION_NAME,
        "protocol.json",
        "split-spec.json",
        "candidate-spec.json",
        "walkforward-spec.json",
        "phase9-readiness.json",
    )
    return {name: _sha256(root / name) for name in names}


def prepare_phase9_v3_snapshot(
    corpus_root: str | Path,
    out_root: str | Path,
) -> dict[str, object]:
    corpus = Path(corpus_root).resolve()
    source_protocol = _read_v3_corpus_protocol(corpus)
    source_protocol_digest = _canonical_digest(source_protocol)
    out = Path(out_root).resolve()
    if out.exists():
        raise MainnetPhase9Error("Phase 9 V3 snapshot output must not already exist")
    if corpus == out or corpus in out.parents:
        raise MainnetPhase9Error(
            "Phase 9 V3 snapshot output must be separate from the corpus"
        )

    journal_source = corpus / "journal.sqlite3"
    facts_source = corpus / "facts.sqlite3"
    attestation_source = corpus / ATTESTATION_NAME
    progress = mainnet_evidence_progress_payload(journal_source, facts_source)
    attested_run_ids = _read_attested_run_ids(attestation_source)
    if progress.get("attested_run_count") != len(attested_run_ids):
        raise MainnetPhase9Error("attested run count does not match run_ids")
    code_revision = progress.get("code_revision")
    expected_revision = source_protocol["pinned_code_revision"]
    if code_revision != expected_revision:
        raise MainnetPhase9Error("V3 corpus code revision does not match protocol identity")
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise MainnetPhase9Error("attested code revision is invalid")

    sources = _attested_sources(
        journal_source,
        attested_run_ids,
        code_revision=code_revision,
    )
    run_ids = select_v2_snapshot_run_ids(sources)
    if not run_ids or not set(run_ids).issubset(attested_run_ids):
        raise MainnetPhase9Error("selected V3 snapshot runs must be attested")

    out.mkdir(parents=True)
    shutil.copy2(journal_source, out / "journal.sqlite3")
    shutil.copy2(facts_source, out / "facts.sqlite3")
    shutil.copy2(attestation_source, out / ATTESTATION_NAME)
    shutil.copy2(corpus / "protocol.json", out / "protocol.json")

    dataset_payload = freeze_evaluation_dataset_payload(
        out / "journal.sqlite3",
        out / "facts.sqlite3",
        run_ids,
    )
    dataset_id = dataset_payload.get("dataset_manifest_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise MainnetPhase9Error("frozen V3 dataset id is invalid")
    built = _build_dataset(
        out / "journal.sqlite3",
        out / "facts.sqlite3",
        run_ids=run_ids,
        code_revision=code_revision,
    )
    if built.manifest.manifest_id != dataset_id:
        raise MainnetPhase9Error("rebuilt V3 dataset does not match frozen dataset")
    if not built.manifest.data_complete or built.manifest.gap_refs:
        raise MainnetPhase9Error(
            "selected V3 snapshot dataset must remain complete and gap-free"
        )

    policy = EvaluationPolicy()
    protocol = build_v2_protocol(built.manifest, policy=policy)
    readiness = evaluate_v2_readiness(
        built.manifest,
        built.samples,
        policy=policy,
    )
    policy_json = _policy_payload(policy)
    split_spec = {
        "policy": policy_json,
        "train": _partition_payload(protocol.split.train),
        "validation": _partition_payload(protocol.split.validation),
        "test": _partition_payload(protocol.split.test),
    }
    candidate = _v3_candidate_from_sources(out / "journal.sqlite3", run_ids)
    profile_ids = tuple(
        sorted(profile.profile_id for profile in predeclared_cost_stress_profiles())
    )
    candidate_set = FrozenCandidateSet(
        candidates=(candidate,),
        sensitivity_profile_ids=profile_ids,
        policy_id=policy.policy_id,
    )
    candidate_spec = {
        "policy": policy_json,
        "candidates": [
            {
                "name": candidate.name,
                "strategy_version": candidate.strategy_version,
                "risk_version": candidate.risk_version,
                "execution_config_version": candidate.execution_config_version,
                "code_revision": candidate.code_revision,
                "config_digest": candidate.config_digest,
            }
        ],
        "sensitivity_profile_ids": list(profile_ids),
    }
    walkforward_spec = {
        "first_window_start_ms": protocol.walkforward.first_window_start_ms,
        "development_duration_ms": protocol.walkforward.development_duration_ms,
        "validation_duration_ms": protocol.walkforward.validation_duration_ms,
        "evaluation_duration_ms": protocol.walkforward.evaluation_duration_ms,
        "step_ms": protocol.walkforward.step_ms,
        "embargo_ms": protocol.walkforward.embargo_ms,
        "expanding": protocol.walkforward.expanding,
    }
    readiness_json = _readiness_payload(readiness)
    _write_json(out / "split-spec.json", split_spec)
    _write_json(out / "candidate-spec.json", candidate_spec)
    _write_json(out / "walkforward-spec.json", walkforward_spec)
    _write_json(out / "phase9-readiness.json", readiness_json)

    split_id: str | None = None
    if readiness.ready:
        split_payload = freeze_evaluation_splits_payload(
            out / "facts.sqlite3",
            dataset_id,
            out / "split-spec.json",
        )
        raw_split_id = split_payload.get("split_manifest_id")
        if not isinstance(raw_split_id, str) or not raw_split_id.strip():
            raise MainnetPhase9Error("frozen V3 split id is invalid")
        split_id = raw_split_id

    snapshot_base: dict[str, object] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_name": V3_SNAPSHOT_NAME,
        "source_protocol": source_protocol["protocol"],
        "source_protocol_digest": source_protocol_digest,
        "one_shot_oos": True,
        "economic_claim": "none",
        "mainnet_attestation_id": progress["mainnet_attestation_id"],
        "full_attested_run_count": len(attested_run_ids),
        "code_revision": code_revision,
        "run_ids": list(run_ids),
        "protocol_test_end_ms": protocol.split.test.end_ms,
        "dataset_manifest_id": dataset_id,
        "split_manifest_id": split_id,
        "candidate_set_id": candidate_set.candidate_set_id,
        "policy_id": policy.policy_id,
        "ready_for_untouched_evaluation": readiness.ready,
        "reason_codes": list(readiness.reason_codes),
        "file_sha256": _v3_snapshot_hashes(out),
        "network_access": False,
        "live_orders": False,
    }
    snapshot = {**snapshot_base, "snapshot_id": _canonical_digest(snapshot_base)}
    _write_json(out / "snapshot.json", snapshot)
    return snapshot


def _verify_v3_source_protocol(
    root: Path,
    snapshot: Mapping[str, object],
) -> str:
    protocol = _read_mapping(root / "protocol.json", "V3 snapshot source protocol")
    if protocol != V3_SOURCE_PROTOCOL:
        raise MainnetPhase9Error("V3 snapshot source protocol identity is invalid")
    protocol_digest = _canonical_digest(protocol)
    if snapshot.get("source_protocol") != protocol["protocol"]:
        raise MainnetPhase9Error("V3 snapshot source protocol name is invalid")
    if snapshot.get("source_protocol_digest") != protocol_digest:
        raise MainnetPhase9Error("V3 snapshot source protocol digest is invalid")
    return protocol_digest


def evaluate_phase9_v3_snapshot(snapshot_root: str | Path) -> dict[str, object]:
    root = Path(snapshot_root).resolve()
    snapshot = _read_mapping(root / "snapshot.json", "Phase 9 V3 snapshot")
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise MainnetPhase9Error("V3 snapshot_id is invalid")
    base = {key: value for key, value in snapshot.items() if key != "snapshot_id"}
    if _canonical_digest(base) != snapshot_id:
        raise MainnetPhase9Error("V3 snapshot metadata digest is invalid")
    if snapshot.get("snapshot_name") != V3_SNAPSHOT_NAME:
        raise MainnetPhase9Error("snapshot is not V3 Phase 9 evidence")
    if snapshot.get("one_shot_oos") is not True:
        raise MainnetPhase9Error("V3 snapshot must be one-shot OOS evidence")
    if snapshot.get("ready_for_untouched_evaluation") is not True:
        raise MainnetPhase9Error("V3 snapshot is not ready for untouched evaluation")
    protocol_digest = _verify_v3_source_protocol(root, snapshot)
    _verify_snapshot_files(root, snapshot)

    dataset_id = snapshot.get("dataset_manifest_id")
    split_id = snapshot.get("split_manifest_id")
    if not isinstance(dataset_id, str) or not isinstance(split_id, str):
        raise MainnetPhase9Error("V3 snapshot dataset or split id is invalid")
    result = run_evaluation(
        root / "journal.sqlite3",
        root / "facts.sqlite3",
        dataset_id,
        split_id,
        root / "candidate-spec.json",
        root / "walkforward-spec.json",
    )
    result_payload = evaluation_result_payload(result)
    payload: dict[str, object] = {
        **result_payload,
        "evaluation_name": V3_EVALUATION_NAME,
        "snapshot_id": snapshot_id,
        "mainnet_attestation_id": snapshot["mainnet_attestation_id"],
        "source_protocol": V3_SOURCE_PROTOCOL["protocol"],
        "source_protocol_digest": protocol_digest,
        "one_shot_oos": True,
        "economic_claim": "phase9_baseline_edge_assessment",
        "network_access": False,
        "live_orders": False,
    }
    _write_json(root / "evaluation.json", payload)
    return payload
