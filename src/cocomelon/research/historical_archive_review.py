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
    verify_archive_preset_bundle_receipt,
    verify_archive_preset_run_receipt,
)

REVIEW_POLICY_NAME = "historical-stability-gated-freeze-review-v1"
REVIEW_SCHEMA_VERSION = 1
VARIANT_SPECS = (
    ("stable_horizon_ridge", "stable_horizon_ridge_folds"),
    ("occupancy_stable_ridge", "occupancy_stable_ridge_folds"),
    ("portfolio_capacity_stable_ridge", "portfolio_capacity_stable_ridge_folds"),
    ("stable_tree", "stable_tree_folds"),
)


class HistoricalArchiveReviewError(RuntimeError):
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
        raise HistoricalArchiveReviewError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise HistoricalArchiveReviewError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveReviewError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveReviewError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise HistoricalArchiveReviewError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise HistoricalArchiveReviewError(
            f"{field} must be a valid decimal string"
        ) from exc
    if not resolved.is_finite():
        raise HistoricalArchiveReviewError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class HistoricalDevelopmentReviewPolicy:
    name: str = REVIEW_POLICY_NAME
    eligible_families: tuple[str, ...] = tuple(item[0] for item in VARIANT_SPECS)
    calibration_variants: tuple[str, ...] = ("shared", "market")
    min_test_folds: int = 2
    test_trades_per_fold_source: str = "comparison_config.min_validation_trades"
    minimum_mean_source: str = "comparison_config.min_validation_mean_net_return"
    require_every_test_fold_above_floor: bool = True
    require_overall_test_mean_above_floor: bool = True
    evidence_class: str = EVIDENCE_CLASS
    schema_version: int = REVIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.name != REVIEW_POLICY_NAME:
            raise ValueError("unsupported historical development review policy")
        if self.eligible_families != tuple(item[0] for item in VARIANT_SPECS):
            raise ValueError("review policy family set is frozen")
        if self.calibration_variants != ("shared", "market"):
            raise ValueError("review policy calibration variants are frozen")
        if self.min_test_folds < 2:
            raise ValueError("min_test_folds must preserve multi-fold evidence")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("historical review evidence must remain touched")
        if self.schema_version != REVIEW_SCHEMA_VERSION:
            raise ValueError("unsupported historical review policy schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "eligible_families": self.eligible_families,
            "calibration_variants": self.calibration_variants,
            "min_test_folds": self.min_test_folds,
            "test_trades_per_fold_source": self.test_trades_per_fold_source,
            "minimum_mean_source": self.minimum_mean_source,
            "require_every_test_fold_above_floor": (
                self.require_every_test_fold_above_floor
            ),
            "require_overall_test_mean_above_floor": (
                self.require_overall_test_mean_above_floor
            ),
            "evidence_class": self.evidence_class,
            "schema_version": self.schema_version,
        }

    @property
    def policy_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "policy_id": self.policy_id}


FROZEN_ARCHIVE_DEVELOPMENT_REVIEW_V1 = HistoricalDevelopmentReviewPolicy()


