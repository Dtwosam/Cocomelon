from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_dataset import LearningDatasetManifest, LearningDatasetSnapshot
from cocomelon.research.outcome_learning import LearningEvidenceKind, LearningEvidenceRecord

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


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _int_value(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"learning dataset {field} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"learning dataset {field} must be an integer") from exc


def _market_from_canonical(value: str) -> MarketId:
    if not value.strip():
        raise ValueError("learning dataset record market must not be empty")
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    return MarketId(dex, coin)


def _record_from_payload(raw: dict[str, object]) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind(str(raw["kind"])),
        source_record_id=str(raw["source_record_id"]),
        source_evidence_class=str(raw["source_evidence_class"]),
        candidate_id=str(raw["candidate_id"]),
        candidate_spec_id=(
            None if raw.get("candidate_spec_id") is None else str(raw["candidate_spec_id"])
        ),
        campaign_id=None if raw.get("campaign_id") is None else str(raw["campaign_id"]),
        market=_market_from_canonical(str(raw["market"])),
        direction=Direction(str(raw["direction"])),
        opened_at_ms=_int_value(raw["opened_at_ms"], "opened_at_ms"),
        closed_at_ms=_int_value(raw["closed_at_ms"], "closed_at_ms"),
        feature_snapshot_id=str(raw["feature_snapshot_id"]),
        research_eligible_at_ms=_int_value(raw["research_eligible_at_ms"], "research_eligible_at_ms"),
        context_state_1h=(
            None if raw.get("context_state_1h") is None else str(raw["context_state_1h"])
        ),
        gross_return_fraction=_optional_decimal(raw.get("gross_return_fraction")),
        modeled_cost_fraction=_optional_decimal(raw.get("modeled_cost_fraction")),
        net_return_fraction=_optional_decimal(raw.get("net_return_fraction")),
        gross_realized_pnl=_optional_decimal(raw.get("gross_realized_pnl")),
        entry_fees=_optional_decimal(raw.get("entry_fees")),
        exit_fees=_optional_decimal(raw.get("exit_fees")),
        funding_cash_pnl=_optional_decimal(raw.get("funding_cash_pnl")),
        entry_slippage_fraction=_optional_decimal(raw.get("entry_slippage_fraction")),
        exit_slippage_fraction=_optional_decimal(raw.get("exit_slippage_fraction")),
        net_pnl=_optional_decimal(raw.get("net_pnl")),
        net_r=_optional_decimal(raw.get("net_r")),
        schema_version=_int_value(raw["schema_version"], "schema_version"),
    )


def _manifest_from_payload(raw: dict[str, object]) -> LearningDatasetManifest:
    def values(field: str) -> tuple[str, ...]:
        value = raw[field]
        if not isinstance(value, list):
            raise ValueError(f"learning dataset manifest {field} must be a list")
        return tuple(str(item) for item in value)

    return LearningDatasetManifest(
        as_of_ms=_int_value(raw["as_of_ms"], "as_of_ms"),
        ledger_state_digest=str(raw["ledger_state_digest"]),
        eligible_record_ids=values("eligible_record_ids"),
        quarantined_record_ids=values("quarantined_record_ids"),
        prospective_record_ids=values("prospective_record_ids"),
        paper_execution_record_ids=values("paper_execution_record_ids"),
        live_execution_record_ids=values("live_execution_record_ids"),
        candidate_ids=values("candidate_ids"),
        schema_version=_int_value(raw["schema_version"], "schema_version"),
    )


@dataclass(frozen=True, slots=True)
class VerifiedLearningDatasetBundle:
    snapshot: LearningDatasetSnapshot
    manifest_sha256: str
    records_sha256: str

    @property
    def lineage_payload(self) -> dict[str, object]:
        return {
            "dataset_id": self.snapshot.manifest.dataset_id,
            "manifest_sha256": self.manifest_sha256,
            "records_sha256": self.records_sha256,
        }

    @property
    def lineage_id(self) -> str:
        return _digest_bytes(_canonical_json(self.lineage_payload).encode("utf-8"))


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


def load_verified_learning_dataset_bundle(
    *,
    output_dir: Path,
) -> VerifiedLearningDatasetBundle:
    manifest_path = output_dir / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    raw_manifest = json.loads(manifest_bytes)
    if not isinstance(raw_manifest, dict):
        raise ValueError("learning dataset manifest must be an object")
    if _int_value(raw_manifest.get("bundle_schema_version", -1), "bundle_schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ValueError("unsupported learning dataset bundle schema")
    if raw_manifest.get("records_file") != "records.jsonl":
        raise ValueError("learning dataset records filename mismatch")

    records_path = output_dir / "records.jsonl"
    records_bytes = records_path.read_bytes()
    actual_records_digest = _digest_bytes(records_bytes)
    if raw_manifest.get("records_sha256") != actual_records_digest:
        raise ValueError("learning dataset records digest mismatch")

    records: list[LearningEvidenceRecord] = []
    for line in records_bytes.splitlines():
        if not line:
            continue
        raw_record = json.loads(line)
        if not isinstance(raw_record, dict):
            raise ValueError("learning dataset record must be an object")
        record_id = raw_record.pop("record_id", None)
        record = _record_from_payload(raw_record)
        if record_id != record.record_id:
            raise ValueError("learning dataset record identity mismatch")
        records.append(record)

    manifest = _manifest_from_payload(raw_manifest)
    if raw_manifest.get("dataset_id") != manifest.dataset_id:
        raise ValueError("learning dataset manifest identity mismatch")

    count_fields = {
        "eligible_record_count": len(manifest.eligible_record_ids),
        "quarantined_record_count": len(manifest.quarantined_record_ids),
        "prospective_record_count": len(manifest.prospective_record_ids),
        "paper_execution_record_count": len(manifest.paper_execution_record_ids),
        "live_execution_record_count": len(manifest.live_execution_record_ids),
    }
    for field, expected in count_fields.items():
        if _int_value(raw_manifest.get(field, -1), field) != expected:
            raise ValueError(f"learning dataset manifest {field} mismatch")

    by_kind = {
        kind: tuple(record for record in records if record.kind is kind)
        for kind in LearningEvidenceKind
    }
    snapshot = LearningDatasetSnapshot(
        manifest=manifest,
        prospective_records=by_kind[LearningEvidenceKind.PROSPECTIVE_PAPER],
        paper_execution_records=by_kind[LearningEvidenceKind.PAPER_EXECUTION],
        live_execution_records=by_kind[LearningEvidenceKind.LIVE_EXECUTION],
    )
    if tuple(sorted(record.record_id for record in records)) != manifest.eligible_record_ids:
        raise ValueError("learning dataset records do not match manifest")

    return VerifiedLearningDatasetBundle(
        snapshot=snapshot,
        manifest_sha256=_digest_bytes(manifest_bytes),
        records_sha256=actual_records_digest,
    )


def verify_learning_dataset_bundle(*, output_dir: Path) -> dict[str, object]:
    verified = load_verified_learning_dataset_bundle(output_dir=output_dir)
    return {
        "dataset_id": verified.snapshot.manifest.dataset_id,
        "eligible_record_count": len(verified.snapshot.manifest.eligible_record_ids),
        "manifest_sha256": verified.manifest_sha256,
        "records_sha256": verified.records_sha256,
        "verified": True,
    }
