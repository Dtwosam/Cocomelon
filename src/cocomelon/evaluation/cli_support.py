from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cocomelon.domain.evaluation import (
    EvaluationPolicy,
    EvaluationResult,
    FrozenSplitManifest,
    SplitName,
    TimePartition,
)
from cocomelon.evaluation.result_codec import (
    EvaluationResultCodecError,
    evaluation_result_from_payload,
)
from cocomelon.evaluation.splits import freeze_split_manifest
from cocomelon.evaluation.store import EvaluationFactStore


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
    if set(value) != {"start_ms", "end_ms"}:
        raise ValueError(f"{name.value} must contain only start_ms and end_ms")
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