@dataclass(frozen=True, slots=True)
class HistoricalDevelopmentVariantReview:
    model_family: str
    calibration_variant: str
    fold_count: int
    minimum_required_fold_count: int
    minimum_required_trades_per_fold: int
    minimum_required_mean_net_return: Decimal
    total_test_trades: int
    long_test_trades: int
    short_test_trades: int
    total_realized_net_return: Decimal
    mean_realized_net_return: Decimal | None
    minimum_fold_trade_count: int
    insufficient_activity_fold_indices: tuple[int, ...]
    nonpositive_fold_indices: tuple[int, ...]
    eligible_for_freeze_review: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.model_family not in FROZEN_ARCHIVE_DEVELOPMENT_REVIEW_V1.eligible_families:
            raise ValueError("unsupported model_family")
        if self.calibration_variant not in {"shared", "market"}:
            raise ValueError("unsupported calibration_variant")
        if self.fold_count <= 0:
            raise ValueError("fold_count must be positive")
        if self.minimum_required_fold_count < 2:
            raise ValueError("minimum_required_fold_count must be at least two")
        if self.minimum_required_trades_per_fold <= 0:
            raise ValueError("minimum_required_trades_per_fold must be positive")
        if not self.minimum_required_mean_net_return.is_finite():
            raise ValueError("minimum_required_mean_net_return must be finite")
        for field in (
            "total_test_trades",
            "long_test_trades",
            "short_test_trades",
            "minimum_fold_trade_count",
        ):
            if getattr(self, field) < 0:
                raise ValueError(f"{field} must be non-negative")
        if self.long_test_trades + self.short_test_trades != self.total_test_trades:
            raise ValueError("long/short counts must equal total_test_trades")
        if not self.total_realized_net_return.is_finite():
            raise ValueError("total_realized_net_return must be finite")
        if self.mean_realized_net_return is None:
            if self.total_test_trades != 0:
                raise ValueError("mean return is required when test trades exist")
        elif not self.mean_realized_net_return.is_finite():
            raise ValueError("mean_realized_net_return must be finite")
        if tuple(sorted(set(self.insufficient_activity_fold_indices))) != (
            self.insufficient_activity_fold_indices
        ):
            raise ValueError("insufficient_activity_fold_indices must be sorted unique")
        if tuple(sorted(set(self.nonpositive_fold_indices))) != (
            self.nonpositive_fold_indices
        ):
            raise ValueError("nonpositive_fold_indices must be sorted unique")
        if not self.reason_codes:
            raise ValueError("reason_codes must not be empty")
        if self.eligible_for_freeze_review != (self.reason_codes == ("qualified",)):
            raise ValueError("eligible_for_freeze_review must match reason_codes")

    def to_dict(self) -> dict[str, object]:
        return {
            "model_family": self.model_family,
            "calibration_variant": self.calibration_variant,
            "fold_count": self.fold_count,
            "minimum_required_fold_count": self.minimum_required_fold_count,
            "minimum_required_trades_per_fold": self.minimum_required_trades_per_fold,
            "minimum_required_mean_net_return": str(
                self.minimum_required_mean_net_return
            ),
            "total_test_trades": self.total_test_trades,
            "long_test_trades": self.long_test_trades,
            "short_test_trades": self.short_test_trades,
            "total_realized_net_return": str(self.total_realized_net_return),
            "mean_realized_net_return": (
                None
                if self.mean_realized_net_return is None
                else str(self.mean_realized_net_return)
            ),
            "minimum_fold_trade_count": self.minimum_fold_trade_count,
            "insufficient_activity_fold_indices": (
                self.insufficient_activity_fold_indices
            ),
            "nonpositive_fold_indices": self.nonpositive_fold_indices,
            "eligible_for_freeze_review": self.eligible_for_freeze_review,
            "reason_codes": self.reason_codes,
        }


@dataclass(frozen=True, slots=True)
class HistoricalArchiveDevelopmentReview:
    preset_name: str
    preset_id: str
    evidence_class: str
    preset_run_receipt_id: str
    bundle_id: str
    comparison_report_id: str
    comparison_version: str
    policy_id: str
    minimum_required_trades_per_fold: int
    minimum_required_mean_net_return: Decimal
    variants: tuple[HistoricalDevelopmentVariantReview, ...]
    status: str
    promotion_eligible: bool = False
    schema_version: int = REVIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "preset_run_receipt_id",
            "bundle_id",
            "comparison_report_id",
            "comparison_version",
            "policy_id",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        if self.evidence_class != EVIDENCE_CLASS:
            raise ValueError("historical review evidence must remain touched")
        if self.minimum_required_trades_per_fold <= 0:
            raise ValueError("minimum_required_trades_per_fold must be positive")
        if not self.minimum_required_mean_net_return.is_finite():
            raise ValueError("minimum_required_mean_net_return must be finite")
        if not self.variants:
            raise ValueError("variants must not be empty")
        expected_status = (
            "freeze_review_available"
            if any(item.eligible_for_freeze_review for item in self.variants)
            else "no_candidate_qualified"
        )
        if self.status != expected_status:
            raise ValueError("status must match variant qualification state")
        if self.promotion_eligible:
            raise ValueError("touched historical review cannot be promotion eligible")
        if self.schema_version != REVIEW_SCHEMA_VERSION:
            raise ValueError("unsupported historical development review schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "evidence_class": self.evidence_class,
            "preset_run_receipt_id": self.preset_run_receipt_id,
            "bundle_id": self.bundle_id,
            "comparison_report_id": self.comparison_report_id,
            "comparison_version": self.comparison_version,
            "policy_id": self.policy_id,
            "minimum_required_trades_per_fold": (
                self.minimum_required_trades_per_fold
            ),
            "minimum_required_mean_net_return": str(
                self.minimum_required_mean_net_return
            ),
            "variants": tuple(item.to_dict() for item in self.variants),
            "status": self.status,
            "promotion_eligible": self.promotion_eligible,
            "schema_version": self.schema_version,
        }

    @property
    def review_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "review_id": self.review_id}


