from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cocomelon.domain.evaluation import (
    CandidateDefinition,
    EvaluationPolicy,
    EvaluationResult,
    FrozenCandidateSet,
    FrozenSplitManifest,
    SplitName,
    TimePartition,
)
from cocomelon.evaluation.dataset import build_evaluation_dataset
from cocomelon.evaluation.engine import EvaluationEngine, EvaluationRequest
from cocomelon.evaluation.result_codec import (
    EvaluationResultCodecError,
    evaluation_result_from_payload,
)
from cocomelon.evaluation.sensitivity import (
    CostStressProfile,
    predeclared_cost_stress_profiles,
)
from cocomelon.evaluation.splits import freeze_split_manifest
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evaluation.walkforward import WalkForwardPlan
from cocomelon.journal.store import JournalStore


def _read_json_mapping(path: str | Path, field: str) -> dict[str, Any]:
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"{field} must be an existing JSON file")
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must contain valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{field} must contain a JSON object")
    return {str(key): value for key, value in raw.items()}


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string array")
    result = tuple(value)
    if not result or any(not item.strip() for item in result):
        raise ValueError(f"{field} values must not be empty")
    return result


def evaluation_policy_from_payload(value: object) -> EvaluationPolicy:
    if not isinstance(value, dict):
        raise ValueError("policy must be an object")
    required = {
        "policy_version",
        "min_oos_trades",
        "min_oos_days",
        "min_walkforward_windows",
        "min_trades_per_walkforward_window",
        "min_score_bucket_trades",
        "positive_walkforward_fraction",
        "bootstrap_confidence",
        "bootstrap_block_days",
        "bootstrap_resamples",
        "split_embargo_ms",
        "no_trade_horizons_ms",
    }
    if set(value) != required:
        missing = sorted(required - set(value))
        extra = sorted(set(value) - required)
        raise ValueError(f"policy keys must be exact; missing={missing}, extra={extra}")
    horizons = value["no_trade_horizons_ms"]
    if not isinstance(horizons, list):
        raise ValueError("no_trade_horizons_ms must be an array")
    return EvaluationPolicy(
        policy_version=_string(value["policy_version"], "policy_version"),
        min_oos_trades=_int(value["min_oos_trades"], "min_oos_trades"),
        min_oos_days=_int(value["min_oos_days"], "min_oos_days"),
        min_walkforward_windows=_int(
            value["min_walkforward_windows"], "min_walkforward_windows"
        ),
        min_trades_per_walkforward_window=_int(
            value["min_trades_per_walkforward_window"],
            "min_trades_per_walkforward_window",
        ),
        min_score_bucket_trades=_int(
            value["min_score_bucket_trades"], "min_score_bucket_trades"
        ),
        positive_walkforward_fraction=_decimal(
            value["positive_walkforward_fraction"], "positive_walkforward_fraction"
        ),
        bootstrap_confidence=_decimal(
            value["bootstrap_confidence"], "bootstrap_confidence"
        ),
        bootstrap_block_days=_int(
            value["bootstrap_block_days"], "bootstrap_block_days"
        ),
        bootstrap_resamples=_int(value["bootstrap_resamples"], "bootstrap_resamples"),
        split_embargo_ms=_int(value["split_embargo_ms"], "split_embargo_ms"),
        no_trade_horizons_ms=tuple(
            _int(item, "no_trade_horizons_ms") for item in horizons
        ),
    )


def _time_partition(value: object, name: SplitName) -> TimePartition:
    if not isinstance(value, dict):
        raise ValueError(f"{name.value} must be an object")
    if set(value) not in ({"start_ms", "end_ms"}, {"name", "start_ms", "end_ms"}):
        raise ValueError(f"{name.value} has unsupported keys")
    if "name" in value and value["name"] != name.value:
        raise ValueError(f"{name.value} partition name does not match its field")
    return TimePartition(
        name=name,
        start_ms=_int(value["start_ms"], f"{name.value}.start_ms"),
        end_ms=_int(value["end_ms"], f"{name.value}.end_ms"),
    )


def _partition_payload(partition: TimePartition) -> dict[str, object]:
    return {
        "name": partition.name.value,
        "start_ms": partition.start_ms,
        "end_ms": partition.end_ms,
    }


