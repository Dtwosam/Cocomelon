from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from cocomelon.domain.evaluation import (
    CandidateDefinition,
    EvaluationDatasetManifest,
    EvaluationPolicy,
    FrozenCandidateSet,
    FrozenSplitManifest,
    OOSStatus,
    SplitName,
    TimePartition,
    TradeEvaluationSample,
)
from cocomelon.evaluation.store import EvaluationConsistencyError, EvaluationFactStore


def freeze_split_manifest(
    dataset: EvaluationDatasetManifest,
    *,
    train: TimePartition,
    validation: TimePartition,
    test: TimePartition,
    policy: EvaluationPolicy,
) -> FrozenSplitManifest:
    if train.start_ms < dataset.start_ms or test.end_ms > dataset.end_ms:
        raise ValueError("split partitions must remain inside the frozen dataset window")
    return FrozenSplitManifest(
        dataset_manifest_id=dataset.manifest_id,
        train=train,
        validation=validation,
        test=test,
        embargo_ms=policy.split_embargo_ms,
        policy_id=policy.policy_id,
    )


def _partition_for_sample(
    sample: TradeEvaluationSample,
    split: FrozenSplitManifest,
) -> TimePartition | None:
    for partition in (split.train, split.validation, split.test):
        if (
            partition.start_ms <= sample.opened_at_ms
            and sample.closed_at_ms < partition.end_ms
        ):
            return partition
    return None


def _internal_boundaries(split: FrozenSplitManifest) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                split.train.end_ms,
                split.validation.start_ms,
                split.validation.end_ms,
                split.test.start_ms,
            }
        )
    )


def split_exclusion_reason(
    sample: TradeEvaluationSample,
    split: FrozenSplitManifest,
) -> str | None:
    partition = _partition_for_sample(sample, split)
    if partition is None:
        if any(
            sample.opened_at_ms < boundary <= sample.closed_at_ms
            for boundary in _internal_boundaries(split)
        ):
            return "CROSSES_SPLIT_BOUNDARY"
        return "OUTSIDE_SPLIT"

    if split.embargo_ms > 0:
        for boundary in _internal_boundaries(split):
            embargo_start = boundary - split.embargo_ms
            embargo_end = boundary + split.embargo_ms
            if sample.closed_at_ms >= embargo_start and sample.opened_at_ms < embargo_end:
                return "SPLIT_EMBARGO"
    return None


def split_samples(
    samples: Sequence[TradeEvaluationSample],
    split: FrozenSplitManifest,
) -> Mapping[SplitName, tuple[TradeEvaluationSample, ...]]:
    grouped: dict[SplitName, list[TradeEvaluationSample]] = {
        SplitName.TRAIN: [],
        SplitName.VALIDATION: [],
        SplitName.TEST: [],
    }
    for sample in samples:
        if split_exclusion_reason(sample, split) is not None:
            continue
        partition = _partition_for_sample(sample, split)
        if partition is None:
            continue
        grouped[partition.name].append(sample)

    return {
        name: tuple(
            sorted(
                values,
                key=lambda item: (
                    item.decision_timestamp_ms,
                    item.opened_at_ms,
                    item.closed_at_ms,
                    item.trade_id,
                ),
            )
        )
        for name, values in grouped.items()
    }


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _partition_payload(partition: TimePartition) -> dict[str, object]:
    return {
        "name": partition.name.value,
        "start_ms": partition.start_ms,
        "end_ms": partition.end_ms,
    }


def _split_payload(split: FrozenSplitManifest) -> str:
    return _canonical_json(
        {
            "dataset_manifest_id": split.dataset_manifest_id,
            "train": _partition_payload(split.train),
            "validation": _partition_payload(split.validation),
            "test": _partition_payload(split.test),
            "embargo_ms": split.embargo_ms,
            "policy_id": split.policy_id,
            "schema_version": split.schema_version,
        }
    )


def _candidate_payload(candidate: CandidateDefinition) -> dict[str, object]:
    return {
        "name": candidate.name,
        "strategy_version": candidate.strategy_version,
        "risk_version": candidate.risk_version,
        "execution_config_version": candidate.execution_config_version,
        "code_revision": candidate.code_revision,
        "config_digest": candidate.config_digest,
        "schema_version": candidate.schema_version,
    }


def _candidate_set_payload(candidates: FrozenCandidateSet) -> str:
    return _canonical_json(
        {
            "candidates": tuple(_candidate_payload(item) for item in candidates.candidates),
            "sensitivity_profile_ids": candidates.sensitivity_profile_ids,
            "policy_id": candidates.policy_id,
            "schema_version": candidates.schema_version,
        }
    )


def _record_consistent(
    store: EvaluationFactStore,
    *,
    table: str,
    key_field: str,
    key: str,
    payload: str,
) -> None:
    existing = store.connection.execute(
        f"SELECT payload_json FROM {table} WHERE {key_field} = ?",  # noqa: S608
        (key,),
    ).fetchone()
    if existing is not None:
        if existing[0] != payload:
            raise EvaluationConsistencyError(f"conflicting {table} record: {key}")
        return
    store.connection.execute(
        f"INSERT INTO {table}({key_field}, payload_json) VALUES (?, ?)",  # noqa: S608
        (key, payload),
    )


def consume_untouched_test(
    store: EvaluationFactStore,
    split: FrozenSplitManifest,
    candidates: FrozenCandidateSet,
    policy: EvaluationPolicy,
) -> OOSStatus:
    if split.policy_id != policy.policy_id:
        raise ValueError("split policy does not match evaluation policy")
    if split.embargo_ms != policy.split_embargo_ms:
        raise ValueError("split embargo does not match evaluation policy")
    if candidates.policy_id != policy.policy_id:
        raise ValueError("candidate set must be frozen to the evaluation policy")

    try:
        store.connection.execute("BEGIN IMMEDIATE")
        _record_consistent(
            store,
            table="evaluation_split_manifests",
            key_field="split_manifest_id",
            key=split.split_manifest_id,
            payload=_split_payload(split),
        )
        _record_consistent(
            store,
            table="evaluation_candidate_sets",
            key_field="candidate_set_id",
            key=candidates.candidate_set_id,
            payload=_candidate_set_payload(candidates),
        )
        existing = store.connection.execute(
            """
            SELECT candidate_set_id, policy_id
            FROM evaluation_oos_consumptions
            WHERE test_partition_digest = ?
            """,
            (split.test_partition_digest,),
        ).fetchone()
        if existing is None:
            store.connection.execute(
                """
                INSERT INTO evaluation_oos_consumptions(
                    test_partition_digest,
                    candidate_set_id,
                    policy_id,
                    consumed_by_evaluation_id
                ) VALUES (?, ?, ?, NULL)
                """,
                (
                    split.test_partition_digest,
                    candidates.candidate_set_id,
                    policy.policy_id,
                ),
            )
            store.connection.commit()
            return OOSStatus.UNTOUCHED

        store.connection.commit()
        if existing == (candidates.candidate_set_id, policy.policy_id):
            return OOSStatus.REPRODUCTION
        return OOSStatus.CONTAMINATED
    except Exception:
        store.connection.rollback()
        raise
