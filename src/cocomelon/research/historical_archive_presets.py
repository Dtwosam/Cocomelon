from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cocomelon.domain.market import MarketId
from cocomelon.research.historical_archive_acquisition import plan_archive_shards
from cocomelon.research.historical_archive_experiment import (
    ArchiveHistoricalExperimentResult,
    ArchiveHistoricalSourcePreparation,
    HistoricalArchiveExperimentClient,
    prepare_archive_historical_sources,
    run_archive_historical_experiment,
    run_prepared_archive_historical_experiment,
    verify_downloaded_archive_cache,
)
from cocomelon.research.historical_baselines import ExecutionCostAssumptions
from cocomelon.research.historical_model_comparison import (
    HistoricalModelComparisonConfig,
)
from cocomelon.research.historical_tree import TreeModelConfig
from cocomelon.research.python_source_attestation import (
    PythonSourceTreeAttestation,
    build_python_source_tree_attestation,
    verify_python_source_tree_attestation,
    write_python_source_tree_attestation,
)

PRESET_NAME = "archive-jul-sep-2026-v2"
EVIDENCE_CLASS = "touched_development"


def _utc_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).astimezone(UTC).timestamp() * 1000)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_path(path: Path, field: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"ARCHIVE_PRESET_BUNDLE_{field}_MISSING")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class HistoricalArchiveExperimentPreset:
    name: str
    start_ms: int
    end_ms: int
    markets: tuple[MarketId, ...]
    intervals: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    comparison_config: HistoricalModelComparisonConfig
    overlap_candles: int
    max_funding_items: int
    evidence_class: str = EVIDENCE_CLASS
    schema_version: int = 2

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("invalid preset range")
        if not self.markets:
            raise ValueError("markets must not be empty")
        if not self.intervals:
            raise ValueError("intervals must not be empty")
        if not self.horizons_ms or any(value <= 0 for value in self.horizons_ms):
            raise ValueError("horizons_ms must contain positive values")
        if self.overlap_candles <= 0 or self.overlap_candles > 5_000:
            raise ValueError("overlap_candles must be between 1 and 5000")
        if self.max_funding_items <= 1:
            raise ValueError("max_funding_items must be greater than one")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("archive presets must remain touched_development")
        if self.schema_version != 2:
            raise ValueError("unsupported archive preset schema")

    @property
    def archive_shard_count(self) -> int:
        return len(plan_archive_shards(start_ms=self.start_ms, end_ms=self.end_ms))

    def identity_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "markets": tuple(market.canonical for market in self.markets),
            "intervals": self.intervals,
            "horizons_ms": self.horizons_ms,
            "comparison_config": self.comparison_config.to_dict(),
            "overlap_candles": self.overlap_candles,
            "max_funding_items": self.max_funding_items,
            "archive_shard_count": self.archive_shard_count,
            "evidence_class": self.evidence_class,
            "schema_version": self.schema_version,
        }

    @property
    def preset_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()[:24]

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "preset_id": self.preset_id}