def _variant_review(
    folds: tuple[object, ...],
    *,
    model_family: str,
    calibration_variant: str,
    minimum_required_trades_per_fold: int,
    minimum_required_mean_net_return: Decimal,
    policy: HistoricalDevelopmentReviewPolicy,
) -> HistoricalDevelopmentVariantReview:
    if len(folds) < policy.min_test_folds:
        reason_codes = ("insufficient_test_folds",)
        return HistoricalDevelopmentVariantReview(
            model_family=model_family,
            calibration_variant=calibration_variant,
            fold_count=len(folds),
            minimum_required_fold_count=policy.min_test_folds,
            minimum_required_trades_per_fold=minimum_required_trades_per_fold,
            minimum_required_mean_net_return=minimum_required_mean_net_return,
            total_test_trades=0,
            long_test_trades=0,
            short_test_trades=0,
            total_realized_net_return=Decimal("0"),
            mean_realized_net_return=None,
            minimum_fold_trade_count=0,
            insufficient_activity_fold_indices=(),
            nonpositive_fold_indices=(),
            eligible_for_freeze_review=False,
            reason_codes=reason_codes,
        )

    total_trades = 0
    long_trades = 0
    short_trades = 0
    total_return = Decimal("0")
    fold_trade_counts: list[int] = []
    insufficient: list[int] = []
    nonpositive: list[int] = []

    for raw_fold in folds:
        fold = _mapping(raw_fold, f"{model_family} fold")
        fold_index = _integer(fold.get("fold_index"), "fold_index")
        evaluation = _mapping(
            fold.get(f"{calibration_variant}_test"),
            f"{model_family}.{calibration_variant}_test",
        )
        trade_count = _integer(evaluation.get("trade_count"), "trade_count")
        long_count = _integer(evaluation.get("long_count"), "long_count")
        short_count = _integer(evaluation.get("short_count"), "short_count")
        realized = _decimal(
            evaluation.get("total_realized_net_return"),
            "total_realized_net_return",
        )
        raw_mean = evaluation.get("mean_realized_net_return")
        mean = (
            None
            if raw_mean is None
            else _decimal(raw_mean, "mean_realized_net_return")
        )
        if long_count + short_count != trade_count:
            raise HistoricalArchiveReviewError(
                "test long/short counts do not equal trade_count"
            )
        if (trade_count == 0) != (mean is None):
            raise HistoricalArchiveReviewError(
                "test mean return must be null exactly when trade_count is zero"
            )

        fold_trade_counts.append(trade_count)
        total_trades += trade_count
        long_trades += long_count
        short_trades += short_count
        total_return += realized
        if trade_count < minimum_required_trades_per_fold:
            insufficient.append(fold_index)
        if mean is None or mean <= minimum_required_mean_net_return:
            nonpositive.append(fold_index)

    overall_mean = (
        None
        if total_trades == 0
        else total_return / Decimal(total_trades)
    )
    reasons: list[str] = []
    if insufficient:
        reasons.append("insufficient_test_trades")
    if nonpositive:
        reasons.append("test_fold_not_above_floor")
    if (
        overall_mean is None
        or overall_mean <= minimum_required_mean_net_return
    ):
        reasons.append("overall_test_mean_not_above_floor")
    eligible = not reasons
    if eligible:
        reasons.append("qualified")

    return HistoricalDevelopmentVariantReview(
        model_family=model_family,
        calibration_variant=calibration_variant,
        fold_count=len(folds),
        minimum_required_fold_count=policy.min_test_folds,
        minimum_required_trades_per_fold=minimum_required_trades_per_fold,
        minimum_required_mean_net_return=minimum_required_mean_net_return,
        total_test_trades=total_trades,
        long_test_trades=long_trades,
        short_test_trades=short_trades,
        total_realized_net_return=total_return,
        mean_realized_net_return=overall_mean,
        minimum_fold_trade_count=min(fold_trade_counts),
        insufficient_activity_fold_indices=tuple(sorted(insufficient)),
        nonpositive_fold_indices=tuple(sorted(nonpositive)),
        eligible_for_freeze_review=eligible,
        reason_codes=tuple(reasons),
    )


