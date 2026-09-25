from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.research.learning_challenger_run import LearningChallengerRunManifest
from cocomelon.research.learning_dataset_bundle import VerifiedLearningDatasetBundle
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import LearningEvidenceKind, LearningEvidenceRecord

TRAINING_ROWS_SCHEMA_VERSION = 1
RECORD_FEATURES = frozenset(
    {
        "market",
        "direction",
        "context_state_1h",
        "source_evidence_class",
        "candidate_id",
        "candidate_spec_id",
        "campaign_id",
    }
)
SNAPSHOT_FEATURES = frozenset(
    {
        "day_return",
        "funding",
        "open_interest",
        "day_notional_volume",
        "oi_change_fraction",
        "funding_change",
        "mark_oracle_dislocation_bps",
        "return_5m",
        "return_15m",
        "return_1h",
        "return_4h",
        "realized_vol_15m",
        "range_expansion_15m",
        "relative_volume_15m",
        "spread_bps",
        "bid_depth_25bps",
        "ask_depth_25bps",
        "book_imbalance",
        "book_age_ms",
        "trend_regime",
        "volatility_regime",
    }
)
SUPPORTED_FEATURES = RECORD_FEATURES | SNAPSHOT_FEATURES
TARGET_BY_KIND = {
    LearningEvidenceKind.PROSPECTIVE_PAPER: "modeled_net_return_fraction",
    LearningEvidenceKind.PAPER_EXECUTION: "realized_net_r",
    LearningEvidenceKind.LIVE_EXECUTION: "realized_net_r",
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _record_feature_value(record: LearningEvidenceRecord, feature: str) -> str:
    if feature == "market":
        return record.market.canonical
    if feature == "direction":
        return record.direction.value
    if feature == "source_evidence_class":
        return record.source_evidence_class
    if feature == "candidate_id":
        return record.candidate_id
    if feature == "context_state_1h":
        if record.context_state_1h is None:
            raise ValueError(
                f"record {record.record_id} has no context_state_1h feature"
            )
        return record.context_state_1h
    if feature == "candidate_spec_id":
        if record.candidate_spec_id is None:
            raise ValueError(
                f"record {record.record_id} has no candidate_spec_id feature"
            )
        return record.candidate_spec_id
    if feature == "campaign_id":
        if record.campaign_id is None:
            raise ValueError(f"record {record.record_id} has no campaign_id feature")
        return record.campaign_id
    raise ValueError(f"unsupported record feature: {feature}")


def _snapshot_feature_value(snapshot: object, feature: str) -> str:
    value = getattr(snapshot, feature)
    if value is None:
        raise ValueError(f"feature snapshot has no value for {feature}")
    if feature in {"trend_regime", "volatility_regime"}:
        return str(value.value)
    return str(value)


def _feature_values(
    record: LearningEvidenceRecord,
    feature_registry: tuple[str, ...],
    *,
    feature_store: LearningFeatureSnapshotStore | None,
) -> tuple[str, ...]:
    snapshot = None
    if any(feature in SNAPSHOT_FEATURES for feature in feature_registry):
        if feature_store is None:
            raise ValueError(
                "feature snapshot store is required for snapshot-backed features"
            )
        verified = feature_store.load(record.feature_snapshot_id)
        if verified is None:
            raise ValueError(
                f"missing feature snapshot for record {record.record_id}: "
                f"{record.feature_snapshot_id}"
            )
        snapshot = verified.snapshot
        if snapshot.market != record.market:
            raise ValueError(
                f"feature snapshot market does not match record {record.record_id}"
            )
        if snapshot.as_of_ms > record.opened_at_ms:
            raise ValueError(
                f"feature snapshot is after trade open for record {record.record_id}"
            )
        if snapshot.source_received_at_ms > record.opened_at_ms:
            raise ValueError(
                f"feature snapshot source is after trade open for record {record.record_id}"
            )

    values: list[str] = []
    for feature in feature_registry:
        if feature in RECORD_FEATURES:
            values.append(_record_feature_value(record, feature))
            continue
        if feature in SNAPSHOT_FEATURES:
            if snapshot is None:
                raise ValueError("feature snapshot resolution failed")
            values.append(_snapshot_feature_value(snapshot, feature))
            continue
        raise ValueError(f"unsupported learning training feature: {feature}")
    return tuple(values)


def _target(record: LearningEvidenceRecord) -> tuple[str, Decimal]:
    target_name = TARGET_BY_KIND[record.kind]
    if record.kind is LearningEvidenceKind.PROSPECTIVE_PAPER:
        value = record.net_return_fraction
    else:
        value = record.net_r
    if value is None:
        raise ValueError(f"record {record.record_id} is missing target {target_name}")
    return target_name, value


@dataclass(frozen=True, slots=True)
class LearningTrainingRow:
    source_record_id: str
    evidence_kind: str
    source_evidence_class: str
    candidate_id: str
    candidate_spec_id: str | None
    campaign_id: str | None
    market: str
    direction: str
    opened_at_ms: int
    closed_at_ms: int
    feature_snapshot_id: str
    feature_registry: tuple[str, ...]
    feature_values: tuple[str, ...]
    target_name: str
    target_value: Decimal
    schema_version: int = TRAINING_ROWS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.source_record_id) != 64:
            raise ValueError("source_record_id must be a SHA-256 identity")
        if self.evidence_kind not in {kind.value for kind in LearningEvidenceKind}:
            raise ValueError("unsupported learning training evidence kind")
        expected_target = TARGET_BY_KIND[LearningEvidenceKind(self.evidence_kind)]
        if self.target_name != expected_target:
            raise ValueError("target_name must match evidence kind")
        if len(self.feature_registry) != len(self.feature_values):
            raise ValueError("feature registry and values must align")
        if not self.feature_registry:
            raise ValueError("feature registry must not be empty")
        if len(set(self.feature_registry)) != len(self.feature_registry):
            raise ValueError("feature registry must be unique")
        if any(feature not in SUPPORTED_FEATURES for feature in self.feature_registry):
            raise ValueError("feature registry contains unsupported feature")
        if any(not value.strip() for value in self.feature_values):
            raise ValueError("feature values must not be empty")
        if self.opened_at_ms < 0 or self.closed_at_ms < self.opened_at_ms:
            raise ValueError("learning training timestamps are invalid")
        if not self.feature_snapshot_id.strip():
            raise ValueError("feature_snapshot_id must not be empty")
        if not self.target_value.is_finite():
            raise ValueError("target_value must be finite")
        if self.schema_version != TRAINING_ROWS_SCHEMA_VERSION:
            raise ValueError("unsupported learning training row schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_record_id": self.source_record_id,
            "evidence_kind": self.evidence_kind,
            "source_evidence_class": self.source_evidence_class,
            "candidate_id": self.candidate_id,
            "candidate_spec_id": self.candidate_spec_id,
            "campaign_id": self.campaign_id,
            "market": self.market,
            "direction": self.direction,
            "opened_at_ms": self.opened_at_ms,
            "closed_at_ms": self.closed_at_ms,
            "feature_snapshot_id": self.feature_snapshot_id,
            "feature_registry": self.feature_registry,
            "feature_values": self.feature_values,
            "target_name": self.target_name,
            "target_value": str(self.target_value),
            "schema_version": self.schema_version,
        }

    @property
    def row_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "row_id": self.row_id}