@dataclass(frozen=True, slots=True)
class HistoricalArchivePresetPreflight:
    preset_name: str
    preset_id: str
    evidence_class: str
    archive_manifest_id: str
    archive_shard_count: int
    archive_total_byte_count: int
    expected_archive_shard_count: int
    implementation_attestation_id: str
    source_tree_sha256: str
    source_file_count: int
    source_cache_file_count: int
    output_root_clean: bool
    paid_request_performed: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "archive_manifest_id",
            "implementation_attestation_id",
            "source_tree_sha256",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("preflight evidence must remain touched_development")
        if self.archive_shard_count <= 0:
            raise ValueError("archive_shard_count must be positive")
        if self.archive_shard_count != self.expected_archive_shard_count:
            raise ValueError("archive shard count must match frozen preset")
        if self.archive_total_byte_count < 0:
            raise ValueError("archive_total_byte_count must be non-negative")
        if len(self.implementation_attestation_id) != 64:
            raise ValueError("implementation_attestation_id must be SHA-256")
        if len(self.source_tree_sha256) != 64:
            raise ValueError("source_tree_sha256 must be SHA-256")
        if self.source_file_count <= 0:
            raise ValueError("source_file_count must be positive")
        if self.source_cache_file_count < 0:
            raise ValueError("source_cache_file_count must be non-negative")
        if not self.output_root_clean:
            raise ValueError("preflight requires a clean output root")
        if self.paid_request_performed:
            raise ValueError("archive preset preflight must remain offline")
        if self.schema_version != 1:
            raise ValueError("unsupported archive preset preflight schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "evidence_class": self.evidence_class,
            "archive_manifest_id": self.archive_manifest_id,
            "archive_shard_count": self.archive_shard_count,
            "archive_total_byte_count": self.archive_total_byte_count,
            "expected_archive_shard_count": self.expected_archive_shard_count,
            "implementation_attestation_id": self.implementation_attestation_id,
            "source_tree_sha256": self.source_tree_sha256,
            "source_file_count": self.source_file_count,
            "source_cache_file_count": self.source_cache_file_count,
            "output_root_clean": self.output_root_clean,
            "paid_request_performed": self.paid_request_performed,
            "schema_version": self.schema_version,
        }

    @property
    def preflight_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "preflight_id": self.preflight_id}


@dataclass(frozen=True, slots=True)
class HistoricalArchivePresetRunReceipt:
    preset_name: str
    preset_id: str
    preset_identity_sha256: str
    evidence_class: str
    archive_manifest_id: str
    archive_ingest_manifest_id: str
    coverage_report_id: str
    overlap_report_id: str
    dataset_id: str
    comparison_report_id: str
    comparison_version: str
    archive_shard_count: int
    archive_total_byte_count: int
    overlap_compared_count: int
    dataset_row_count: int
    fold_count: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "archive_manifest_id",
            "archive_ingest_manifest_id",
            "coverage_report_id",
            "overlap_report_id",
            "dataset_id",
            "comparison_report_id",
            "comparison_version",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        if len(self.preset_identity_sha256) != 64:
            raise ValueError("preset_identity_sha256 must be SHA-256")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("preset run evidence must remain touched_development")
        for field in (
            "archive_shard_count",
            "overlap_compared_count",
            "dataset_row_count",
            "fold_count",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        if self.archive_total_byte_count < 0:
            raise ValueError("archive_total_byte_count must be non-negative")
        if self.schema_version != 1:
            raise ValueError("unsupported preset run receipt schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "preset_identity_sha256": self.preset_identity_sha256,
            "evidence_class": self.evidence_class,
            "archive_manifest_id": self.archive_manifest_id,
            "archive_ingest_manifest_id": self.archive_ingest_manifest_id,
            "coverage_report_id": self.coverage_report_id,
            "overlap_report_id": self.overlap_report_id,
            "dataset_id": self.dataset_id,
            "comparison_report_id": self.comparison_report_id,
            "comparison_version": self.comparison_version,
            "archive_shard_count": self.archive_shard_count,
            "archive_total_byte_count": self.archive_total_byte_count,
            "overlap_compared_count": self.overlap_compared_count,
            "dataset_row_count": self.dataset_row_count,
            "fold_count": self.fold_count,
            "schema_version": self.schema_version,
        }

    @property
    def receipt_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "receipt_id": self.receipt_id}


