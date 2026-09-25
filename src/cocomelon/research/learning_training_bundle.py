from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from cocomelon.research.learning_challenger_run import LearningChallengerRunManifest
from cocomelon.research.learning_training_rows import (
    LearningTrainingRow,
    LearningTrainingSet,
)

TRAINING_BUNDLE_SCHEMA_VERSION = 1
ROWS_FILENAME = "rows.jsonl"
MANIFEST_FILENAME = "manifest.json"


class LearningTrainingBundleError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningTrainingBundleError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningTrainingBundleError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningTrainingBundleError(f"{field} must be an integer")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LearningTrainingBundleError(f"{field} must be a string array")
    return tuple(value)


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _training_row(raw: dict[str, object]) -> LearningTrainingRow:
    try:
        row = LearningTrainingRow(
            source_record_id=_string(
                raw.get("source_record_id"),
                "source_record_id",
            ),
            evidence_kind=_string(raw.get("evidence_kind"), "evidence_kind"),
            source_evidence_class=_string(
                raw.get("source_evidence_class"),
                "source_evidence_class",
            ),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_spec_id=_optional_string(
                raw.get("candidate_spec_id"),
                "candidate_spec_id",
            ),
            campaign_id=_optional_string(raw.get("campaign_id"), "campaign_id"),
            market=_string(raw.get("market"), "market"),
            direction=_string(raw.get("direction"), "direction"),
            opened_at_ms=_integer(raw.get("opened_at_ms"), "opened_at_ms"),
            closed_at_ms=_integer(raw.get("closed_at_ms"), "closed_at_ms"),
            feature_snapshot_id=_string(
                raw.get("feature_snapshot_id"),
                "feature_snapshot_id",
            ),
            feature_registry=_strings(
                raw.get("feature_registry"),
                "feature_registry",
            ),
            feature_values=_strings(raw.get("feature_values"), "feature_values"),
            target_name=_string(raw.get("target_name"), "target_name"),
            target_value=Decimal(_string(raw.get("target_value"), "target_value")),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except (ValueError, ArithmeticError) as exc:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_ROW_INVALID"
        ) from exc
    if raw.get("row_id") != row.row_id:
        raise LearningTrainingBundleError("LEARNING_TRAINING_ROW_ID_MISMATCH")
    return row


@dataclass(frozen=True, slots=True)
class VerifiedLearningTrainingBundle:
    training_set: LearningTrainingSet
    manifest_sha256: str
    rows_sha256: str

    @property
    def bundle_id(self) -> str:
        return _sha256_bytes(
            _canonical_json(
                {
                    "training_set_id": self.training_set.training_set_id,
                    "manifest_sha256": self.manifest_sha256,
                    "rows_sha256": self.rows_sha256,
                }
            ).encode("utf-8")
        )


def write_learning_training_bundle(
    training_set: LearningTrainingSet,
    *,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise LearningTrainingBundleError(
            "learning training output directory must be empty"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    rows_bytes = "".join(
        _canonical_json(row.to_dict()) + "\n"
        for row in training_set.rows
    ).encode("utf-8")
    rows_path = output_dir / ROWS_FILENAME
    rows_path.write_bytes(rows_bytes)

    manifest_payload = {
        **training_set.to_dict(),
        "training_bundle_schema_version": TRAINING_BUNDLE_SCHEMA_VERSION,
        "rows_file": ROWS_FILENAME,
        "rows_sha256": _sha256_bytes(rows_bytes),
    }
    manifest_bytes = (_canonical_json(manifest_payload) + "\n").encode("utf-8")
    (output_dir / MANIFEST_FILENAME).write_bytes(manifest_bytes)

    return {
        **manifest_payload,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "output_dir": str(output_dir),
    }


def load_verified_learning_training_bundle(
    *,
    output_dir: Path,
) -> VerifiedLearningTrainingBundle:
    manifest_path = output_dir / MANIFEST_FILENAME
    try:
        manifest_bytes = manifest_path.read_bytes()
        raw_manifest = _mapping(
            json.loads(manifest_bytes),
            "learning training manifest",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_MANIFEST_INVALID"
        ) from exc

    if (
        _integer(
            raw_manifest.get("training_bundle_schema_version"),
            "training_bundle_schema_version",
        )
        != TRAINING_BUNDLE_SCHEMA_VERSION
    ):
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_BUNDLE_SCHEMA_UNSUPPORTED"
        )
    if raw_manifest.get("rows_file") != ROWS_FILENAME:
        raise LearningTrainingBundleError("LEARNING_TRAINING_ROWS_FILE_MISMATCH")

    rows_path = output_dir / ROWS_FILENAME
    try:
        rows_bytes = rows_path.read_bytes()
    except OSError as exc:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_ROWS_MISSING"
        ) from exc
    rows_sha256 = _sha256_bytes(rows_bytes)
    if raw_manifest.get("rows_sha256") != rows_sha256:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_ROWS_DIGEST_MISMATCH"
        )

    rows: list[LearningTrainingRow] = []
    try:
        for line in rows_bytes.splitlines():
            if not line:
                continue
            rows.append(_training_row(_mapping(json.loads(line), "training row")))
    except json.JSONDecodeError as exc:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_ROWS_INVALID"
        ) from exc

    try:
        training_set = LearningTrainingSet(
            run_id=_string(raw_manifest.get("run_id"), "run_id"),
            dataset_id=_string(raw_manifest.get("dataset_id"), "dataset_id"),
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
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_SET_INVALID"
        ) from exc

    expected = {
        **training_set.to_dict(),
        "training_bundle_schema_version": TRAINING_BUNDLE_SCHEMA_VERSION,
        "rows_file": ROWS_FILENAME,
        "rows_sha256": rows_sha256,
    }
    if _canonical_json(raw_manifest) != _canonical_json(expected):
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_MANIFEST_IDENTITY_MISMATCH"
        )
    if manifest_bytes != (_canonical_json(expected) + "\n").encode("utf-8"):
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_MANIFEST_NON_CANONICAL"
        )

    return VerifiedLearningTrainingBundle(
        training_set=training_set,
        manifest_sha256=_sha256_bytes(manifest_bytes),
        rows_sha256=rows_sha256,
    )



def verify_learning_training_bundle(
    *,
    output_dir: Path,
    manifest: LearningChallengerRunManifest,
) -> VerifiedLearningTrainingBundle:
    verified = load_verified_learning_training_bundle(output_dir=output_dir)
    training_set = verified.training_set
    if training_set.run_id != manifest.run_id:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_RUN_ID_MISMATCH"
        )
    if training_set.dataset_id != manifest.dataset_id:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_DATASET_ID_MISMATCH"
        )
    if training_set.dataset_lineage_id != manifest.dataset_lineage_id:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_DATASET_LINEAGE_MISMATCH"
        )
    if training_set.feature_registry != manifest.feature_registry:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_FEATURE_REGISTRY_MISMATCH"
        )
    if training_set.evidence_kind != manifest.input_kinds[0]:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_EVIDENCE_KIND_MISMATCH"
        )
    source_record_ids = tuple(row.source_record_id for row in training_set.rows)
    if source_record_ids != manifest.input_record_ids:
        raise LearningTrainingBundleError(
            "LEARNING_TRAINING_INPUT_RECORDS_MISMATCH"
        )
    return verified
