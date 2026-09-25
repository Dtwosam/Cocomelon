from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cocomelon.research.learning_dataset import LearningDatasetSnapshot

BUNDLE_SCHEMA_VERSION = 1


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_learning_dataset_bundle(
    snapshot: LearningDatasetSnapshot,
    *,
    output_dir: Path,
) -> dict[str, object]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("learning dataset output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)

    records = tuple(
        {
            **record.identity_payload(),
            "record_id": record.record_id,
        }
        for record in snapshot.eligible_records
    )
    records_bytes = (
        "".join(_canonical_json(record) + "\n" for record in records).encode("utf-8")
    )
    records_path = output_dir / "records.jsonl"
    records_path.write_bytes(records_bytes)

    manifest_payload = {
        **snapshot.manifest.to_dict(),
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "records_file": records_path.name,
        "records_sha256": _digest_bytes(records_bytes),
    }
    manifest_bytes = (_canonical_json(manifest_payload) + "\n").encode("utf-8")
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_bytes(manifest_bytes)

    return {
        **manifest_payload,
        "manifest_sha256": _digest_bytes(manifest_bytes),
        "output_dir": str(output_dir),
    }


def verify_learning_dataset_bundle(*, output_dir: Path) -> dict[str, object]:
    manifest_path = output_dir / "manifest.json"
    records_path = output_dir / "records.jsonl"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if int(manifest.get("bundle_schema_version", -1)) != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported learning dataset bundle schema")
    if manifest.get("records_file") != records_path.name:
        raise ValueError("learning dataset records filename mismatch")

    records_bytes = records_path.read_bytes()
    actual_records_digest = _digest_bytes(records_bytes)
    if manifest.get("records_sha256") != actual_records_digest:
        raise ValueError("learning dataset records digest mismatch")

    record_ids: list[str] = []
    for line in records_bytes.splitlines():
        if not line:
            continue
        raw = json.loads(line)
        record_id = raw.get("record_id")
        if not isinstance(record_id, str) or len(record_id) != 64:
            raise ValueError("learning dataset record identity is invalid")
        identity = dict(raw)
        identity.pop("record_id")
        calculated = hashlib.sha256(
            _canonical_json(identity).encode("utf-8")
        ).hexdigest()
        if calculated != record_id:
            raise ValueError("learning dataset record identity mismatch")
        record_ids.append(record_id)

    expected_ids = sorted(str(value) for value in manifest.get("eligible_record_ids", ()))
    if sorted(record_ids) != expected_ids:
        raise ValueError("learning dataset records do not match manifest")
    if len(record_ids) != int(manifest.get("eligible_record_count", -1)):
        raise ValueError("learning dataset record count mismatch")

    return {
        "dataset_id": str(manifest["dataset_id"]),
        "eligible_record_count": len(record_ids),
        "manifest_sha256": _digest_bytes(manifest_bytes),
        "records_sha256": actual_records_digest,
        "verified": True,
    }