def build_archive_development_review(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
    policy: HistoricalDevelopmentReviewPolicy = (
        FROZEN_ARCHIVE_DEVELOPMENT_REVIEW_V1
    ),
) -> HistoricalArchiveDevelopmentReview:
    bundle = verify_archive_preset_bundle_receipt(
        output_root / "preset-bundle.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    run_receipt = verify_archive_preset_run_receipt(
        output_root / "preset-run.json",
        preset=preset,
    )

    try:
        comparison = _mapping(
            json.loads((output_root / "comparison.json").read_text(encoding="utf-8")),
            "comparison report",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalArchiveReviewError("COMPARISON_REPORT_INVALID") from exc

    comparison_report_id = _string(
        comparison.get("report_id"),
        "comparison.report_id",
    )
    comparison_version = _string(
        comparison.get("comparison_version"),
        "comparison.comparison_version",
    )
    if comparison_report_id != run_receipt.comparison_report_id:
        raise HistoricalArchiveReviewError("COMPARISON_REPORT_ID_MISMATCH")
    if comparison_version != run_receipt.comparison_version:
        raise HistoricalArchiveReviewError("COMPARISON_VERSION_MISMATCH")
    if comparison.get("evidence_class") != EVIDENCE_CLASS:
        raise HistoricalArchiveReviewError("COMPARISON_EVIDENCE_CLASS_MISMATCH")

    config = _mapping(comparison.get("config"), "comparison.config")
    min_test_trades = _integer(
        config.get("min_validation_trades"),
        "comparison.config.min_validation_trades",
    )
    if min_test_trades <= 0:
        raise HistoricalArchiveReviewError("MINIMUM_TEST_TRADES_INVALID")
    mean_floor = _decimal(
        config.get("min_validation_mean_net_return"),
        "comparison.config.min_validation_mean_net_return",
    )

    variants: list[HistoricalDevelopmentVariantReview] = []
    for model_family, field in VARIANT_SPECS:
        folds = _sequence(comparison.get(field), field)
        for calibration_variant in policy.calibration_variants:
            variants.append(
                _variant_review(
                    folds,
                    model_family=model_family,
                    calibration_variant=calibration_variant,
                    minimum_required_trades_per_fold=min_test_trades,
                    minimum_required_mean_net_return=mean_floor,
                    policy=policy,
                )
            )

    resolved = tuple(variants)
    return HistoricalArchiveDevelopmentReview(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        evidence_class=EVIDENCE_CLASS,
        preset_run_receipt_id=run_receipt.receipt_id,
        bundle_id=bundle.bundle_id,
        comparison_report_id=comparison_report_id,
        comparison_version=comparison_version,
        policy_id=policy.policy_id,
        minimum_required_trades_per_fold=min_test_trades,
        minimum_required_mean_net_return=mean_floor,
        variants=resolved,
        status=(
            "freeze_review_available"
            if any(item.eligible_for_freeze_review for item in resolved)
            else "no_candidate_qualified"
        ),
    )


def write_archive_development_review(
    output_root: Path,
    review: HistoricalArchiveDevelopmentReview,
) -> Path:
    path = output_root / "development-review.json"
    payload = (_canonical_json(review.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveReviewError("DEVELOPMENT_REVIEW_CONFLICT")
        return path
    temporary = output_root / ".development-review.json.tmp"
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