@dataclass(frozen=True, slots=True)
class HistoricalArchivePresetBundleReceipt:
    preset_name: str
    preset_id: str
    evidence_class: str
    preset_run_receipt_id: str
    archive_download_manifest_sha256: str
    archive_ingest_sha256: str
    coverage_sha256: str
    overlap_sha256: str
    source_preparation_sha256: str
    dataset_manifest_sha256: str
    training_parquet_sha256: str
    comparison_sha256: str
    preset_run_receipt_sha256: str
    implementation_sha256: str
    schema_version: int = 3

    def __post_init__(self) -> None:
        for field in ("preset_name", "preset_id", "preset_run_receipt_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("preset bundle evidence must remain touched_development")
        for field in (
            "archive_download_manifest_sha256",
            "archive_ingest_sha256",
            "coverage_sha256",
            "overlap_sha256",
            "source_preparation_sha256",
            "dataset_manifest_sha256",
            "training_parquet_sha256",
            "comparison_sha256",
            "preset_run_receipt_sha256",
            "implementation_sha256",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"{field} must be SHA-256")
        if self.schema_version != 3:
            raise ValueError("unsupported preset bundle receipt schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "evidence_class": self.evidence_class,
            "preset_run_receipt_id": self.preset_run_receipt_id,
            "archive_download_manifest_sha256": (
                self.archive_download_manifest_sha256
            ),
            "archive_ingest_sha256": self.archive_ingest_sha256,
            "coverage_sha256": self.coverage_sha256,
            "overlap_sha256": self.overlap_sha256,
            "source_preparation_sha256": self.source_preparation_sha256,
            "dataset_manifest_sha256": self.dataset_manifest_sha256,
            "training_parquet_sha256": self.training_parquet_sha256,
            "comparison_sha256": self.comparison_sha256,
            "preset_run_receipt_sha256": self.preset_run_receipt_sha256,
            "implementation_sha256": self.implementation_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def bundle_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "bundle_id": self.bundle_id}


def _archive_preset_bundle_paths(
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> dict[str, Path]:
    return {
        "archive_download_manifest": archive_root / "download_manifest.json",
        "archive_ingest": source_root / "archive_ingest.json",
        "coverage": source_root / "coverage.json",
        "overlap": source_root / "archive_native_overlap.json",
        "source_preparation": source_root / "source-preparation.json",
        "dataset_manifest": output_root / "dataset" / "manifest.json",
        "training_parquet": output_root / "dataset" / "training.parquet",
        "comparison": output_root / "comparison.json",
        "preset_run_receipt": output_root / "preset-run.json",
        "implementation": output_root / "implementation.json",
    }


def _package_source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_archive_preset_source_attestation(
    preset: HistoricalArchiveExperimentPreset,
) -> PythonSourceTreeAttestation:
    return build_python_source_tree_attestation(
        _package_source_root(),
        subject_type="historical_archive_preset",
        subject_id=preset.preset_id,
    )


def verify_archive_preset_source_attestation(
    output_root: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
) -> PythonSourceTreeAttestation:
    return verify_python_source_tree_attestation(
        output_root / "implementation.json",
        expected_subject_type="historical_archive_preset",
        expected_subject_id=preset.preset_id,
    )


def _summary_string(
    result: ArchiveHistoricalExperimentResult,
    field: str,
) -> str:
    value = result.source_summary.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"ARCHIVE_PRESET_{field.upper()}_MISSING")
    return value


def build_archive_preset_run_receipt(
    preset: HistoricalArchiveExperimentPreset,
    result: ArchiveHistoricalExperimentResult,
) -> HistoricalArchivePresetRunReceipt:
    if (
        result.archive.requested_start_ms != preset.start_ms
        or result.archive.requested_end_ms != preset.end_ms
    ):
        raise RuntimeError("ARCHIVE_PRESET_RANGE_MISMATCH")
    if result.archive.shard_count != preset.archive_shard_count:
        raise RuntimeError("ARCHIVE_PRESET_SHARD_COUNT_MISMATCH")
    if result.comparison.evidence_class != preset.evidence_class:
        raise RuntimeError("ARCHIVE_PRESET_EVIDENCE_CLASS_MISMATCH")
    if result.comparison.config.to_dict() != preset.comparison_config.to_dict():
        raise RuntimeError("ARCHIVE_PRESET_COMPARISON_CONFIG_MISMATCH")
    expected_markets = tuple(
        sorted(market.canonical for market in preset.markets)
    )
    if tuple(sorted(result.comparison.markets)) != expected_markets:
        raise RuntimeError("ARCHIVE_PRESET_MARKET_SET_MISMATCH")
    if tuple(sorted(result.comparison.horizons_ms)) != tuple(
        sorted(preset.horizons_ms)
    ):
        raise RuntimeError("ARCHIVE_PRESET_HORIZON_SET_MISMATCH")
    if (
        result.overlap.overlap_candles != preset.overlap_candles
        or not result.overlap.exact
    ):
        raise RuntimeError("ARCHIVE_PRESET_OVERLAP_MISMATCH")

    preset_identity_sha256 = hashlib.sha256(
        _canonical_json(preset.identity_payload()).encode("utf-8")
    ).hexdigest()
    return HistoricalArchivePresetRunReceipt(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        preset_identity_sha256=preset_identity_sha256,
        evidence_class=preset.evidence_class,
        archive_manifest_id=result.archive.manifest_id,
        archive_ingest_manifest_id=_summary_string(
            result,
            "archive_manifest_id",
        ),
        coverage_report_id=_summary_string(result, "coverage_report_id"),
        overlap_report_id=result.overlap.report_id,
        dataset_id=result.dataset_id,
        comparison_report_id=result.report_id,
        comparison_version=result.comparison.comparison_version,
        archive_shard_count=result.archive.shard_count,
        archive_total_byte_count=result.archive.total_byte_count,
        overlap_compared_count=result.overlap.compared_count,
        dataset_row_count=result.comparison.dataset_row_count,
        fold_count=len(result.comparison.baseline_folds),
    )


def verify_archive_preset_run_receipt(
    path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
) -> HistoricalArchivePresetRunReceipt:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_INVALID") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_INVALID")

    required_strings = (
        "preset_name",
        "preset_id",
        "preset_identity_sha256",
        "evidence_class",
        "archive_manifest_id",
        "archive_ingest_manifest_id",
        "coverage_report_id",
        "overlap_report_id",
        "dataset_id",
        "comparison_report_id",
        "comparison_version",
        "receipt_id",
    )
    values: dict[str, str] = {}
    for field in required_strings:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_INVALID")
        values[field] = value

    integer_fields = (
        "archive_shard_count",
        "archive_total_byte_count",
        "overlap_compared_count",
        "dataset_row_count",
        "fold_count",
        "schema_version",
    )
    integers: dict[str, int] = {}
    for field in integer_fields:
        value = raw.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_INVALID")
        integers[field] = value

    try:
        receipt = HistoricalArchivePresetRunReceipt(
            preset_name=values["preset_name"],
            preset_id=values["preset_id"],
            preset_identity_sha256=values["preset_identity_sha256"],
            evidence_class=values["evidence_class"],
            archive_manifest_id=values["archive_manifest_id"],
            archive_ingest_manifest_id=values["archive_ingest_manifest_id"],
            coverage_report_id=values["coverage_report_id"],
            overlap_report_id=values["overlap_report_id"],
            dataset_id=values["dataset_id"],
            comparison_report_id=values["comparison_report_id"],
            comparison_version=values["comparison_version"],
            archive_shard_count=integers["archive_shard_count"],
            archive_total_byte_count=integers["archive_total_byte_count"],
            overlap_compared_count=integers["overlap_compared_count"],
            dataset_row_count=integers["dataset_row_count"],
            fold_count=integers["fold_count"],
            schema_version=integers["schema_version"],
        )
    except ValueError as exc:
        raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_INVALID") from exc

    if values["receipt_id"] != receipt.receipt_id:
        raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_ID_MISMATCH")
    expected_preset_sha256 = hashlib.sha256(
        _canonical_json(preset.identity_payload()).encode("utf-8")
    ).hexdigest()
    if (
        receipt.preset_name != preset.name
        or receipt.preset_id != preset.preset_id
        or receipt.preset_identity_sha256 != expected_preset_sha256
        or receipt.evidence_class != preset.evidence_class
    ):
        raise RuntimeError("ARCHIVE_PRESET_RUN_PRESET_MISMATCH")
    return receipt


