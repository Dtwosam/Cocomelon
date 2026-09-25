from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from cocomelon.research.learning_challenger_run import (
    LearningChallengerRunManifest,
    build_learning_challenger_run_manifest,
)
from cocomelon.research.learning_dataset_bundle import VerifiedLearningDatasetBundle
from cocomelon.research.outcome_learning import LearningEvidenceKind, LearningEvidenceRecord

TRAINING_INPUT_SCHEMA_VERSION = 1
TRAINING_BUNDLE_SCHEMA_VERSION = 1
SUPPORTED_FEATURES = (
    "market",
    "direction",
    "context_state_1h",
    "source_evidence_class",
)


class LearningTrainingInputError(RuntimeError):
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


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningTrainingInputError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningTrainingInputError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LearningTrainingInputError(f"{field} must be a string array")
    return tuple(value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningTrainingInputError(f"{field} must be an integer")
    return value


def _features(value: object) -> dict[str, str | None]:
    raw = _mapping(value, "features")
    resolved: dict[str, str | None] = {}
    for key, item in raw.items():
        if item is not None and not isinstance(item, str):
            raise LearningTrainingInputError("feature values must be strings or null")
        resolved[key] = item
    return resolved


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class LearningTrainingRow:
    run_id: str
    record_id: str
    evidence_kind: str
    source_record_id: str
    candidate_id: str
    candidate_spec_id: str | None
    campaign_id: str | None
    feature_snapshot_id: str
    opened_at_ms: int
    closed_at_ms: int
    features: dict[str, str | None]
    target_name: str
    target_value: Decimal
    schema_version: int = TRAINING_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.run_id, "run_id")
        _require_sha256(self.record_id, "record_id")
        if self.evidence_kind not in {kind.value for kind in LearningEvidenceKind}:
            raise ValueError("unsupported evidence_kind")
        for field in (
            "source_record_id",
            "candidate_id",
            "feature_snapshot_id",
            "target_name",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.candidate_spec_id is not None and not self.candidate_spec_id.strip():
            raise ValueError("candidate_spec_id must not be empty when present")
        if self.campaign_id is not None and not self.campaign_id.strip():
            raise ValueError("campaign_id must not be empty when present")
        if self.opened_at_ms < 0 or self.closed_at_ms < self.opened_at_ms:
            raise ValueError("training row timestamps are invalid")
        if not self.features:
            raise ValueError("training row features must not be empty")
        if any(feature not in SUPPORTED_FEATURES for feature in self.features):
            raise ValueError("training row contains unsupported feature")
        if not self.target_value.is_finite():
            raise ValueError("training row target_value must be finite")
        if self.schema_version != TRAINING_INPUT_SCHEMA_VERSION:
            raise ValueError("unsupported learning training row schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "record_id": self.record_id,
            "evidence_kind": self.evidence_kind,
            "source_record_id": self.source_record_id,
            "candidate_id": self.candidate_id,
            "candidate_spec_id": self.candidate_spec_id,
            "campaign_id": self.campaign_id,
            "feature_snapshot_id": self.feature_snapshot_id,
            "opened_at_ms": self.opened_at_ms,
            "closed_at_ms": self.closed_at_ms,
            "features": self.features,
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
class LearningTrainingTable:
    run_id: str
    dataset_lineage_id: str
    evidence_kind: str
    target_name: str
    feature_registry: tuple[str, ...]
    rows: tuple[LearningTrainingRow, ...]
    schema_version: int = TRAINING_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.run_id, "run_id")
        _require_sha256(self.dataset_lineage_id, "dataset_lineage_id")
        if self.evidence_kind not in {kind.value for kind in LearningEvidenceKind}:
            raise ValueError("unsupported evidence_kind")
        if not self.target_name.strip():
            raise ValueError("target_name must not be empty")
        if not self.feature_registry:
            raise ValueError("feature_registry must not be empty")
        if len(set(self.feature_registry)) != len(self.feature_registry):
            raise ValueError("feature_registry must be unique")
        if any(feature not in SUPPORTED_FEATURES for feature in self.feature_registry):
            raise ValueError("feature_registry contains unsupported learning feature")
        if not self.rows:
            raise ValueError("learning training table must contain rows")
        expected_order = tuple(
            sorted(
                self.rows,
                key=lambda item: (
                    item.closed_at_ms,
                    item.opened_at_ms,
                    item.record_id,
                ),
            )
        )
        if self.rows != expected_order:
            raise ValueError("learning training rows must be chronological")
        for row in self.rows:
            if row.run_id != self.run_id:
                raise ValueError("training row run_id does not match table")
            if row.evidence_kind != self.evidence_kind:
                raise ValueError("training row evidence kind does not match table")
            if row.target_name != self.target_name:
                raise ValueError("training row target does not match table")
            if set(row.features) != set(self.feature_registry):
                raise ValueError("training row features do not match registry")
        if self.schema_version != TRAINING_INPUT_SCHEMA_VERSION:
            raise ValueError("unsupported learning training table schema")

    @property
    def rows_sha256(self) -> str:
        return _sha256_json(tuple(row.to_dict() for row in self.rows))

    def identity_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "dataset_lineage_id": self.dataset_lineage_id,
            "evidence_kind": self.evidence_kind,
            "target_name": self.target_name,
            "feature_registry": self.feature_registry,
            "row_count": len(self.rows),
            "row_ids": tuple(row.row_id for row in self.rows),
            "rows_sha256": self.rows_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def table_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "table_id": self.table_id}


