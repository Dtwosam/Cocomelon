from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.research.learning_dataset_bundle import VerifiedLearningDatasetBundle
from cocomelon.research.learning_feature_snapshots import (
    LearningFeatureSnapshotStore,
    VerifiedLearningFeatureSnapshot,
)
from cocomelon.research.outcome_learning import LearningEvidenceRecord

FEATURE_JOIN_SCHEMA_VERSION = 1
NUMERIC_FEATURE_REGISTRY = (
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
)


class LearningFeatureJoinError(RuntimeError):
    pass


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


def _feature_value(value: Decimal | int | None) -> str | int | None:
    if isinstance(value, Decimal):
        return str(value)
    return value


def numeric_feature_values(
    snapshot: FeatureSnapshot,
) -> tuple[str | int | None, ...]:
    return tuple(
        _feature_value(getattr(snapshot, feature))
        for feature in NUMERIC_FEATURE_REGISTRY
    )


@dataclass(frozen=True, slots=True)
class LearningFeatureJoinRow:
    record_id: str
    feature_snapshot_id: str
    feature_snapshot_record_sha256: str
    market: str
    opened_at_ms: int
    feature_as_of_ms: int
    feature_source_received_at_ms: int
    values: tuple[str | int | None, ...]
    schema_version: int = FEATURE_JOIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.record_id) != 64:
            raise ValueError("record_id must be a SHA-256 identity")
        if len(self.feature_snapshot_id) != 24:
            raise ValueError("feature_snapshot_id must be a snapshot identity")
        if len(self.feature_snapshot_record_sha256) != 64:
            raise ValueError("feature_snapshot_record_sha256 must be SHA-256")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.opened_at_ms < 0:
            raise ValueError("opened_at_ms must be non-negative")
        if self.feature_as_of_ms > self.opened_at_ms:
            raise ValueError("feature_as_of_ms cannot follow trade open")
        if self.feature_source_received_at_ms > self.opened_at_ms:
            raise ValueError("feature source cannot be received after trade open")
        if len(self.values) != len(NUMERIC_FEATURE_REGISTRY):
            raise ValueError("numeric feature width does not match registry")
        if self.schema_version != FEATURE_JOIN_SCHEMA_VERSION:
            raise ValueError("unsupported feature join row schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "feature_snapshot_record_sha256": self.feature_snapshot_record_sha256,
            "market": self.market,
            "opened_at_ms": self.opened_at_ms,
            "feature_as_of_ms": self.feature_as_of_ms,
            "feature_source_received_at_ms": self.feature_source_received_at_ms,
            "values": self.values,
            "schema_version": self.schema_version,
        }

    @property
    def row_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "row_id": self.row_id}


@dataclass(frozen=True, slots=True)
class LearningFeatureJoin:
    dataset_id: str
    dataset_lineage_id: str
    feature_registry: tuple[str, ...]
    rows: tuple[LearningFeatureJoinRow, ...]
    used_feature_records_sha256: str
    schema_version: int = FEATURE_JOIN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "dataset_id",
            "dataset_lineage_id",
            "used_feature_records_sha256",
        ):
            value = getattr(self, field)
            if len(value) != 64:
                raise ValueError(f"{field} must be a SHA-256 identity")
        if self.feature_registry != NUMERIC_FEATURE_REGISTRY:
            raise ValueError("feature_registry must match numeric feature registry")
        if not self.rows:
            raise ValueError("feature join requires at least one row")
        record_ids = tuple(row.record_id for row in self.rows)
        if record_ids != tuple(sorted(record_ids)):
            raise ValueError("feature join rows must be sorted by record_id")
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("feature join rows must be unique by record_id")
        if self.schema_version != FEATURE_JOIN_SCHEMA_VERSION:
            raise ValueError("unsupported feature join schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "feature_registry": self.feature_registry,
            "row_count": len(self.rows),
            "row_ids": tuple(row.row_id for row in self.rows),
            "used_feature_records_sha256": self.used_feature_records_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def join_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "join_id": self.join_id}


def _join_row(
    record: LearningEvidenceRecord,
    verified: VerifiedLearningFeatureSnapshot,
) -> LearningFeatureJoinRow:
    snapshot = verified.snapshot
    if snapshot.snapshot_id != record.feature_snapshot_id:
        raise LearningFeatureJoinError(
            "LEARNING_FEATURE_JOIN_SNAPSHOT_ID_MISMATCH"
        )
    if snapshot.market != record.market:
        raise LearningFeatureJoinError(
            "LEARNING_FEATURE_JOIN_MARKET_MISMATCH"
        )
    if snapshot.as_of_ms > record.opened_at_ms:
        raise LearningFeatureJoinError(
            "LEARNING_FEATURE_JOIN_LOOKAHEAD_AS_OF"
        )
    if snapshot.source_received_at_ms > record.opened_at_ms:
        raise LearningFeatureJoinError(
            "LEARNING_FEATURE_JOIN_LOOKAHEAD_SOURCE_RECEIVED"
        )
    return LearningFeatureJoinRow(
        record_id=record.record_id,
        feature_snapshot_id=snapshot.snapshot_id,
        feature_snapshot_record_sha256=verified.record_sha256,
        market=record.market.canonical,
        opened_at_ms=record.opened_at_ms,
        feature_as_of_ms=snapshot.as_of_ms,
        feature_source_received_at_ms=snapshot.source_received_at_ms,
        values=numeric_feature_values(snapshot),
    )


def build_learning_feature_join(
    bundle: VerifiedLearningDatasetBundle,
    feature_store: LearningFeatureSnapshotStore,
) -> LearningFeatureJoin:
    rows: list[LearningFeatureJoinRow] = []
    used_records: list[tuple[str, str]] = []
    for record in bundle.snapshot.eligible_records:
        verified = feature_store.load(record.feature_snapshot_id)
        if verified is None:
            raise LearningFeatureJoinError(
                "LEARNING_FEATURE_JOIN_SNAPSHOT_MISSING:"
                f"{record.feature_snapshot_id}"
            )
        row = _join_row(record, verified)
        rows.append(row)
        used_records.append(
            (
                verified.snapshot.snapshot_id,
                verified.record_sha256,
            )
        )

    if not rows:
        raise LearningFeatureJoinError("LEARNING_FEATURE_JOIN_DATASET_EMPTY")
    ordered_rows = tuple(sorted(rows, key=lambda item: item.record_id))
    used_feature_records_sha256 = _sha256_json(
        tuple(sorted(set(used_records)))
    )
    return LearningFeatureJoin(
        dataset_id=bundle.snapshot.manifest.dataset_id,
        dataset_lineage_id=bundle.lineage_id,
        feature_registry=NUMERIC_FEATURE_REGISTRY,
        rows=ordered_rows,
        used_feature_records_sha256=used_feature_records_sha256,
    )