def build_archive_preset_bundle_receipt(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchivePresetBundleReceipt:
    run_receipt = verify_archive_preset_run_receipt(
        output_root / "preset-run.json",
        preset=preset,
    )
    verify_archive_preset_source_attestation(
        output_root,
        preset=preset,
    )
    paths = _archive_preset_bundle_paths(
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    return HistoricalArchivePresetBundleReceipt(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        evidence_class=preset.evidence_class,
        preset_run_receipt_id=run_receipt.receipt_id,
        archive_download_manifest_sha256=_sha256_path(
            paths["archive_download_manifest"],
            "ARCHIVE_DOWNLOAD_MANIFEST",
        ),
        archive_ingest_sha256=_sha256_path(
            paths["archive_ingest"],
            "ARCHIVE_INGEST",
        ),
        coverage_sha256=_sha256_path(paths["coverage"], "COVERAGE"),
        overlap_sha256=_sha256_path(paths["overlap"], "OVERLAP"),
        source_preparation_sha256=_sha256_path(
            paths["source_preparation"],
            "SOURCE_PREPARATION",
        ),
        dataset_manifest_sha256=_sha256_path(
            paths["dataset_manifest"],
            "DATASET_MANIFEST",
        ),
        training_parquet_sha256=_sha256_path(
            paths["training_parquet"],
            "TRAINING_PARQUET",
        ),
        comparison_sha256=_sha256_path(
            paths["comparison"],
            "COMPARISON",
        ),
        preset_run_receipt_sha256=_sha256_path(
            paths["preset_run_receipt"],
            "PRESET_RUN_RECEIPT",
        ),
        implementation_sha256=_sha256_path(
            paths["implementation"],
            "IMPLEMENTATION",
        ),
    )


def write_archive_preset_bundle_receipt(
    output_root: Path,
    receipt: HistoricalArchivePresetBundleReceipt,
) -> Path:
    path = output_root / "preset-bundle.json"
    payload = _canonical_json(receipt.to_dict()) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RECEIPT_CONFLICT")
        return path

    temporary = output_root / ".preset-bundle.json.tmp"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
    return path


def verify_archive_preset_bundle_receipt(
    path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchivePresetBundleReceipt:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RECEIPT_INVALID") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RECEIPT_INVALID")

    string_fields = (
        "preset_name",
        "preset_id",
        "evidence_class",
        "preset_run_receipt_id",
        "archive_download_manifest_sha256",
        "archive_ingest_sha256",
        "coverage_sha256",
        "overlap_sha256",
        "source_preparation_sha256",
        "dataset_manifest_sha256",
        "training_parquet_sha256",
        "comparison_sha256",
        "preset_run_receipt_sha256",
        "implementation_sha256",
        "bundle_id",
    )
    values: dict[str, str] = {}
    for field in string_fields:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RECEIPT_INVALID")
        values[field] = value

    schema_version = raw.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RECEIPT_INVALID")

    try:
        receipt = HistoricalArchivePresetBundleReceipt(
            preset_name=values["preset_name"],
            preset_id=values["preset_id"],
            evidence_class=values["evidence_class"],
            preset_run_receipt_id=values["preset_run_receipt_id"],
            archive_download_manifest_sha256=values[
                "archive_download_manifest_sha256"
            ],
            archive_ingest_sha256=values["archive_ingest_sha256"],
            coverage_sha256=values["coverage_sha256"],
            overlap_sha256=values["overlap_sha256"],
            source_preparation_sha256=values["source_preparation_sha256"],
            dataset_manifest_sha256=values["dataset_manifest_sha256"],
            training_parquet_sha256=values["training_parquet_sha256"],
            comparison_sha256=values["comparison_sha256"],
            preset_run_receipt_sha256=values["preset_run_receipt_sha256"],
            implementation_sha256=values["implementation_sha256"],
            schema_version=schema_version,
        )
    except ValueError as exc:
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RECEIPT_INVALID") from exc

    if values["bundle_id"] != receipt.bundle_id:
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RECEIPT_ID_MISMATCH")
    if (
        receipt.preset_name != preset.name
        or receipt.preset_id != preset.preset_id
        or receipt.evidence_class != preset.evidence_class
    ):
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_PRESET_MISMATCH")

    run_receipt = verify_archive_preset_run_receipt(
        output_root / "preset-run.json",
        preset=preset,
    )
    if run_receipt.receipt_id != receipt.preset_run_receipt_id:
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_RUN_RECEIPT_MISMATCH")

    expected = build_archive_preset_bundle_receipt(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    if expected != receipt:
        raise RuntimeError("ARCHIVE_PRESET_BUNDLE_FILE_DIGEST_MISMATCH")
    return receipt


def write_archive_preset_run_receipt(
    output_root: Path,
    receipt: HistoricalArchivePresetRunReceipt,
) -> Path:
    path = output_root / "preset-run.json"
    payload = _canonical_json(receipt.to_dict()) + "\n"
    output_root.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise RuntimeError("ARCHIVE_PRESET_RUN_RECEIPT_CONFLICT")
        return path

    temporary = output_root / ".preset-run.json.tmp"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
    return path


JUL_SEP_2026_V2 = HistoricalArchiveExperimentPreset(
    name=PRESET_NAME,
    start_ms=_utc_ms("2026-07-01T00:00:00+00:00"),
    end_ms=_utc_ms("2026-09-20T23:55:00+00:00"),
    markets=(
        MarketId(dex="", coin="BTC"),
        MarketId(dex="", coin="ETH"),
        MarketId(dex="", coin="HYPE"),
        MarketId(dex="", coin="SOL"),
    ),
    intervals=("5m", "15m"),
    horizons_ms=(900_000, 3_600_000, 14_400_000),
    comparison_config=HistoricalModelComparisonConfig(
        costs=ExecutionCostAssumptions(
            round_trip_fee_fraction=Decimal("0.0007"),
            round_trip_slippage_fraction=Decimal("0.0005"),
            funding_reserve_fraction_per_hour=Decimal("0.0001"),
        ),
        candidate_thresholds=(
            Decimal("0"),
            Decimal("0.0005"),
            Decimal("0.001"),
            Decimal("0.002"),
            Decimal("0.004"),
        ),
        candidate_ridge_alphas=(
            Decimal("0.01"),
            Decimal("0.1"),
            Decimal("1"),
            Decimal("10"),
        ),
        min_train_anchors=8_000,
        validation_anchors=2_000,
        test_anchors=2_000,
        step_anchors=2_000,
        embargo_anchors=48,
        baseline_min_state_samples=50,
        baseline_min_coin_samples=100,
        ridge_min_market_samples=100,
        min_sample_count=50,
        min_validation_trades=20,
        min_validation_mean_net_return=Decimal("0"),
        stability_blocks=4,
        min_validation_block_trades=5,
        tree_min_market_samples=100,
        portfolio_max_concurrent_positions=2,
        tree_config=TreeModelConfig(
            max_leaf_nodes=7,
            min_samples_leaf=100,
            learning_rate=Decimal("0.05"),
            max_iter=100,
            l2_regularization=Decimal("1"),
        ),
    ),
    overlap_candles=96,
    max_funding_items=500,
)

PRESETS = {
    JUL_SEP_2026_V2.name: JUL_SEP_2026_V2,
}


def get_archive_experiment_preset(name: str) -> HistoricalArchiveExperimentPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        raise ValueError(f"unknown archive experiment preset: {name}") from exc


def _source_cache_file_count(source_root: Path) -> int:
    if not source_root.exists():
        return 0
    if not source_root.is_dir():
        raise RuntimeError("ARCHIVE_PRESET_SOURCE_ROOT_NOT_DIRECTORY")
    return sum(1 for path in source_root.rglob("*") if path.is_file())


def build_archive_preset_preflight(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchivePresetPreflight:
    ensure_archive_preset_output_root_clean(output_root)
    source_cache_file_count = _source_cache_file_count(source_root)
    archive = verify_downloaded_archive_cache(
        archive_root,
        start_ms=preset.start_ms,
        end_ms=preset.end_ms,
    )
    if archive.shard_count != preset.archive_shard_count:
        raise RuntimeError("ARCHIVE_PRESET_PREFLIGHT_SHARD_COUNT_MISMATCH")

    implementation = build_archive_preset_source_attestation(preset)
    return HistoricalArchivePresetPreflight(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        evidence_class=preset.evidence_class,
        archive_manifest_id=archive.manifest_id,
        archive_shard_count=archive.shard_count,
        archive_total_byte_count=archive.total_byte_count,
        expected_archive_shard_count=preset.archive_shard_count,
        implementation_attestation_id=implementation.attestation_id,
        source_tree_sha256=implementation.source_tree_sha256,
        source_file_count=len(implementation.files),
        source_cache_file_count=source_cache_file_count,
        output_root_clean=True,
    )


def ensure_archive_preset_output_root_clean(output_root: Path) -> None:
    if not output_root.exists():
        return
    if not output_root.is_dir():
        raise RuntimeError("ARCHIVE_PRESET_OUTPUT_ROOT_NOT_DIRECTORY")
    if any(output_root.iterdir()):
        raise RuntimeError("ARCHIVE_PRESET_OUTPUT_ROOT_NOT_EMPTY")


def prepare_archive_experiment_preset(
    client: HistoricalArchiveExperimentClient,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    clock_ms: Callable[[], int],
) -> ArchiveHistoricalSourcePreparation:
    return prepare_archive_historical_sources(
        client,
        archive_root=archive_root,
        source_root=source_root,
        markets=preset.markets,
        intervals=preset.intervals,
        start_ms=preset.start_ms,
        end_ms=preset.end_ms,
        clock_ms=clock_ms,
        max_funding_items=preset.max_funding_items,
        overlap_candles=preset.overlap_candles,
    )


def run_prepared_archive_experiment_preset(
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> ArchiveHistoricalExperimentResult:
    ensure_archive_preset_output_root_clean(output_root)
    source_before = build_archive_preset_source_attestation(preset)
    result = run_prepared_archive_historical_experiment(
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
        markets=preset.markets,
        intervals=preset.intervals,
        horizons_ms=preset.horizons_ms,
        start_ms=preset.start_ms,
        end_ms=preset.end_ms,
        config=preset.comparison_config,
        overlap_candles=preset.overlap_candles,
    )
    source_after = build_archive_preset_source_attestation(preset)
    if source_after != source_before:
        raise RuntimeError("ARCHIVE_PRESET_SOURCE_TREE_CHANGED_DURING_RUN")
    write_python_source_tree_attestation(
        output_root / "implementation.json",
        source_after,
    )
    receipt = build_archive_preset_run_receipt(preset, result)
    write_archive_preset_run_receipt(output_root, receipt)
    bundle = build_archive_preset_bundle_receipt(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    write_archive_preset_bundle_receipt(output_root, bundle)
    return result


def run_archive_experiment_preset(
    client: HistoricalArchiveExperimentClient,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    clock_ms: Callable[[], int],
) -> ArchiveHistoricalExperimentResult:
    ensure_archive_preset_output_root_clean(output_root)
    source_before = build_archive_preset_source_attestation(preset)
    result = run_archive_historical_experiment(
        client,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
        markets=preset.markets,
        intervals=preset.intervals,
        horizons_ms=preset.horizons_ms,
        start_ms=preset.start_ms,
        end_ms=preset.end_ms,
        clock_ms=clock_ms,
        config=preset.comparison_config,
        max_funding_items=preset.max_funding_items,
        overlap_candles=preset.overlap_candles,
    )
    source_after = build_archive_preset_source_attestation(preset)
    if source_after != source_before:
        raise RuntimeError("ARCHIVE_PRESET_SOURCE_TREE_CHANGED_DURING_RUN")
    write_python_source_tree_attestation(
        output_root / "implementation.json",
        source_after,
    )
    receipt = build_archive_preset_run_receipt(preset, result)
    write_archive_preset_run_receipt(output_root, receipt)
    bundle = build_archive_preset_bundle_receipt(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    write_archive_preset_bundle_receipt(output_root, bundle)
    return result