def _target(record: LearningEvidenceRecord) -> tuple[str, Decimal]:
    if record.kind is LearningEvidenceKind.PROSPECTIVE_PAPER:
        if record.net_return_fraction is None:
            raise LearningTrainingInputError("PROSPECTIVE_TARGET_MISSING")
        return "net_return_fraction", record.net_return_fraction
    if record.net_r is None:
        raise LearningTrainingInputError("EXECUTION_TARGET_MISSING")
    return "net_r", record.net_r


def _feature_value(record: LearningEvidenceRecord, feature: str) -> str | None:
    if feature == "market":
        return record.market.canonical
    if feature == "direction":
        return record.direction.value
    if feature == "context_state_1h":
        return record.context_state_1h
    if feature == "source_evidence_class":
        return record.source_evidence_class
    raise LearningTrainingInputError(f"UNSUPPORTED_FEATURE:{feature}")


def build_learning_training_table(
    bundle: VerifiedLearningDatasetBundle,
    manifest: LearningChallengerRunManifest,
) -> LearningTrainingTable:
    input_kinds = tuple(LearningEvidenceKind(kind) for kind in manifest.input_kinds)
    expected = build_learning_challenger_run_manifest(
        bundle,
        input_kinds=input_kinds,
        feature_registry=manifest.feature_registry,
        model_family=manifest.model_family,
        model_config=manifest.model_config,
        decision_policy=manifest.decision_policy,
        implementation_commit_sha=manifest.implementation_commit_sha,
    )
    if manifest != expected:
        raise LearningTrainingInputError("LEARNING_TRAINING_RUN_LINEAGE_MISMATCH")
    if len(input_kinds) != 1:
        raise LearningTrainingInputError("LEARNING_TRAINING_REQUIRES_ONE_EVIDENCE_KIND")
    if any(feature not in SUPPORTED_FEATURES for feature in manifest.feature_registry):
        raise LearningTrainingInputError("LEARNING_TRAINING_FEATURE_REGISTRY_UNSUPPORTED")

    records = {
        record.record_id: record
        for record in bundle.snapshot.eligible_records
    }
    selected: list[LearningEvidenceRecord] = []
    for record_id in manifest.input_record_ids:
        record = records.get(record_id)
        if record is None:
            raise LearningTrainingInputError("LEARNING_TRAINING_RECORD_MISSING")
        selected.append(record)

    kind = input_kinds[0]
    if any(record.kind is not kind for record in selected):
        raise LearningTrainingInputError("LEARNING_TRAINING_EVIDENCE_KIND_MISMATCH")

    rows: list[LearningTrainingRow] = []
    target_name: str | None = None
    for record in selected:
        row_target_name, target_value = _target(record)
        if target_name is None:
            target_name = row_target_name
        elif row_target_name != target_name:
            raise LearningTrainingInputError("LEARNING_TRAINING_TARGET_FAMILY_MISMATCH")
        rows.append(
            LearningTrainingRow(
                run_id=manifest.run_id,
                record_id=record.record_id,
                evidence_kind=record.kind.value,
                source_record_id=record.source_record_id,
                candidate_id=record.candidate_id,
                candidate_spec_id=record.candidate_spec_id,
                campaign_id=record.campaign_id,
                feature_snapshot_id=record.feature_snapshot_id,
                opened_at_ms=record.opened_at_ms,
                closed_at_ms=record.closed_at_ms,
                features={
                    feature: _feature_value(record, feature)
                    for feature in manifest.feature_registry
                },
                target_name=row_target_name,
                target_value=target_value,
            )
        )

    if target_name is None:
        raise LearningTrainingInputError("LEARNING_TRAINING_TARGET_MISSING")
    return LearningTrainingTable(
        run_id=manifest.run_id,
        dataset_lineage_id=bundle.lineage_id,
        evidence_kind=kind.value,
        target_name=target_name,
        feature_registry=manifest.feature_registry,
        rows=tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.closed_at_ms,
                    item.opened_at_ms,
                    item.record_id,
                ),
            )
        ),
    )