@dataclass(frozen=True, slots=True)
class LearningTrainingSet:
    run_id: str
    dataset_id: str
    dataset_lineage_id: str
    evidence_kind: str
    target_name: str
    feature_registry: tuple[str, ...]
    rows: tuple[LearningTrainingRow, ...]
    schema_version: int = TRAINING_ROWS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.run_id, "run_id"),
            (self.dataset_id, "dataset_id"),
            (self.dataset_lineage_id, "dataset_lineage_id"),
        ):
            if len(value) != 64:
                raise ValueError(f"{field} must be a SHA-256 identity")
        if not self.rows:
            raise ValueError("learning training set must not be empty")
        if tuple(sorted(self.rows, key=lambda row: row.source_record_id)) != self.rows:
            raise ValueError("learning training rows must be sorted by source_record_id")
        if len({row.source_record_id for row in self.rows}) != len(self.rows):
            raise ValueError("learning training source records must be unique")
        if any(row.evidence_kind != self.evidence_kind for row in self.rows):
            raise ValueError("learning training set cannot mix evidence kinds")
        if any(row.target_name != self.target_name for row in self.rows):
            raise ValueError("learning training set cannot mix target families")
        if any(row.feature_registry != self.feature_registry for row in self.rows):
            raise ValueError("learning training rows must use frozen feature registry")
        if self.schema_version != TRAINING_ROWS_SCHEMA_VERSION:
            raise ValueError("unsupported learning training set schema")

    @property
    def training_set_id(self) -> str:
        return _sha256_json(
            {
                "run_id": self.run_id,
                "dataset_id": self.dataset_id,
                "dataset_lineage_id": self.dataset_lineage_id,
                "evidence_kind": self.evidence_kind,
                "target_name": self.target_name,
                "feature_registry": self.feature_registry,
                "row_ids": tuple(row.row_id for row in self.rows),
                "schema_version": self.schema_version,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "evidence_kind": self.evidence_kind,
            "target_name": self.target_name,
            "feature_registry": self.feature_registry,
            "row_count": len(self.rows),
            "row_ids": tuple(row.row_id for row in self.rows),
            "training_set_id": self.training_set_id,
            "schema_version": self.schema_version,
        }


def _records_for_kind(
    bundle: VerifiedLearningDatasetBundle,
    kind: LearningEvidenceKind,
) -> tuple[LearningEvidenceRecord, ...]:
    if kind is LearningEvidenceKind.PROSPECTIVE_PAPER:
        return bundle.snapshot.prospective_records
    if kind is LearningEvidenceKind.PAPER_EXECUTION:
        return bundle.snapshot.paper_execution_records
    return bundle.snapshot.live_execution_records


def build_learning_training_set(
    bundle: VerifiedLearningDatasetBundle,
    manifest: LearningChallengerRunManifest,
    *,
    feature_store: LearningFeatureSnapshotStore | None = None,
) -> LearningTrainingSet:
    if manifest.dataset_id != bundle.snapshot.manifest.dataset_id:
        raise ValueError("challenger run dataset_id does not match verified bundle")
    if manifest.dataset_lineage_id != bundle.lineage_id:
        raise ValueError("challenger run dataset lineage does not match verified bundle")
    if len(manifest.input_kinds) != 1:
        raise ValueError("challenger run must contain exactly one evidence kind")

    kind = LearningEvidenceKind(manifest.input_kinds[0])
    records = _records_for_kind(bundle, kind)
    expected_record_ids = tuple(sorted(record.record_id for record in records))
    if manifest.input_record_ids != expected_record_ids:
        raise ValueError("challenger run input records do not match verified bundle")
    if any(feature not in SUPPORTED_FEATURES for feature in manifest.feature_registry):
        raise ValueError("challenger feature registry contains unsupported feature")

    rows = tuple(
        sorted(
            (
                LearningTrainingRow(
                    source_record_id=record.record_id,
                    evidence_kind=record.kind.value,
                    source_evidence_class=record.source_evidence_class,
                    candidate_id=record.candidate_id,
                    candidate_spec_id=record.candidate_spec_id,
                    campaign_id=record.campaign_id,
                    market=record.market.canonical,
                    direction=record.direction.value,
                    opened_at_ms=record.opened_at_ms,
                    closed_at_ms=record.closed_at_ms,
                    feature_snapshot_id=record.feature_snapshot_id,
                    feature_registry=manifest.feature_registry,
                    feature_values=_feature_values(
                        record,
                        manifest.feature_registry,
                        feature_store=feature_store,
                    ),
                    target_name=_target(record)[0],
                    target_value=_target(record)[1],
                )
                for record in records
            ),
            key=lambda row: row.source_record_id,
        )
    )
    target_name = TARGET_BY_KIND[kind]
    return LearningTrainingSet(
        run_id=manifest.run_id,
        dataset_id=manifest.dataset_id,
        dataset_lineage_id=manifest.dataset_lineage_id,
        evidence_kind=kind.value,
        target_name=target_name,
        feature_registry=manifest.feature_registry,
        rows=rows,
    )
