from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from cocomelon.domain.evaluation import (
    CandidateDefinition,
    EvaluationPolicy,
    FrozenCandidateSet,
    ReplayEvaluationSource,
    TimePartition,
)
from cocomelon.evaluation.cli_support import (
    evaluation_result_payload,
    freeze_evaluation_dataset_payload,
    freeze_evaluation_splits_payload,
    run_evaluation,
)
from cocomelon.evaluation.dataset import DatasetBuildResult, build_evaluation_dataset
from cocomelon.evaluation.mainnet_evidence import (
    ATTESTATION_NAME,
    mainnet_evidence_progress_payload,
)
from cocomelon.evaluation.mainnet_protocol import (
    MainnetPhase9Readiness,
    build_v2_protocol,
    evaluate_v2_readiness,
    select_v2_snapshot_run_ids,
)
from cocomelon.evaluation.sensitivity import predeclared_cost_stress_profiles
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_NAME = "v2-phase9-frozen-snapshot"
EVALUATION_NAME = "v2-phase9-evaluation"


class MainnetPhase9Error(RuntimeError):
    pass


def _read_mapping(path: Path, field: str) -> dict[str, object]:
    if not path.is_file():
        raise MainnetPhase9Error(f"{field} is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MainnetPhase9Error(f"{field} must contain valid JSON") from exc
    if not isinstance(raw, dict):
        raise MainnetPhase9Error(f"{field} must contain a JSON object")
    return {str(key): value for key, value in raw.items()}


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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


def _policy_payload(policy: EvaluationPolicy) -> dict[str, object]:
    return {
        "policy_version": policy.policy_version,
        "min_oos_trades": policy.min_oos_trades,
        "min_oos_days": policy.min_oos_days,
        "min_walkforward_windows": policy.min_walkforward_windows,
        "min_trades_per_walkforward_window": policy.min_trades_per_walkforward_window,
        "min_score_bucket_trades": policy.min_score_bucket_trades,
        "positive_walkforward_fraction": str(policy.positive_walkforward_fraction),
        "bootstrap_confidence": str(policy.bootstrap_confidence),
        "bootstrap_block_days": policy.bootstrap_block_days,
        "bootstrap_resamples": policy.bootstrap_resamples,
        "split_embargo_ms": policy.split_embargo_ms,
        "no_trade_horizons_ms": list(policy.no_trade_horizons_ms),
    }


def _partition_payload(partition: TimePartition) -> dict[str, object]:
    return {
        "start_ms": partition.start_ms,
        "end_ms": partition.end_ms,
    }


def _read_attested_run_ids(attestation_path: Path) -> tuple[str, ...]:
    attestation = _read_mapping(attestation_path, "mainnet attestation")
    raw = attestation.get("run_ids")
    if not isinstance(raw, list) or not raw or any(
        not isinstance(item, str) or not item.strip() for item in raw
    ):
        raise MainnetPhase9Error("mainnet attestation run_ids are invalid")
    run_ids = tuple(str(item) for item in raw)
    if tuple(sorted(set(run_ids))) != run_ids:
        raise MainnetPhase9Error("mainnet attestation run_ids must be sorted and unique")
    return run_ids


def _attested_sources(
    journal_path: Path,
    run_ids: tuple[str, ...],
    *,
    code_revision: str,
) -> tuple[ReplayEvaluationSource, ...]:
    journal = JournalStore(journal_path)
    try:
        sources: list[ReplayEvaluationSource] = []
        for run_id in run_ids:
            result = journal.load_replay_result(run_id)
            if result is None:
                raise MainnetPhase9Error(f"replay result is missing: {run_id}")
            manifest = journal.load_manifest(result.manifest_id)
            if manifest is None:
                raise MainnetPhase9Error(
                    f"replay manifest is missing: {result.manifest_id}"
                )
            if manifest.code_revision != code_revision:
                raise MainnetPhase9Error("attested source revision is inconsistent")
            if not result.data_complete or result.processed_gaps != 0 or manifest.gap_refs:
                raise MainnetPhase9Error("attested source must remain complete and gap-free")
            sources.append(
                ReplayEvaluationSource(
                    run_id=result.run_id,
                    manifest_id=result.manifest_id,
                    result_digest=result.result_digest,
                    evidence_class=result.evidence_class,
                    start_ms=result.start_ms,
                    end_ms=result.end_ms,
                    data_complete=result.data_complete,
                )
            )
    finally:
        journal.close()
    return tuple(sources)


def _build_dataset(
    journal_path: Path,
    facts_path: Path,
    *,
    run_ids: tuple[str, ...],
    code_revision: str,
) -> DatasetBuildResult:
    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    try:
        return build_evaluation_dataset(
            journal,
            facts,
            replay_run_ids=run_ids,
            code_revision=code_revision,
        )
    finally:
        facts.close()
        journal.close()


def _candidate_from_sources(
    journal_path: Path,
    run_ids: tuple[str, ...],
) -> CandidateDefinition:
    journal = JournalStore(journal_path)
    try:
        manifests = []
        for run_id in run_ids:
            result = journal.load_replay_result(run_id)
            if result is None:
                raise MainnetPhase9Error(f"replay result is missing: {run_id}")
            manifest = journal.load_manifest(result.manifest_id)
            if manifest is None:
                raise MainnetPhase9Error(
                    f"replay manifest is missing: {result.manifest_id}"
                )
            manifests.append(manifest)
    finally:
        journal.close()

    definitions = {
        (
            item.strategy_version,
            item.risk_version,
            item.execution_config_version,
            item.code_revision,
            item.config_digest,
        )
        for item in manifests
    }
    if len(definitions) != 1:
        raise MainnetPhase9Error(
            "attested V2 sources do not share one frozen candidate definition"
        )
    strategy, risk, execution, revision, config_digest = next(iter(definitions))
    if execution is None or not execution.strip():
        raise MainnetPhase9Error(
            "attested V2 sources require an execution_config_version"
        )
    return CandidateDefinition(
        name="v2-baseline-fixed",
        strategy_version=strategy,
        risk_version=risk,
        execution_config_version=execution,
        code_revision=revision,
        config_digest=config_digest,
    )


def _readiness_payload(readiness: MainnetPhase9Readiness) -> dict[str, object]:
    return {
        "dataset_manifest_id": readiness.dataset_manifest_id,
        "test_window_complete": readiness.test_window_complete,
        "test_trade_count": readiness.test_trade_count,
        "test_covered_days": readiness.test_covered_days,
        "eligible_walkforward_windows": readiness.eligible_walkforward_windows,
        "minimum_oos_trades": readiness.minimum_oos_trades,
        "minimum_oos_days": readiness.minimum_oos_days,
        "minimum_walkforward_windows": readiness.minimum_walkforward_windows,
        "minimum_trades_per_walkforward_window": (
            readiness.minimum_trades_per_walkforward_window
        ),
        "ready_for_untouched_evaluation": readiness.ready,
        "reason_codes": list(readiness.reason_codes),
        "one_shot_oos": True,
        "economic_claim": "none",
        "network_access": False,
        "live_orders": False,
    }


def _snapshot_hashes(root: Path) -> dict[str, str]:
    names = (
        "journal.sqlite3",
        "facts.sqlite3",
        ATTESTATION_NAME,
        "split-spec.json",
        "candidate-spec.json",
        "walkforward-spec.json",
        "phase9-readiness.json",
    )
    return {name: _sha256(root / name) for name in names}


def prepare_phase9_v2_snapshot(
    corpus_root: str | Path,
    out_root: str | Path,
) -> dict[str, object]:
    corpus = Path(corpus_root).resolve()
    out = Path(out_root).resolve()
    if out.exists():
        raise MainnetPhase9Error("Phase 9 snapshot output must not already exist")
    if corpus == out or corpus in out.parents:
        raise MainnetPhase9Error("Phase 9 snapshot output must be separate from the corpus")

    journal_source = corpus / "journal.sqlite3"
    facts_source = corpus / "facts.sqlite3"
    attestation_source = corpus / ATTESTATION_NAME
    progress = mainnet_evidence_progress_payload(journal_source, facts_source)
    attested_run_ids = _read_attested_run_ids(attestation_source)
    if progress.get("attested_run_count") != len(attested_run_ids):
        raise MainnetPhase9Error("attested run count does not match run_ids")
    code_revision = progress.get("code_revision")
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise MainnetPhase9Error("attested code revision is invalid")
    sources = _attested_sources(
        journal_source,
        attested_run_ids,
        code_revision=code_revision,
    )
    run_ids = select_v2_snapshot_run_ids(sources)
    if not run_ids or not set(run_ids).issubset(attested_run_ids):
        raise MainnetPhase9Error("selected snapshot runs must be attested")

    out.mkdir(parents=True)
    shutil.copy2(journal_source, out / "journal.sqlite3")
    shutil.copy2(facts_source, out / "facts.sqlite3")
    shutil.copy2(attestation_source, out / ATTESTATION_NAME)

    dataset_payload = freeze_evaluation_dataset_payload(
        out / "journal.sqlite3",
        out / "facts.sqlite3",
        run_ids,
    )
    dataset_id = dataset_payload.get("dataset_manifest_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise MainnetPhase9Error("frozen dataset id is invalid")
    built = _build_dataset(
        out / "journal.sqlite3",
        out / "facts.sqlite3",
        run_ids=run_ids,
        code_revision=code_revision,
    )
    if built.manifest.manifest_id != dataset_id:
        raise MainnetPhase9Error("rebuilt dataset does not match frozen dataset")
    if not built.manifest.data_complete or built.manifest.gap_refs:
        raise MainnetPhase9Error("selected snapshot dataset must remain complete and gap-free")

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
    candidate = _candidate_from_sources(out / "journal.sqlite3", run_ids)
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
            raise MainnetPhase9Error("frozen split id is invalid")
        split_id = raw_split_id

    hashes = _snapshot_hashes(out)
    snapshot_base: dict[str, object] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "snapshot_name": SNAPSHOT_NAME,
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
        "file_sha256": hashes,
        "network_access": False,
        "live_orders": False,
    }
    snapshot = {**snapshot_base, "snapshot_id": _canonical_digest(snapshot_base)}
    _write_json(out / "snapshot.json", snapshot)
    return snapshot


def _verify_snapshot_files(root: Path, snapshot: Mapping[str, object]) -> None:
    raw = snapshot.get("file_sha256")
    if not isinstance(raw, dict) or not raw:
        raise MainnetPhase9Error("snapshot file hashes are invalid")
    for name, expected in raw.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise MainnetPhase9Error("snapshot file hash entry is invalid")
        path = root / name
        if not path.is_file() or _sha256(path) != expected:
            raise MainnetPhase9Error(f"snapshot file hash mismatch: {name}")


def evaluate_phase9_v2_snapshot(snapshot_root: str | Path) -> dict[str, object]:
    root = Path(snapshot_root).resolve()
    snapshot = _read_mapping(root / "snapshot.json", "Phase 9 snapshot")
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise MainnetPhase9Error("snapshot_id is invalid")
    base = {key: value for key, value in snapshot.items() if key != "snapshot_id"}
    if _canonical_digest(base) != snapshot_id:
        raise MainnetPhase9Error("snapshot metadata digest is invalid")
    if snapshot.get("one_shot_oos") is not True:
        raise MainnetPhase9Error("snapshot must be one-shot OOS evidence")
    if snapshot.get("ready_for_untouched_evaluation") is not True:
        raise MainnetPhase9Error("snapshot is not ready for untouched evaluation")
    _verify_snapshot_files(root, snapshot)

    dataset_id = snapshot.get("dataset_manifest_id")
    split_id = snapshot.get("split_manifest_id")
    if not isinstance(dataset_id, str) or not isinstance(split_id, str):
        raise MainnetPhase9Error("snapshot dataset or split id is invalid")
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
        "evaluation_name": EVALUATION_NAME,
        "snapshot_id": snapshot_id,
        "mainnet_attestation_id": snapshot["mainnet_attestation_id"],
        "one_shot_oos": True,
        "economic_claim": "phase9_baseline_edge_assessment",
        "network_access": False,
        "live_orders": False,
    }
    _write_json(root / "evaluation.json", payload)
    return payload