@dataclass(frozen=True, slots=True)
class VerifiedLearningTrainingBundle:
    table: LearningTrainingTable
    manifest_sha256: str
    rows_file_sha256: str


def _row_from_payload(raw: dict[str, object]) -> LearningTrainingRow:
    try:
        target_value = Decimal(_string(raw.get("target_value"), "target_value"))
    except ArithmeticError as exc:
        raise LearningTrainingInputError("target_value must be a decimal string") from exc
    return LearningTrainingRow(
        run_id=_string(raw.get("run_id"), "run_id"),
        record_id=_string(raw.get("record_id"), "record_id"),
        evidence_kind=_string(raw.get("evidence_kind"), "evidence_kind"),
        source_record_id=_string(raw.get("source_record_id"), "source_record_id"),
        candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
        candidate_spec_id=_optional_string(
            raw.get("candidate_spec_id"),
            "candidate_spec_id",
        ),
        campaign_id=_optional_string(raw.get("campaign_id"), "campaign_id"),
        feature_snapshot_id=_string(
            raw.get("feature_snapshot_id"),
            "feature_snapshot_id",
        ),
        opened_at_ms=_integer(raw.get("opened_at_ms"), "opened_at_ms"),
        closed_at_ms=_integer(raw.get("closed_at_ms"), "closed_at_ms"),
        features=_features(raw.get("features")),
        target_name=_string(raw.get("target_name"), "target_name"),
        target_value=target_value,
        schema_version=_integer(raw.get("schema_version"), "schema_version"),
    )


