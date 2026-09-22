from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.research.historical_archive_presets import (
    EVIDENCE_CLASS,
    HistoricalArchiveExperimentPreset,
)
from cocomelon.research.historical_archive_review import (
    HistoricalArchiveDevelopmentReview,
    HistoricalDevelopmentVariantReview,
    build_archive_development_review,
)
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)

SELECTION_POLICY = "unique_qualified_variant_only"
CANDIDATE_KIND = "model_family_recipe"
FREEZE_SCHEMA_VERSION = 1


class HistoricalArchiveCandidateFreezeError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveCandidateFreezeError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCandidateFreezeError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCandidateFreezeError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCandidateFreezeError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise HistoricalArchiveCandidateFreezeError(
            f"{field} must be a decimal string"
        )
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise HistoricalArchiveCandidateFreezeError(
            f"{field} must be a decimal string"
        ) from exc
    if not resolved.is_finite():
        raise HistoricalArchiveCandidateFreezeError(f"{field} must be finite")
    return resolved


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class HistoricalArchiveCandidateFreeze:
    preset_name: str
    preset_id: str
    evidence_class: str
    bundle_id: str
    review_id: str
    review_policy_id: str
    comparison_report_id: str
    comparison_version: str
    model_family: str
    calibration_variant: str
    qualified_variant_sha256: str
    minimum_required_trades_per_fold: int
    minimum_required_mean_net_return: Decimal
    total_test_trades: int
    mean_realized_net_return: Decimal
    discovery_start_ms: int
    discovery_end_ms: int
    frozen_at_ms: int
    validation_not_before_ms: int
    selection_policy: str = SELECTION_POLICY
    candidate_kind: str = CANDIDATE_KIND
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = FREEZE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "bundle_id",
            "review_id",
            "review_policy_id",
            "comparison_report_id",
            "comparison_version",
            "model_family",
            "calibration_variant",
            "qualified_variant_sha256",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        _require_sha256(self.qualified_variant_sha256, "qualified_variant_sha256")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("archive candidate freeze evidence must remain touched")
        if self.selection_policy != SELECTION_POLICY:
            raise ValueError("unsupported archive candidate selection policy")
        if self.candidate_kind != CANDIDATE_KIND:
            raise ValueError("unsupported archive candidate kind")
        if self.minimum_required_trades_per_fold <= 0:
            raise ValueError("minimum_required_trades_per_fold must be positive")
        if not self.minimum_required_mean_net_return.is_finite():
            raise ValueError("minimum_required_mean_net_return must be finite")
        if self.total_test_trades <= 0:
            raise ValueError("total_test_trades must be positive")
        if not self.mean_realized_net_return.is_finite():
            raise ValueError("mean_realized_net_return must be finite")
        if self.mean_realized_net_return <= self.minimum_required_mean_net_return:
            raise ValueError("qualified candidate mean must be above review floor")
        if self.discovery_start_ms < 0:
            raise ValueError("discovery_start_ms must be non-negative")
        if self.discovery_end_ms <= self.discovery_start_ms:
            raise ValueError("discovery_end_ms must be after discovery_start_ms")
        if self.frozen_at_ms < self.discovery_end_ms:
            raise ValueError("frozen_at_ms must not precede discovery end")
        if self.validation_not_before_ms != (
            self.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ):
            raise ValueError("validation_not_before_ms must equal freeze + embargo")
        if not self.prospective_only:
            raise ValueError("archive candidate freeze must remain prospective-only")
        if self.promotion_eligible:
            raise ValueError("touched archive candidate cannot be promotion eligible")
        if self.execution_ready:
            raise ValueError("family-recipe freeze is not execution ready")
        if self.schema_version != FREEZE_SCHEMA_VERSION:
            raise ValueError("unsupported archive candidate freeze schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "evidence_class": self.evidence_class,
            "bundle_id": self.bundle_id,
            "review_id": self.review_id,
            "review_policy_id": self.review_policy_id,
            "comparison_report_id": self.comparison_report_id,
            "comparison_version": self.comparison_version,
            "model_family": self.model_family,
            "calibration_variant": self.calibration_variant,
            "qualified_variant_sha256": self.qualified_variant_sha256,
            "minimum_required_trades_per_fold": (
                self.minimum_required_trades_per_fold
            ),
            "minimum_required_mean_net_return": str(
                self.minimum_required_mean_net_return
            ),
            "total_test_trades": self.total_test_trades,
            "mean_realized_net_return": str(self.mean_realized_net_return),
            "discovery_start_ms": self.discovery_start_ms,
            "discovery_end_ms": self.discovery_end_ms,
            "frozen_at_ms": self.frozen_at_ms,
            "validation_not_before_ms": self.validation_not_before_ms,
            "selection_policy": self.selection_policy,
            "candidate_kind": self.candidate_kind,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def candidate_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "candidate_id": self.candidate_id}