def _split_payload(split: FrozenSplitManifest) -> dict[str, object]:
    return {
        "dataset_manifest_id": split.dataset_manifest_id,
        "train": _partition_payload(split.train),
        "validation": _partition_payload(split.validation),
        "test": _partition_payload(split.test),
        "embargo_ms": split.embargo_ms,
        "policy_id": split.policy_id,
        "schema_version": split.schema_version,
    }


def freeze_evaluation_dataset_payload(
    journal_path: str | Path,
    facts_path: str | Path,
    replay_run_ids: tuple[str, ...],
) -> dict[str, object]:
    if not replay_run_ids or any(not run_id.strip() for run_id in replay_run_ids):
        raise ValueError("at least one non-empty replay run id is required")
    run_ids = tuple(sorted(set(replay_run_ids)))
    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    try:
        source_manifests = []
        for run_id in run_ids:
            replay_result = journal.load_replay_result(run_id)
            if replay_result is None:
                raise ValueError(f"replay result not found: {run_id}")
            source_manifest = journal.load_manifest(replay_result.manifest_id)
            if source_manifest is None:
                raise ValueError(f"replay manifest not found: {replay_result.manifest_id}")
            source_manifests.append(source_manifest)
        revisions = {item.code_revision for item in source_manifests}
        if len(revisions) != 1:
            raise ValueError("replay runs must share one source code revision")
        code_revision = next(iter(revisions))
        built = build_evaluation_dataset(
            journal,
            facts,
            replay_run_ids=run_ids,
            code_revision=code_revision,
        )
    finally:
        facts.close()
        journal.close()

    manifest = built.manifest
    return {
        "dataset_manifest_id": manifest.manifest_id,
        "source_run_ids": list(run_ids),
        "source_manifest_ids": [item.manifest_id for item in source_manifests],
        "evidence_class": (
            None if manifest.evidence_class is None else manifest.evidence_class.value
        ),
        "start_ms": manifest.start_ms,
        "end_ms": manifest.end_ms,
        "code_revision": manifest.code_revision,
        "trade_count": len(manifest.trade_ids),
        "excluded_trade_count": len(built.excluded_trade_ids),
        "exclusion_reasons": [list(item) for item in built.exclusion_reasons],
        "data_complete": manifest.data_complete,
        "gap_refs": list(manifest.gap_refs),
        "network_access": False,
    }