def write_learning_training_bundle(
    table: LearningTrainingTable,
    *,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise LearningTrainingInputError(
            "learning training bundle output directory must be empty"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_bytes = (
        "".join(_canonical_json(row.to_dict()) + "\n" for row in table.rows)
    ).encode("utf-8")
    rows_path = output_dir / "rows.jsonl"
    _atomic_write(rows_path, rows_bytes)

    manifest_payload = {
        **table.to_dict(),
        "bundle_schema_version": TRAINING_BUNDLE_SCHEMA_VERSION,
        "rows_file": rows_path.name,
        "rows_file_sha256": _digest_bytes(rows_bytes),
    }
    manifest_bytes = (_canonical_json(manifest_payload) + "\n").encode("utf-8")
    manifest_path = output_dir / "manifest.json"
    _atomic_write(manifest_path, manifest_bytes)
    return {
        **manifest_payload,
        "manifest_sha256": _digest_bytes(manifest_bytes),
        "output_dir": str(output_dir),
    }


def load_verified_learning_training_bundle(
    *,
    output_dir: Path,
) -> VerifiedLearningTrainingBundle:
    manifest_path = output_dir / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        raw_manifest = _mapping(
            json.loads(manifest_bytes),
            "learning training bundle manifest",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_MANIFEST_INVALID"
        ) from exc

    if (
        _integer(
            raw_manifest.get("bundle_schema_version"),
            "bundle_schema_version",
        )
        != TRAINING_BUNDLE_SCHEMA_VERSION
    ):
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_SCHEMA_UNSUPPORTED"
        )
    if raw_manifest.get("rows_file") != "rows.jsonl":
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_ROWS_FILENAME_MISMATCH"
        )

    rows_path = output_dir / "rows.jsonl"
    try:
        rows_bytes = rows_path.read_bytes()
    except OSError as exc:
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_ROWS_MISSING"
        ) from exc
    rows_file_sha256 = _digest_bytes(rows_bytes)
    if raw_manifest.get("rows_file_sha256") != rows_file_sha256:
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_ROWS_DIGEST_MISMATCH"
        )

    rows: list[LearningTrainingRow] = []
    try:
        for line in rows_bytes.splitlines():
            if not line:
                continue
            raw_row = _mapping(
                json.loads(line),
                "learning training row",
            )
            stored_row_id = raw_row.pop("row_id", None)
            row = _row_from_payload(raw_row)
            if stored_row_id != row.row_id:
                raise LearningTrainingInputError(
                    "LEARNING_TRAINING_BUNDLE_ROW_IDENTITY_MISMATCH"
                )
            rows.append(row)
    except json.JSONDecodeError as exc:
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_ROW_INVALID"
        ) from exc

    try:
        table = LearningTrainingTable(
            run_id=_string(raw_manifest.get("run_id"), "run_id"),
            dataset_lineage_id=_string(
                raw_manifest.get("dataset_lineage_id"),
                "dataset_lineage_id",
            ),
            evidence_kind=_string(
                raw_manifest.get("evidence_kind"),
                "evidence_kind",
            ),
            target_name=_string(raw_manifest.get("target_name"), "target_name"),
            feature_registry=_strings(
                raw_manifest.get("feature_registry"),
                "feature_registry",
            ),
            rows=tuple(rows),
            schema_version=_integer(
                raw_manifest.get("schema_version"),
                "schema_version",
            ),
        )
    except ValueError as exc:
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_TABLE_INVALID"
        ) from exc

    expected_manifest = {
        **table.to_dict(),
        "bundle_schema_version": TRAINING_BUNDLE_SCHEMA_VERSION,
        "rows_file": "rows.jsonl",
        "rows_file_sha256": rows_file_sha256,
    }
    if _canonical_json(raw_manifest) != _canonical_json(expected_manifest):
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_MANIFEST_IDENTITY_MISMATCH"
        )
    canonical_manifest = (_canonical_json(expected_manifest) + "\n").encode("utf-8")
    if manifest_bytes != canonical_manifest:
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_MANIFEST_NON_CANONICAL"
        )

    return VerifiedLearningTrainingBundle(
        table=table,
        manifest_sha256=_digest_bytes(manifest_bytes),
        rows_file_sha256=rows_file_sha256,
    )


def verify_learning_training_bundle(
    *,
    output_dir: Path,
    source_bundle: VerifiedLearningDatasetBundle,
    run_manifest: LearningChallengerRunManifest,
) -> VerifiedLearningTrainingBundle:
    loaded = load_verified_learning_training_bundle(output_dir=output_dir)
    expected = build_learning_training_table(source_bundle, run_manifest)
    if loaded.table != expected:
        raise LearningTrainingInputError(
            "LEARNING_TRAINING_BUNDLE_SOURCE_LINEAGE_MISMATCH"
        )
    return loaded