def _persisted_review_must_match(
    output_root: Path,
    review: HistoricalArchiveDevelopmentReview,
) -> None:
    path = output_root / "development-review.json"
    try:
        actual = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HistoricalArchiveCandidateFreezeError(
            "DEVELOPMENT_REVIEW_REQUIRED"
        ) from exc
    expected = _canonical_json(review.to_dict()) + "\n"
    if actual != expected:
        raise HistoricalArchiveCandidateFreezeError(
            "DEVELOPMENT_REVIEW_RECEIPT_MISMATCH"
        )


def _unique_qualified_variant(
    review: HistoricalArchiveDevelopmentReview,
) -> HistoricalDevelopmentVariantReview:
    qualified = tuple(
        item for item in review.variants if item.eligible_for_freeze_review
    )
    if not qualified:
        raise HistoricalArchiveCandidateFreezeError(
            "NO_QUALIFIED_ARCHIVE_CANDIDATE"
        )
    if len(qualified) != 1:
        raise HistoricalArchiveCandidateFreezeError(
            "MULTIPLE_QUALIFIED_ARCHIVE_CANDIDATES"
        )
    return qualified[0]


def build_archive_candidate_freeze(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    frozen_at_ms: int,
) -> HistoricalArchiveCandidateFreeze:
    if frozen_at_ms < 0:
        raise ValueError("frozen_at_ms must be non-negative")

    review = build_archive_development_review(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    _persisted_review_must_match(output_root, review)
    variant = _unique_qualified_variant(review)
    if variant.mean_realized_net_return is None:
        raise HistoricalArchiveCandidateFreezeError(
            "QUALIFIED_VARIANT_MEAN_REQUIRED"
        )

    variant_sha256 = hashlib.sha256(
        _canonical_json(variant.to_dict()).encode("utf-8")
    ).hexdigest()
    return HistoricalArchiveCandidateFreeze(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        evidence_class=preset.evidence_class,
        bundle_id=review.bundle_id,
        review_id=review.review_id,
        review_policy_id=review.policy_id,
        comparison_report_id=review.comparison_report_id,
        comparison_version=review.comparison_version,
        model_family=variant.model_family,
        calibration_variant=variant.calibration_variant,
        qualified_variant_sha256=variant_sha256,
        minimum_required_trades_per_fold=(
            variant.minimum_required_trades_per_fold
        ),
        minimum_required_mean_net_return=(
            variant.minimum_required_mean_net_return
        ),
        total_test_trades=variant.total_test_trades,
        mean_realized_net_return=variant.mean_realized_net_return,
        discovery_start_ms=preset.start_ms,
        discovery_end_ms=preset.end_ms,
        frozen_at_ms=frozen_at_ms,
        validation_not_before_ms=frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS,
    )


def write_archive_candidate_freeze(
    output_root: Path,
    freeze: HistoricalArchiveCandidateFreeze,
) -> Path:
    path = output_root / "candidate-freeze.json"
    payload = (_canonical_json(freeze.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveCandidateFreezeError(
                "ARCHIVE_CANDIDATE_FREEZE_CONFLICT"
            )
        return path

    temporary = output_root / ".candidate-freeze.json.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def _freeze_from_payload(raw: dict[str, object]) -> HistoricalArchiveCandidateFreeze:
    try:
        freeze = HistoricalArchiveCandidateFreeze(
            preset_name=_string(raw.get("preset_name"), "preset_name"),
            preset_id=_string(raw.get("preset_id"), "preset_id"),
            evidence_class=_string(raw.get("evidence_class"), "evidence_class"),
            bundle_id=_string(raw.get("bundle_id"), "bundle_id"),
            review_id=_string(raw.get("review_id"), "review_id"),
            review_policy_id=_string(raw.get("review_policy_id"), "review_policy_id"),
            comparison_report_id=_string(
                raw.get("comparison_report_id"),
                "comparison_report_id",
            ),
            comparison_version=_string(
                raw.get("comparison_version"),
                "comparison_version",
            ),
            model_family=_string(raw.get("model_family"), "model_family"),
            calibration_variant=_string(
                raw.get("calibration_variant"),
                "calibration_variant",
            ),
            qualified_variant_sha256=_string(
                raw.get("qualified_variant_sha256"),
                "qualified_variant_sha256",
            ),
            minimum_required_trades_per_fold=_integer(
                raw.get("minimum_required_trades_per_fold"),
                "minimum_required_trades_per_fold",
            ),
            minimum_required_mean_net_return=_decimal(
                raw.get("minimum_required_mean_net_return"),
                "minimum_required_mean_net_return",
            ),
            total_test_trades=_integer(
                raw.get("total_test_trades"),
                "total_test_trades",
            ),
            mean_realized_net_return=_decimal(
                raw.get("mean_realized_net_return"),
                "mean_realized_net_return",
            ),
            discovery_start_ms=_integer(
                raw.get("discovery_start_ms"),
                "discovery_start_ms",
            ),
            discovery_end_ms=_integer(
                raw.get("discovery_end_ms"),
                "discovery_end_ms",
            ),
            frozen_at_ms=_integer(raw.get("frozen_at_ms"), "frozen_at_ms"),
            validation_not_before_ms=_integer(
                raw.get("validation_not_before_ms"),
                "validation_not_before_ms",
            ),
            selection_policy=_string(
                raw.get("selection_policy"),
                "selection_policy",
            ),
            candidate_kind=_string(raw.get("candidate_kind"), "candidate_kind"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
            ),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"),
                "promotion_eligible",
            ),
            execution_ready=_boolean(
                raw.get("execution_ready"),
                "execution_ready",
            ),
            schema_version=_integer(
                raw.get("schema_version"),
                "schema_version",
            ),
        )
    except ValueError as exc:
        raise HistoricalArchiveCandidateFreezeError(
            "ARCHIVE_CANDIDATE_FREEZE_INVALID"
        ) from exc
    candidate_id = _string(raw.get("candidate_id"), "candidate_id")
    if candidate_id != freeze.candidate_id:
        raise HistoricalArchiveCandidateFreezeError(
            "ARCHIVE_CANDIDATE_FREEZE_ID_MISMATCH"
        )
    return freeze


def verify_archive_candidate_freeze(
    path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCandidateFreeze:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive candidate freeze",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveCandidateFreezeError(
            "ARCHIVE_CANDIDATE_FREEZE_INVALID"
        ) from exc

    freeze = _freeze_from_payload(raw)
    canonical = _canonical_json(freeze.to_dict()) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise HistoricalArchiveCandidateFreezeError(
            "ARCHIVE_CANDIDATE_FREEZE_NON_CANONICAL"
        )
    expected = build_archive_candidate_freeze(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
        frozen_at_ms=freeze.frozen_at_ms,
    )
    if expected != freeze:
        raise HistoricalArchiveCandidateFreezeError(
            "ARCHIVE_CANDIDATE_FREEZE_EVIDENCE_MISMATCH"
        )
    return freeze
