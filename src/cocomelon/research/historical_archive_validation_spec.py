from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from cocomelon.hyperliquid.client import INTERVAL_MS
from cocomelon.research.historical_archive_model_artifact import (
    HistoricalArchiveCandidateModelArtifact,
    verify_archive_candidate_model_artifact,
)
from cocomelon.research.historical_archive_presets import (
    EVIDENCE_CLASS,
    HistoricalArchiveExperimentPreset,
)
from cocomelon.research.historical_archive_training_plan import (
    verify_archive_candidate_training_plan,
)
from cocomelon.research.prospective_context_evidence import (
    PROSPECTIVE_EVIDENCE_CLASS,
)

DAY_MS = 86_400_000
VALIDATION_WINDOW_MS = 45 * DAY_MS
MIN_CAPTURE_COVERAGE = Decimal("0.90")
MIN_SETTLED_TRADES = 80
STABILITY_BLOCKS = 4
MIN_BLOCK_TRADES = 15
MIN_MEAN_NET_RETURN = Decimal("0")
MIN_BLOCK_MEAN_NET_RETURN = Decimal("0")
DECISION_POLICY = "cost_adjusted_directional_threshold_v1"
VALIDATION_POLICY = "prospective-clean-45d-stability-v1"
SPEC_SCHEMA_VERSION = 1


class HistoricalArchiveValidationSpecError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveValidationSpecError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise HistoricalArchiveValidationSpecError(f"{field} must be a sequence")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveValidationSpecError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveValidationSpecError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveValidationSpecError(f"{field} must be boolean")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise HistoricalArchiveValidationSpecError(
            f"{field} must be a decimal string"
        )
    resolved = Decimal(value)
    if not resolved.is_finite():
        raise HistoricalArchiveValidationSpecError(f"{field} must be finite")
    return resolved


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