def freeze_evaluation_splits_payload(
    facts_path: str | Path,
    dataset_id: str,
    spec_path: str | Path,
) -> dict[str, object]:
    if not dataset_id.strip():
        raise ValueError("dataset_id must not be empty")
    spec = _read_json_mapping(spec_path, "split spec")
    if set(spec) != {"policy", "train", "validation", "test"}:
        raise ValueError("split spec must contain policy, train, validation, and test")
    policy = evaluation_policy_from_payload(spec["policy"])

    store = EvaluationFactStore(facts_path)
    try:
        dataset = store.load_dataset_manifest(dataset_id)
        if dataset is None:
            raise ValueError(f"evaluation dataset not found: {dataset_id}")
        split = freeze_split_manifest(
            dataset,
            train=_time_partition(spec["train"], SplitName.TRAIN),
            validation=_time_partition(spec["validation"], SplitName.VALIDATION),
            test=_time_partition(spec["test"], SplitName.TEST),
            policy=policy,
        )
        canonical = json.dumps(
            _split_payload(split),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        try:
            store.connection.execute("BEGIN IMMEDIATE")
            existing = store.connection.execute(
                "SELECT payload_json FROM evaluation_split_manifests WHERE split_manifest_id = ?",
                (split.split_manifest_id,),
            ).fetchone()
            if existing is not None and existing[0] != canonical:
                raise ValueError(f"conflicting evaluation split: {split.split_manifest_id}")
            if existing is None:
                store.connection.execute(
                    """
                    INSERT INTO evaluation_split_manifests(
                        split_manifest_id, payload_json
                    ) VALUES (?, ?)
                    """,
                    (split.split_manifest_id, canonical),
                )
            store.connection.commit()
        except Exception:
            store.connection.rollback()
            raise
    finally:
        store.close()

    return {
        "split_manifest_id": split.split_manifest_id,
        **_split_payload(split),
        "network_access": False,
    }


def _load_split(store: EvaluationFactStore, split_id: str) -> FrozenSplitManifest:
    row = store.connection.execute(
        "SELECT payload_json FROM evaluation_split_manifests WHERE split_manifest_id = ?",
        (split_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"evaluation split not found: {split_id}")
    try:
        raw = json.loads(str(row[0]))
    except json.JSONDecodeError as exc:
        raise ValueError("stored evaluation split must contain valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("stored evaluation split must be an object")
    required = {
        "dataset_manifest_id",
        "train",
        "validation",
        "test",
        "embargo_ms",
        "policy_id",
        "schema_version",
    }
    if set(raw) != required:
        raise ValueError("stored evaluation split has unsupported keys")
    split = FrozenSplitManifest(
        dataset_manifest_id=_string(raw["dataset_manifest_id"], "dataset_manifest_id"),
        train=_time_partition(raw["train"], SplitName.TRAIN),
        validation=_time_partition(raw["validation"], SplitName.VALIDATION),
        test=_time_partition(raw["test"], SplitName.TEST),
        embargo_ms=_int(raw["embargo_ms"], "embargo_ms"),
        policy_id=_string(raw["policy_id"], "policy_id"),
        schema_version=_int(raw["schema_version"], "schema_version"),
    )
    if split.split_manifest_id != split_id:
        raise ValueError("stored evaluation split id does not match canonical payload")
    return split


def _candidate_set_from_payload(
    value: object,
) -> tuple[EvaluationPolicy, FrozenCandidateSet, tuple[CostStressProfile, ...]]:
    if not isinstance(value, dict):
        raise ValueError("candidate spec must be an object")
    if set(value) != {"policy", "candidates", "sensitivity_profile_ids"}:
        raise ValueError(
            "candidate spec must contain policy, candidates, and sensitivity_profile_ids"
        )
    policy = evaluation_policy_from_payload(value["policy"])
    raw_candidates = value["candidates"]
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("candidates must be a non-empty array")
    candidates = []
    required_candidate_keys = {
        "name",
        "strategy_version",
        "risk_version",
        "execution_config_version",
        "code_revision",
        "config_digest",
    }
    for index, raw_candidate in enumerate(raw_candidates):
        if not isinstance(raw_candidate, dict) or set(raw_candidate) != required_candidate_keys:
            raise ValueError(f"candidate {index} has unsupported keys")
        candidates.append(
            CandidateDefinition(
                name=_string(raw_candidate["name"], f"candidate {index} name"),
                strategy_version=_string(
                    raw_candidate["strategy_version"],
                    f"candidate {index} strategy_version",
                ),
                risk_version=_string(
                    raw_candidate["risk_version"],
                    f"candidate {index} risk_version",
                ),
                execution_config_version=_string(
                    raw_candidate["execution_config_version"],
                    f"candidate {index} execution_config_version",
                ),
                code_revision=_string(
                    raw_candidate["code_revision"],
                    f"candidate {index} code_revision",
                ),
                config_digest=_string(
                    raw_candidate["config_digest"],
                    f"candidate {index} config_digest",
                ),
            )
        )
    profile_ids = _string_list(
        value["sensitivity_profile_ids"], "sensitivity_profile_ids"
    )
    available = {item.profile_id: item for item in predeclared_cost_stress_profiles()}
    try:
        selected_profiles = tuple(available[profile_id] for profile_id in profile_ids)
    except KeyError as exc:
        raise ValueError(f"unknown sensitivity profile: {exc.args[0]}") from exc
    candidate_set = FrozenCandidateSet(
        candidates=tuple(candidates),
        sensitivity_profile_ids=profile_ids,
        policy_id=policy.policy_id,
    )
    return policy, candidate_set, selected_profiles


def _walkforward_plan_from_payload(
    value: object,
    *,
    dataset_manifest_id: str,
    policy_id: str,
) -> WalkForwardPlan:
    if not isinstance(value, dict):
        raise ValueError("walk-forward spec must be an object")
    required = {
        "first_window_start_ms",
        "development_duration_ms",
        "validation_duration_ms",
        "evaluation_duration_ms",
        "step_ms",
        "embargo_ms",
        "expanding",
    }
    if set(value) != required:
        raise ValueError("walk-forward spec has unsupported keys")
    return WalkForwardPlan(
        dataset_manifest_id=dataset_manifest_id,
        first_window_start_ms=_int(
            value["first_window_start_ms"], "first_window_start_ms"
        ),
        development_duration_ms=_int(
            value["development_duration_ms"], "development_duration_ms"
        ),
        validation_duration_ms=_int(
            value["validation_duration_ms"], "validation_duration_ms"
        ),
        evaluation_duration_ms=_int(
            value["evaluation_duration_ms"], "evaluation_duration_ms"
        ),
        step_ms=_int(value["step_ms"], "step_ms"),
        embargo_ms=_int(value["embargo_ms"], "embargo_ms"),
        expanding=_boolean(value["expanding"], "expanding"),
        policy_id=policy_id,
    )


def run_evaluation(
    journal_path: str | Path,
    facts_path: str | Path,
    dataset_id: str,
    split_id: str,
    candidate_spec_path: str | Path,
    walkforward_spec_path: str | Path,
) -> EvaluationResult:
    if not dataset_id.strip() or not split_id.strip():
        raise ValueError("dataset_id and split_id must not be empty")
    candidate_spec = _read_json_mapping(candidate_spec_path, "candidate spec")
    walkforward_spec = _read_json_mapping(walkforward_spec_path, "walk-forward spec")
    policy, candidates, profiles = _candidate_set_from_payload(candidate_spec)

    journal = JournalStore(journal_path)
    facts = EvaluationFactStore(facts_path)
    try:
        dataset = facts.load_dataset_manifest(dataset_id)
        if dataset is None:
            raise ValueError(f"evaluation dataset not found: {dataset_id}")
        split = _load_split(facts, split_id)
        plan = _walkforward_plan_from_payload(
            walkforward_spec,
            dataset_manifest_id=dataset.manifest_id,
            policy_id=policy.policy_id,
        )
        request = EvaluationRequest(
            dataset=dataset,
            split=split,
            candidates=candidates,
            policy=policy,
            walkforward_plan=plan,
            sensitivity_profiles=profiles,
        )
        return EvaluationEngine(journal, facts).run(request)
    finally:
        facts.close()
        journal.close()


def evaluation_result_payload(result: EvaluationResult) -> dict[str, object]:
    preview = result.promotion_preview
    return {
        "evaluation_id": result.evaluation_id,
        "result_digest": result.result_digest,
        "edge_status": result.edge_status.value,
        "oos_status": result.oos_status.value,
        "dataset_manifest_id": result.dataset_manifest_id,
        "split_manifest_id": result.split_manifest_id,
        "candidate_set_id": result.candidate_set_id,
        "policy_id": result.policy_id,
        "test_trade_count": result.test_metrics.trade_count,
        "included_sample_count": result.included_sample_count,
        "excluded_sample_count": result.excluded_sample_count,
        "reason_codes": list(result.reason_codes),
        "promotion_preview": {
            "preview_only": preview.preview_only,
            "profit_factor_pass": preview.profit_factor_pass,
            "max_drawdown_pass": preview.max_drawdown_pass,
            "market_concentration_pass": preview.market_concentration_pass,
            "seven_day_concentration_pass": preview.seven_day_concentration_pass,
            "closed_trade_count_pass": preview.closed_trade_count_pass,
            "covered_days_pass": preview.covered_days_pass,
            "invariant_health_pass": preview.invariant_health_pass,
            "reason_codes": list(preview.reason_codes),
        },
        "network_access": False,
    }


def inspect_evaluation_payload(
    facts_path: str | Path,
    evaluation_id: str,
) -> dict[str, object]:
    path = Path(facts_path)
    if not path.is_file():
        raise ValueError("facts must be an existing file")
    if not evaluation_id.strip():
        raise ValueError("evaluation_id must not be empty")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT payload_json FROM evaluation_results WHERE evaluation_id = ?",
            (evaluation_id,),
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError("facts is not a readable Phase 9 SQLite store") from exc
    finally:
        connection.close()
    if row is None:
        raise ValueError(f"evaluation not found: {evaluation_id}")
    try:
        raw = json.loads(str(row[0]))
        result = evaluation_result_from_payload(raw)
    except (json.JSONDecodeError, EvaluationResultCodecError, TypeError, ValueError) as exc:
        raise ValueError("stored evaluation payload is invalid") from exc
    if result.evaluation_id != evaluation_id:
        raise ValueError("stored evaluation id does not match canonical payload")
    return evaluation_result_payload(result)
