from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from cocomelon.research.learning_candidate_package import (
    verify_learning_candidate_package,
)
from cocomelon.research.learning_cycle import (
    DECISION_POLICY,
    MIN_BLOCK_TRADES,
    MIN_VALIDATION_TRADES,
    STABILITY_BLOCKS,
    VALIDATION_ROWS,
)

LEARNING_CLEAN_VALIDATION_SPEC_SCHEMA_VERSION = 1
LEARNING_CLEAN_VALIDATION_POLICY = "prospective-clean-first-settled-trades-v1"
LEARNING_CLEAN_SAMPLE_POLICY = "first-settled-candidate-paper-trades-after-start-v1"
LEARNING_CLEAN_METRIC = "realized_net_r"
LEARNING_CLEAN_QUALIFICATION_OPERATOR = "strict_gt"
MIN_CLEAN_MEAN_NET_R = Decimal(str(DECISION_POLICY["min_validation_mean_target"]))


class LearningCleanValidationSpecError(RuntimeError):
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


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCleanValidationSpecError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCleanValidationSpecError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCleanValidationSpecError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCleanValidationSpecError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningCleanValidationSpecError(
            f"{field} must be a decimal string"
        )
    try:
        resolved = Decimal(value)
    except Exception as exc:
        raise LearningCleanValidationSpecError(
            f"{field} must be a decimal string"
        ) from exc
    if not resolved.is_finite():
        raise LearningCleanValidationSpecError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class LearningCleanValidationSpec:
    candidate_id: str
    candidate_package_id: str
    candidate_package_receipt_sha256: str
    experiment_id: str
    model_family: str
    validation_start_ms: int
    target_settled_trades: int
    stability_blocks: int
    trades_per_block: int
    metric: str
    min_overall_mean_net_r: Decimal
    min_block_mean_net_r: Decimal
    qualification_operator: str
    sample_policy: str
    validation_policy: str
    paper_only: bool = True
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CLEAN_VALIDATION_SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_package_id",
            "candidate_package_receipt_sha256",
            "experiment_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.target_settled_trades != VALIDATION_ROWS:
            raise ValueError("target_settled_trades must remain frozen")
        if self.target_settled_trades != MIN_VALIDATION_TRADES:
            raise ValueError("target settled trades must match learning policy")
        if self.stability_blocks != STABILITY_BLOCKS:
            raise ValueError("stability_blocks must remain frozen")
        if self.trades_per_block != MIN_BLOCK_TRADES:
            raise ValueError("trades_per_block must remain frozen")
        if self.stability_blocks * self.trades_per_block != self.target_settled_trades:
            raise ValueError("validation blocks must partition the settled trade target")
        if self.metric != LEARNING_CLEAN_METRIC:
            raise ValueError("unsupported learning clean validation metric")
        if (
            not self.min_overall_mean_net_r.is_finite()
            or not self.min_block_mean_net_r.is_finite()
        ):
            raise ValueError("clean validation mean floors must be finite")
        if self.min_overall_mean_net_r != MIN_CLEAN_MEAN_NET_R:
            raise ValueError("overall clean validation floor must remain frozen")
        if self.min_block_mean_net_r != MIN_CLEAN_MEAN_NET_R:
            raise ValueError("block clean validation floor must remain frozen")
        if self.qualification_operator != LEARNING_CLEAN_QUALIFICATION_OPERATOR:
            raise ValueError("unsupported clean validation qualification operator")
        if self.sample_policy != LEARNING_CLEAN_SAMPLE_POLICY:
            raise ValueError("unsupported clean validation sample policy")
        if self.validation_policy != LEARNING_CLEAN_VALIDATION_POLICY:
            raise ValueError("unsupported learning clean validation policy")
        if not self.paper_only:
            raise ValueError("learning clean validation must remain paper-only")
        if not self.prospective_only:
            raise ValueError("learning clean validation must remain prospective-only")
        if not self.research_only:
            raise ValueError("learning clean validation must remain research-only")
        if self.promotion_eligible:
            raise ValueError("validation spec cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("validation spec cannot authorize execution")
        if self.schema_version != LEARNING_CLEAN_VALIDATION_SPEC_SCHEMA_VERSION:
            raise ValueError("unsupported learning clean validation spec schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "candidate_package_receipt_sha256": (
                self.candidate_package_receipt_sha256
            ),
            "experiment_id": self.experiment_id,
            "model_family": self.model_family,
            "validation_start_ms": self.validation_start_ms,
            "target_settled_trades": self.target_settled_trades,
            "stability_blocks": self.stability_blocks,
            "trades_per_block": self.trades_per_block,
            "metric": self.metric,
            "min_overall_mean_net_r": str(self.min_overall_mean_net_r),
            "min_block_mean_net_r": str(self.min_block_mean_net_r),
            "qualification_operator": self.qualification_operator,
            "sample_policy": self.sample_policy,
            "validation_policy": self.validation_policy,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def spec_id(self) -> str:
        return _sha256_bytes(
            _canonical_json(self.identity_payload()).encode("utf-8")
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "spec_id": self.spec_id}


def build_learning_clean_validation_spec(
    package_root: Path,
) -> LearningCleanValidationSpec:
    package = verify_learning_candidate_package(package_root)
    receipt_path = package_root / "candidate-package.json"
    try:
        receipt_bytes = receipt_path.read_bytes()
    except OSError as exc:
        raise LearningCleanValidationSpecError(
            "LEARNING_CLEAN_VALIDATION_PACKAGE_RECEIPT_UNREADABLE"
        ) from exc
    return LearningCleanValidationSpec(
        candidate_id=package.candidate_id,
        candidate_package_id=package.package_id,
        candidate_package_receipt_sha256=_sha256_bytes(receipt_bytes),
        experiment_id=package.experiment_id,
        model_family=package.model_family,
        validation_start_ms=package.validation_not_before_ms,
        target_settled_trades=VALIDATION_ROWS,
        stability_blocks=STABILITY_BLOCKS,
        trades_per_block=MIN_BLOCK_TRADES,
        metric=LEARNING_CLEAN_METRIC,
        min_overall_mean_net_r=MIN_CLEAN_MEAN_NET_R,
        min_block_mean_net_r=MIN_CLEAN_MEAN_NET_R,
        qualification_operator=LEARNING_CLEAN_QUALIFICATION_OPERATOR,
        sample_policy=LEARNING_CLEAN_SAMPLE_POLICY,
        validation_policy=LEARNING_CLEAN_VALIDATION_POLICY,
    )


def write_learning_clean_validation_spec(
    output_root: Path,
    spec: LearningCleanValidationSpec,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "candidate-validation-spec.json"
    payload = (_canonical_json(spec.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCleanValidationSpecError(
                "LEARNING_CLEAN_VALIDATION_SPEC_CONFLICT"
            )
        return path

    temporary = output_root / ".candidate-validation-spec.json.tmp"
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


def _spec_from_payload(raw: dict[str, object]) -> LearningCleanValidationSpec:
    try:
        spec = LearningCleanValidationSpec(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_package_id=_string(
                raw.get("candidate_package_id"),
                "candidate_package_id",
            ),
            candidate_package_receipt_sha256=_string(
                raw.get("candidate_package_receipt_sha256"),
                "candidate_package_receipt_sha256",
            ),
            experiment_id=_string(raw.get("experiment_id"), "experiment_id"),
            model_family=_string(raw.get("model_family"), "model_family"),
            validation_start_ms=_integer(
                raw.get("validation_start_ms"),
                "validation_start_ms",
            ),
            target_settled_trades=_integer(
                raw.get("target_settled_trades"),
                "target_settled_trades",
            ),
            stability_blocks=_integer(
                raw.get("stability_blocks"),
                "stability_blocks",
            ),
            trades_per_block=_integer(
                raw.get("trades_per_block"),
                "trades_per_block",
            ),
            metric=_string(raw.get("metric"), "metric"),
            min_overall_mean_net_r=_decimal(
                raw.get("min_overall_mean_net_r"),
                "min_overall_mean_net_r",
            ),
            min_block_mean_net_r=_decimal(
                raw.get("min_block_mean_net_r"),
                "min_block_mean_net_r",
            ),
            qualification_operator=_string(
                raw.get("qualification_operator"),
                "qualification_operator",
            ),
            sample_policy=_string(raw.get("sample_policy"), "sample_policy"),
            validation_policy=_string(
                raw.get("validation_policy"),
                "validation_policy",
            ),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
            ),
            research_only=_boolean(raw.get("research_only"), "research_only"),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"),
                "promotion_eligible",
            ),
            execution_ready=_boolean(
                raw.get("execution_ready"),
                "execution_ready",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except ValueError as exc:
        raise LearningCleanValidationSpecError(
            "LEARNING_CLEAN_VALIDATION_SPEC_INVALID"
        ) from exc
    if raw.get("spec_id") != spec.spec_id:
        raise LearningCleanValidationSpecError(
            "LEARNING_CLEAN_VALIDATION_SPEC_ID_MISMATCH"
        )
    return spec


def load_learning_clean_validation_spec(
    path: Path,
) -> LearningCleanValidationSpec:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(
            json.loads(stored_bytes),
            "learning clean validation spec",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCleanValidationSpecError(
            "LEARNING_CLEAN_VALIDATION_SPEC_INVALID"
        ) from exc
    spec = _spec_from_payload(raw)
    canonical = (_canonical_json(spec.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningCleanValidationSpecError(
            "LEARNING_CLEAN_VALIDATION_SPEC_NON_CANONICAL"
        )
    return spec


def verify_learning_clean_validation_spec(
    path: Path,
    *,
    package_root: Path,
) -> LearningCleanValidationSpec:
    stored = load_learning_clean_validation_spec(path)
    expected = build_learning_clean_validation_spec(package_root)
    if stored != expected:
        raise LearningCleanValidationSpecError(
            "LEARNING_CLEAN_VALIDATION_SPEC_EVIDENCE_MISMATCH"
        )
    return stored