@dataclass(frozen=True, slots=True)
class HistoricalArchiveCleanValidationSpec:
    preset_name: str
    preset_id: str
    source_evidence_class: str
    validation_evidence_class: str
    candidate_id: str
    training_plan_id: str
    calibration_id: str
    model_artifact_id: str
    model_payload_sha256: str
    model_family: str
    calibration_variant: str
    model_format: str
    markets: tuple[str, ...]
    anchor_interval: str
    anchor_interval_ms: int
    anchor_end_offset_ms: int
    horizon_thresholds: tuple[tuple[int, Decimal | None], ...]
    allow_coin_calibration: bool
    min_sample_count: int
    decision_policy: str
    execution_policy: str
    max_concurrent_positions: int | None
    costs: dict[str, str]
    validation_start_ms: int
    validation_end_ms: int
    min_capture_coverage: Decimal
    min_settled_trades: int
    stability_blocks: int
    min_block_trades: int
    min_mean_net_return: Decimal
    min_block_mean_net_return: Decimal
    validation_policy: str = VALIDATION_POLICY
    paper_only: bool = True
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = SPEC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "preset_name",
            "preset_id",
            "candidate_id",
            "training_plan_id",
            "calibration_id",
            "model_artifact_id",
            "model_payload_sha256",
            "model_family",
            "calibration_variant",
            "model_format",
            "anchor_interval",
            "decision_policy",
            "execution_policy",
            "validation_policy",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty")
        for field in (
            "candidate_id",
            "training_plan_id",
            "calibration_id",
            "model_artifact_id",
            "model_payload_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.source_evidence_class != EVIDENCE_CLASS:
            raise ValueError("source evidence must remain touched_development")
        if self.validation_evidence_class != PROSPECTIVE_EVIDENCE_CLASS:
            raise ValueError("validation evidence must be prospective_clean")
        if tuple(sorted(set(self.markets))) != self.markets or not self.markets:
            raise ValueError("markets must be sorted unique and non-empty")
        if self.anchor_interval not in INTERVAL_MS:
            raise ValueError("unsupported anchor_interval")
        if self.anchor_interval_ms != INTERVAL_MS[self.anchor_interval]:
            raise ValueError("anchor_interval_ms must match anchor_interval")
        if self.anchor_end_offset_ms != self.anchor_interval_ms - 1:
            raise ValueError("anchor_end_offset_ms must target closed candle ends")
        if not self.horizon_thresholds:
            raise ValueError("horizon_thresholds must not be empty")
        horizons = tuple(item[0] for item in self.horizon_thresholds)
        if horizons != tuple(sorted(set(horizons))):
            raise ValueError("horizon thresholds must be sorted unique")
        if not any(
            threshold is not None
            for _horizon_ms, threshold in self.horizon_thresholds
        ):
            raise ValueError("clean validation candidate must trade a horizon")
        for horizon_ms, threshold in self.horizon_thresholds:
            if horizon_ms <= 0:
                raise ValueError("horizon_ms must be positive")
            if threshold is not None and (
                not threshold.is_finite() or threshold < 0
            ):
                raise ValueError("threshold must be non-negative finite")
        if self.min_sample_count <= 0:
            raise ValueError("min_sample_count must be positive")
        if self.decision_policy != DECISION_POLICY:
            raise ValueError("unsupported decision_policy")
        if self.execution_policy not in {
            "independent_horizon",
            "single_position_occupancy",
            "portfolio_capacity",
        }:
            raise ValueError("unsupported execution_policy")
        if self.execution_policy == "portfolio_capacity":
            if self.max_concurrent_positions is None:
                raise ValueError("portfolio capacity requires max_concurrent_positions")
            if self.max_concurrent_positions <= 0:
                raise ValueError("max_concurrent_positions must be positive")
        elif self.max_concurrent_positions is not None:
            raise ValueError("capacity only applies to portfolio policy")
        required_costs = {
            "round_trip_fee_fraction",
            "round_trip_slippage_fraction",
            "funding_reserve_fraction_per_hour",
        }
        if set(self.costs) != required_costs:
            raise ValueError("costs must contain frozen execution cost fields")
        for value in self.costs.values():
            resolved = Decimal(value)
            if not resolved.is_finite() or resolved < 0:
                raise ValueError("cost values must be non-negative finite")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.validation_end_ms - self.validation_start_ms != VALIDATION_WINDOW_MS:
            raise ValueError("validation window must remain frozen at 45 days")
        if self.min_capture_coverage != MIN_CAPTURE_COVERAGE:
            raise ValueError("min_capture_coverage must remain frozen")
        if self.min_settled_trades != MIN_SETTLED_TRADES:
            raise ValueError("min_settled_trades must remain frozen")
        if self.stability_blocks != STABILITY_BLOCKS:
            raise ValueError("stability_blocks must remain frozen")
        if self.min_block_trades != MIN_BLOCK_TRADES:
            raise ValueError("min_block_trades must remain frozen")
        if self.min_mean_net_return != MIN_MEAN_NET_RETURN:
            raise ValueError("min_mean_net_return must remain frozen")
        if self.min_block_mean_net_return != MIN_BLOCK_MEAN_NET_RETURN:
            raise ValueError("min_block_mean_net_return must remain frozen")
        if self.validation_policy != VALIDATION_POLICY:
            raise ValueError("unsupported validation_policy")
        if self.expected_anchor_count <= 0:
            raise ValueError("validation window must contain expected anchors")
        if self.expected_anchor_count % self.stability_blocks != 0:
            raise ValueError("expected anchors must divide evenly into blocks")
        if not self.paper_only:
            raise ValueError("clean validation spec must remain paper-only")
        if not self.prospective_only:
            raise ValueError("clean validation spec must remain prospective-only")
        if self.promotion_eligible:
            raise ValueError("validation spec is not itself promotion eligible")
        if self.execution_ready:
            raise ValueError("validation spec is not an execution artifact")
        if self.schema_version != SPEC_SCHEMA_VERSION:
            raise ValueError("unsupported clean validation spec schema")

    @property
    def active_horizons(self) -> tuple[int, ...]:
        return tuple(
            horizon_ms
            for horizon_ms, threshold in self.horizon_thresholds
            if threshold is not None
        )

    @property
    def maximum_active_horizon_ms(self) -> int:
        return max(self.active_horizons)

    @property
    def finalization_not_before_ms(self) -> int:
        return self.validation_end_ms + self.maximum_active_horizon_ms

    @property
    def first_expected_anchor_ms(self) -> int:
        base = self.validation_start_ms - (
            self.validation_start_ms % self.anchor_interval_ms
        )
        candidate = base + self.anchor_end_offset_ms
        if candidate < self.validation_start_ms:
            candidate += self.anchor_interval_ms
        return candidate

    @property
    def expected_anchor_count(self) -> int:
        first = self.first_expected_anchor_ms
        if first >= self.validation_end_ms:
            return 0
        return (
            (self.validation_end_ms - 1 - first) // self.anchor_interval_ms
        ) + 1

    @property
    def anchors_per_stability_block(self) -> int:
        return self.expected_anchor_count // self.stability_blocks

    def identity_payload(self) -> dict[str, object]:
        return {
            "preset_name": self.preset_name,
            "preset_id": self.preset_id,
            "source_evidence_class": self.source_evidence_class,
            "validation_evidence_class": self.validation_evidence_class,
            "candidate_id": self.candidate_id,
            "training_plan_id": self.training_plan_id,
            "calibration_id": self.calibration_id,
            "model_artifact_id": self.model_artifact_id,
            "model_payload_sha256": self.model_payload_sha256,
            "model_family": self.model_family,
            "calibration_variant": self.calibration_variant,
            "model_format": self.model_format,
            "markets": self.markets,
            "anchor_interval": self.anchor_interval,
            "anchor_interval_ms": self.anchor_interval_ms,
            "anchor_end_offset_ms": self.anchor_end_offset_ms,
            "horizon_thresholds": tuple(
                {
                    "horizon_ms": horizon_ms,
                    "threshold": None if threshold is None else str(threshold),
                }
                for horizon_ms, threshold in self.horizon_thresholds
            ),
            "active_horizons": self.active_horizons,
            "maximum_active_horizon_ms": self.maximum_active_horizon_ms,
            "allow_coin_calibration": self.allow_coin_calibration,
            "min_sample_count": self.min_sample_count,
            "decision_policy": self.decision_policy,
            "execution_policy": self.execution_policy,
            "max_concurrent_positions": self.max_concurrent_positions,
            "costs": self.costs,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "min_capture_coverage": str(self.min_capture_coverage),
            "min_settled_trades": self.min_settled_trades,
            "stability_blocks": self.stability_blocks,
            "min_block_trades": self.min_block_trades,
            "min_mean_net_return": str(self.min_mean_net_return),
            "min_block_mean_net_return": str(self.min_block_mean_net_return),
            "expected_anchor_count": self.expected_anchor_count,
            "anchors_per_stability_block": self.anchors_per_stability_block,
            "validation_policy": self.validation_policy,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def spec_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "spec_id": self.spec_id}


def _artifact_lineage_matches_plan(
    artifact: HistoricalArchiveCandidateModelArtifact,
    plan: object,
) -> bool:
    return (
        artifact.training_plan_id == getattr(plan, "plan_id", None)
        and artifact.candidate_id == getattr(plan, "candidate_id", None)
        and artifact.model_family == getattr(plan, "model_family", None)
        and artifact.calibration_variant
        == getattr(plan, "calibration_variant", None)
        and artifact.validation_not_before_ms
        == getattr(plan, "validation_not_before_ms", None)
    )


def build_archive_clean_validation_spec(
    preset: HistoricalArchiveExperimentPreset,
    *,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCleanValidationSpec:
    artifact = verify_archive_candidate_model_artifact(
        output_root / "candidate-model.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    plan = verify_archive_candidate_training_plan(
        output_root / "candidate-training-plan.json",
        preset=preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    if not _artifact_lineage_matches_plan(artifact, plan):
        raise HistoricalArchiveValidationSpecError(
            "ARCHIVE_VALIDATION_SPEC_LINEAGE_MISMATCH"
        )
    anchor_interval = plan.anchor_interval
    return HistoricalArchiveCleanValidationSpec(
        preset_name=preset.name,
        preset_id=preset.preset_id,
        source_evidence_class=preset.evidence_class,
        validation_evidence_class=PROSPECTIVE_EVIDENCE_CLASS,
        candidate_id=artifact.candidate_id,
        training_plan_id=artifact.training_plan_id,
        calibration_id=artifact.calibration_id,
        model_artifact_id=artifact.artifact_id,
        model_payload_sha256=artifact.model_payload_sha256,
        model_family=artifact.model_family,
        calibration_variant=artifact.calibration_variant,
        model_format=artifact.model_format,
        markets=tuple(sorted(market.canonical for market in preset.markets)),
        anchor_interval=anchor_interval,
        anchor_interval_ms=INTERVAL_MS[anchor_interval],
        anchor_end_offset_ms=INTERVAL_MS[anchor_interval] - 1,
        horizon_thresholds=artifact.selected_horizon_thresholds,
        allow_coin_calibration=artifact.allow_coin_calibration,
        min_sample_count=artifact.min_sample_count,
        decision_policy=DECISION_POLICY,
        execution_policy=artifact.execution_policy,
        max_concurrent_positions=artifact.max_concurrent_positions,
        costs=dict(artifact.costs),
        validation_start_ms=artifact.validation_not_before_ms,
        validation_end_ms=(
            artifact.validation_not_before_ms + VALIDATION_WINDOW_MS
        ),
        min_capture_coverage=MIN_CAPTURE_COVERAGE,
        min_settled_trades=MIN_SETTLED_TRADES,
        stability_blocks=STABILITY_BLOCKS,
        min_block_trades=MIN_BLOCK_TRADES,
        min_mean_net_return=MIN_MEAN_NET_RETURN,
        min_block_mean_net_return=MIN_BLOCK_MEAN_NET_RETURN,
    )


def write_archive_clean_validation_spec(
    output_root: Path,
    spec: HistoricalArchiveCleanValidationSpec,
) -> Path:
    path = output_root / "candidate-validation-spec.json"
    payload = (_canonical_json(spec.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise HistoricalArchiveValidationSpecError(
                "ARCHIVE_VALIDATION_SPEC_CONFLICT"
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


def load_archive_clean_validation_spec(
    path: Path,
) -> HistoricalArchiveCleanValidationSpec:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "clean validation spec",
        )
        raw_costs = _mapping(raw.get("costs"), "costs")
        costs = {
            key: _string(raw_costs.get(key), f"costs.{key}")
            for key in (
                "round_trip_fee_fraction",
                "round_trip_slippage_fraction",
                "funding_reserve_fraction_per_hour",
            )
        }
        thresholds = tuple(
            (
                _integer(
                    _mapping(item, "horizon threshold").get("horizon_ms"),
                    "horizon threshold horizon_ms",
                ),
                _optional_decimal(
                    _mapping(item, "horizon threshold").get("threshold"),
                    "horizon threshold threshold",
                ),
            )
            for item in _sequence(
                raw.get("horizon_thresholds"),
                "horizon_thresholds",
            )
        )
        spec = HistoricalArchiveCleanValidationSpec(
            preset_name=_string(raw.get("preset_name"), "preset_name"),
            preset_id=_string(raw.get("preset_id"), "preset_id"),
            source_evidence_class=_string(
                raw.get("source_evidence_class"),
                "source_evidence_class",
            ),
            validation_evidence_class=_string(
                raw.get("validation_evidence_class"),
                "validation_evidence_class",
            ),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            training_plan_id=_string(
                raw.get("training_plan_id"),
                "training_plan_id",
            ),
            calibration_id=_string(
                raw.get("calibration_id"),
                "calibration_id",
            ),
            model_artifact_id=_string(
                raw.get("model_artifact_id"),
                "model_artifact_id",
            ),
            model_payload_sha256=_string(
                raw.get("model_payload_sha256"),
                "model_payload_sha256",
            ),
            model_family=_string(raw.get("model_family"), "model_family"),
            calibration_variant=_string(
                raw.get("calibration_variant"),
                "calibration_variant",
            ),
            model_format=_string(raw.get("model_format"), "model_format"),
            markets=tuple(
                _string(item, "market")
                for item in _sequence(raw.get("markets"), "markets")
            ),
            anchor_interval=_string(
                raw.get("anchor_interval"),
                "anchor_interval",
            ),
            anchor_interval_ms=_integer(
                raw.get("anchor_interval_ms"),
                "anchor_interval_ms",
            ),
            anchor_end_offset_ms=_integer(
                raw.get("anchor_end_offset_ms"),
                "anchor_end_offset_ms",
            ),
            horizon_thresholds=thresholds,
            allow_coin_calibration=_boolean(
                raw.get("allow_coin_calibration"),
                "allow_coin_calibration",
            ),
            min_sample_count=_integer(
                raw.get("min_sample_count"),
                "min_sample_count",
            ),
            decision_policy=_string(
                raw.get("decision_policy"),
                "decision_policy",
            ),
            execution_policy=_string(
                raw.get("execution_policy"),
                "execution_policy",
            ),
            max_concurrent_positions=_optional_integer(
                raw.get("max_concurrent_positions"),
                "max_concurrent_positions",
            ),
            costs=costs,
            validation_start_ms=_integer(
                raw.get("validation_start_ms"),
                "validation_start_ms",
            ),
            validation_end_ms=_integer(
                raw.get("validation_end_ms"),
                "validation_end_ms",
            ),
            min_capture_coverage=_decimal(
                raw.get("min_capture_coverage"),
                "min_capture_coverage",
            ),
            min_settled_trades=_integer(
                raw.get("min_settled_trades"),
                "min_settled_trades",
            ),
            stability_blocks=_integer(
                raw.get("stability_blocks"),
                "stability_blocks",
            ),
            min_block_trades=_integer(
                raw.get("min_block_trades"),
                "min_block_trades",
            ),
            min_mean_net_return=_decimal(
                raw.get("min_mean_net_return"),
                "min_mean_net_return",
            ),
            min_block_mean_net_return=_decimal(
                raw.get("min_block_mean_net_return"),
                "min_block_mean_net_return",
            ),
            validation_policy=_string(
                raw.get("validation_policy"),
                "validation_policy",
            ),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
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
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        ArithmeticError,
    ) as exc:
        raise HistoricalArchiveValidationSpecError(
            "ARCHIVE_VALIDATION_SPEC_INVALID"
        ) from exc

    if _string(raw.get("spec_id"), "spec_id") != spec.spec_id:
        raise HistoricalArchiveValidationSpecError(
            "ARCHIVE_VALIDATION_SPEC_ID_MISMATCH"
        )
    canonical = _canonical_json(spec.to_dict()) + "\n"
    if path.read_text(encoding="utf-8") != canonical:
        raise HistoricalArchiveValidationSpecError(
            "ARCHIVE_VALIDATION_SPEC_NON_CANONICAL"
        )
    return spec


def verify_archive_clean_validation_spec(
    path: Path,
    *,
    preset: HistoricalArchiveExperimentPreset,
    archive_root: Path,
    source_root: Path,
    output_root: Path,
) -> HistoricalArchiveCleanValidationSpec:
    loaded = load_archive_clean_validation_spec(path)
    expected = build_archive_clean_validation_spec(
        preset,
        archive_root=archive_root,
        source_root=source_root,
        output_root=output_root,
    )
    if loaded != expected:
        raise HistoricalArchiveValidationSpecError(
            "ARCHIVE_VALIDATION_SPEC_EVIDENCE_MISMATCH"
        )
    return expected
