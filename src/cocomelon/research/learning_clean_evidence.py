from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_candidate_predictor import (
    LEARNING_CANDIDATE_PREDICTION_SCHEMA_VERSION,
    LearningCandidatePrediction,
)
from cocomelon.research.learning_clean_validation_spec import (
    LearningCleanValidationSpec,
)

LEARNING_CLEAN_EVIDENCE_MANIFEST_SCHEMA_VERSION = 1
LEARNING_CLEAN_OUTCOME_SCHEMA_VERSION = 1


class LearningCleanEvidenceError(RuntimeError):
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


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCleanEvidenceError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise LearningCleanEvidenceError(f"{field} must be a sequence")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCleanEvidenceError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCleanEvidenceError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCleanEvidenceError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningCleanEvidenceError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise LearningCleanEvidenceError(
            f"{field} must be a decimal string"
        ) from exc
    if not resolved.is_finite():
        raise LearningCleanEvidenceError(f"{field} must be finite")
    return resolved


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _write_consistent(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCleanEvidenceError(
                f"LEARNING_CLEAN_EVIDENCE_CONFLICT:{path.name}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True, slots=True)
class LearningCleanEvidenceManifest:
    validation_spec_id: str
    candidate_id: str
    candidate_package_id: str
    experiment_id: str
    model_family: str
    validation_start_ms: int
    target_settled_trades: int
    sample_policy: str
    metric: str
    schema_version: int = LEARNING_CLEAN_EVIDENCE_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "validation_spec_id",
            "candidate_id",
            "candidate_package_id",
            "experiment_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.target_settled_trades <= 0:
            raise ValueError("target_settled_trades must be positive")
        if not self.sample_policy.strip() or not self.metric.strip():
            raise ValueError("sample_policy and metric must not be empty")
        if self.schema_version != LEARNING_CLEAN_EVIDENCE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported learning clean evidence manifest schema")

    @classmethod
    def from_spec(
        cls,
        spec: LearningCleanValidationSpec,
    ) -> LearningCleanEvidenceManifest:
        return cls(
            validation_spec_id=spec.spec_id,
            candidate_id=spec.candidate_id,
            candidate_package_id=spec.candidate_package_id,
            experiment_id=spec.experiment_id,
            model_family=spec.model_family,
            validation_start_ms=spec.validation_start_ms,
            target_settled_trades=spec.target_settled_trades,
            sample_policy=spec.sample_policy,
            metric=spec.metric,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "experiment_id": self.experiment_id,
            "model_family": self.model_family,
            "validation_start_ms": self.validation_start_ms,
            "target_settled_trades": self.target_settled_trades,
            "sample_policy": self.sample_policy,
            "metric": self.metric,
            "schema_version": self.schema_version,
        }

    @property
    def manifest_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "manifest_id": self.manifest_id}


@dataclass(frozen=True, slots=True)
class LearningCleanTradeOutcome:
    prediction_id: str
    candidate_id: str
    validation_spec_id: str
    candidate_package_id: str
    source_trade_id: str
    market: str
    direction: str
    opened_at_ms: int
    closed_at_ms: int
    net_r: Decimal
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CLEAN_OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "prediction_id",
            "candidate_id",
            "validation_spec_id",
            "candidate_package_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.source_trade_id.strip():
            raise ValueError("source_trade_id must not be empty")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.direction not in {Direction.LONG.value, Direction.SHORT.value}:
            raise ValueError("clean outcome direction must be long or short")
        if self.opened_at_ms < 0 or self.closed_at_ms < self.opened_at_ms:
            raise ValueError("clean outcome timestamps are invalid")
        if not self.net_r.is_finite():
            raise ValueError("clean outcome net_r must be finite")
        if not self.paper_only or not self.research_only:
            raise ValueError("clean outcome must remain paper research")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("clean outcome cannot authorize promotion or execution")
        if self.schema_version != LEARNING_CLEAN_OUTCOME_SCHEMA_VERSION:
            raise ValueError("unsupported learning clean outcome schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "prediction_id": self.prediction_id,
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "candidate_package_id": self.candidate_package_id,
            "source_trade_id": self.source_trade_id,
            "market": self.market,
            "direction": self.direction,
            "opened_at_ms": self.opened_at_ms,
            "closed_at_ms": self.closed_at_ms,
            "net_r": str(self.net_r),
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def outcome_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "outcome_id": self.outcome_id}


def _prediction_from_payload(raw: dict[str, object]) -> LearningCandidatePrediction:
    try:
        registry = tuple(
            _string(value, "prediction feature_registry")
            for value in _sequence(
                raw.get("feature_registry"),
                "prediction feature_registry",
            )
        )
        values = tuple(
            _string(value, "prediction feature_values")
            for value in _sequence(
                raw.get("feature_values"),
                "prediction feature_values",
            )
        )
        prediction = LearningCandidatePrediction(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            candidate_package_id=_string(
                raw.get("candidate_package_id"),
                "candidate_package_id",
            ),
            experiment_id=_string(raw.get("experiment_id"), "experiment_id"),
            model_family=_string(raw.get("model_family"), "model_family"),
            observed_at_ms=_integer(raw.get("observed_at_ms"), "observed_at_ms"),
            feature_registry=registry,
            feature_values=values,
            predicted_net_r=_optional_decimal(
                raw.get("predicted_net_r"),
                "predicted_net_r",
            ),
            prediction_threshold=_decimal(
                raw.get("prediction_threshold"),
                "prediction_threshold",
            ),
            trade_eligible=_boolean(raw.get("trade_eligible"), "trade_eligible"),
            reason_code=_string(raw.get("reason_code"), "reason_code"),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
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
        raise LearningCleanEvidenceError(
            "LEARNING_CLEAN_PREDICTION_INVALID"
        ) from exc
    if raw.get("prediction_id") != prediction.prediction_id:
        raise LearningCleanEvidenceError(
            "LEARNING_CLEAN_PREDICTION_ID_MISMATCH"
        )
    if prediction.schema_version != LEARNING_CANDIDATE_PREDICTION_SCHEMA_VERSION:
        raise LearningCleanEvidenceError(
            "LEARNING_CLEAN_PREDICTION_SCHEMA_MISMATCH"
        )
    return prediction


def _outcome_from_payload(raw: dict[str, object]) -> LearningCleanTradeOutcome:
    try:
        outcome = LearningCleanTradeOutcome(
            prediction_id=_string(raw.get("prediction_id"), "prediction_id"),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            candidate_package_id=_string(
                raw.get("candidate_package_id"),
                "candidate_package_id",
            ),
            source_trade_id=_string(
                raw.get("source_trade_id"),
                "source_trade_id",
            ),
            market=_string(raw.get("market"), "market"),
            direction=_string(raw.get("direction"), "direction"),
            opened_at_ms=_integer(raw.get("opened_at_ms"), "opened_at_ms"),
            closed_at_ms=_integer(raw.get("closed_at_ms"), "closed_at_ms"),
            net_r=_decimal(raw.get("net_r"), "net_r"),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
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
        raise LearningCleanEvidenceError(
            "LEARNING_CLEAN_OUTCOME_INVALID"
        ) from exc
    if raw.get("outcome_id") != outcome.outcome_id:
        raise LearningCleanEvidenceError(
            "LEARNING_CLEAN_OUTCOME_ID_MISMATCH"
        )
    return outcome


def parse_learning_clean_prediction_payload(
    value: object,
) -> LearningCandidatePrediction:
    return _prediction_from_payload(
        _mapping(value, "learning clean prediction")
    )


def parse_learning_clean_outcome_payload(
    value: object,
) -> LearningCleanTradeOutcome:
    return _outcome_from_payload(
        _mapping(value, "learning clean outcome")
    )


class LearningCleanEvidenceStore:
    def __init__(
        self,
        root: Path,
        *,
        spec: LearningCleanValidationSpec,
    ) -> None:
        self.root = root
        self.spec = spec
        self.manifest = LearningCleanEvidenceManifest.from_spec(spec)
        self.predictions_root = root / "predictions"
        self.outcomes_root = root / "outcomes"
        self.predictions_root.mkdir(parents=True, exist_ok=True)
        self.outcomes_root.mkdir(parents=True, exist_ok=True)
        _write_consistent(
            root / "manifest.json",
            (_canonical_json(self.manifest.to_dict()) + "\n").encode("utf-8"),
        )
        self._verify_manifest()

    def _verify_manifest(self) -> None:
        path = self.root / "manifest.json"
        try:
            payload = path.read_bytes()
            raw = _mapping(json.loads(payload), "learning clean evidence manifest")
        except (OSError, json.JSONDecodeError) as exc:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_EVIDENCE_MANIFEST_INVALID"
            ) from exc
        try:
            stored = LearningCleanEvidenceManifest(
                validation_spec_id=_string(
                    raw.get("validation_spec_id"),
                    "validation_spec_id",
                ),
                candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
                candidate_package_id=_string(
                    raw.get("candidate_package_id"),
                    "candidate_package_id",
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
                sample_policy=_string(raw.get("sample_policy"), "sample_policy"),
                metric=_string(raw.get("metric"), "metric"),
                schema_version=_integer(raw.get("schema_version"), "schema_version"),
            )
        except ValueError as exc:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_EVIDENCE_MANIFEST_INVALID"
            ) from exc
        if raw.get("manifest_id") != stored.manifest_id:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_EVIDENCE_MANIFEST_ID_MISMATCH"
            )
        if stored != self.manifest:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_EVIDENCE_MANIFEST_SPEC_MISMATCH"
            )
        if payload != (_canonical_json(stored.to_dict()) + "\n").encode("utf-8"):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_EVIDENCE_MANIFEST_NON_CANONICAL"
            )

    def _validate_prediction(self, prediction: LearningCandidatePrediction) -> None:
        if (
            prediction.validation_spec_id != self.spec.spec_id
            or prediction.candidate_id != self.spec.candidate_id
            or prediction.candidate_package_id != self.spec.candidate_package_id
            or prediction.experiment_id != self.spec.experiment_id
            or prediction.model_family != self.spec.model_family
        ):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_LINEAGE_MISMATCH"
            )
        if prediction.observed_at_ms < self.spec.validation_start_ms:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_BEFORE_VALIDATION_START"
            )
        if (
            not prediction.paper_only
            or not prediction.research_only
            or prediction.promotion_eligible
            or prediction.execution_ready
        ):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_AUTHORITY_INVALID"
            )

    def record_prediction(
        self,
        prediction: LearningCandidatePrediction,
    ) -> Path:
        self._validate_prediction(prediction)
        path = self.predictions_root / f"{prediction.prediction_id}.json"
        _write_consistent(
            path,
            (_canonical_json(prediction.to_dict()) + "\n").encode("utf-8"),
        )
        return path

    def _load_prediction_path(self, path: Path) -> LearningCandidatePrediction:
        if path.is_symlink():
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_SYMLINK_FORBIDDEN"
            )
        try:
            payload = path.read_bytes()
            raw = _mapping(json.loads(payload), "learning clean prediction")
        except (OSError, json.JSONDecodeError) as exc:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_INVALID"
            ) from exc
        prediction = _prediction_from_payload(raw)
        if path.name != f"{prediction.prediction_id}.json":
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_FILENAME_MISMATCH"
            )
        if payload != (_canonical_json(prediction.to_dict()) + "\n").encode("utf-8"):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_NON_CANONICAL"
            )
        self._validate_prediction(prediction)
        return prediction

    def iter_predictions(self) -> tuple[LearningCandidatePrediction, ...]:
        predictions = tuple(
            self._load_prediction_path(path)
            for path in sorted(self.predictions_root.glob("*.json"))
        )
        if len({item.prediction_id for item in predictions}) != len(predictions):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_PREDICTION_DUPLICATE"
            )
        return tuple(
            sorted(
                predictions,
                key=lambda item: (item.observed_at_ms, item.prediction_id),
            )
        )

    def _prediction_for_outcome(
        self,
        prediction_id: str,
    ) -> LearningCandidatePrediction:
        path = self.predictions_root / f"{prediction_id}.json"
        if not path.is_file():
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_PREDICTION_MISSING"
            )
        prediction = self._load_prediction_path(path)
        if not prediction.trade_eligible:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_FOR_NO_TRADE_PREDICTION"
            )
        return prediction

    def _validate_outcome(
        self,
        outcome: LearningCleanTradeOutcome,
        prediction: LearningCandidatePrediction,
    ) -> None:
        if (
            outcome.prediction_id != prediction.prediction_id
            or outcome.candidate_id != self.spec.candidate_id
            or outcome.validation_spec_id != self.spec.spec_id
            or outcome.candidate_package_id != self.spec.candidate_package_id
        ):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_LINEAGE_MISMATCH"
            )
        if outcome.opened_at_ms < prediction.observed_at_ms:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_PRECEDES_PREDICTION"
            )
        feature_map = dict(
            zip(
                prediction.feature_registry,
                prediction.feature_values,
                strict=True,
            )
        )
        if "market" in feature_map and feature_map["market"] != outcome.market:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_MARKET_MISMATCH"
            )
        if (
            "direction" in feature_map
            and feature_map["direction"] != outcome.direction
        ):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_DIRECTION_MISMATCH"
            )
        if (
            not outcome.paper_only
            or not outcome.research_only
            or outcome.promotion_eligible
            or outcome.execution_ready
        ):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_AUTHORITY_INVALID"
            )

    def record_outcome(
        self,
        outcome: LearningCleanTradeOutcome,
    ) -> Path:
        prediction = self._prediction_for_outcome(outcome.prediction_id)
        self._validate_outcome(outcome, prediction)
        for existing in self.iter_outcomes():
            if (
                existing.source_trade_id == outcome.source_trade_id
                and existing.prediction_id != outcome.prediction_id
            ):
                raise LearningCleanEvidenceError(
                    "LEARNING_CLEAN_SOURCE_TRADE_DUPLICATE"
                )
        path = self.outcomes_root / f"{outcome.prediction_id}.json"
        _write_consistent(
            path,
            (_canonical_json(outcome.to_dict()) + "\n").encode("utf-8"),
        )
        return path

    def _load_outcome_path(self, path: Path) -> LearningCleanTradeOutcome:
        if path.is_symlink():
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_SYMLINK_FORBIDDEN"
            )
        try:
            payload = path.read_bytes()
            raw = _mapping(json.loads(payload), "learning clean outcome")
        except (OSError, json.JSONDecodeError) as exc:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_INVALID"
            ) from exc
        outcome = _outcome_from_payload(raw)
        if path.name != f"{outcome.prediction_id}.json":
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_FILENAME_MISMATCH"
            )
        if payload != (_canonical_json(outcome.to_dict()) + "\n").encode("utf-8"):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_NON_CANONICAL"
            )
        prediction = self._prediction_for_outcome(outcome.prediction_id)
        self._validate_outcome(outcome, prediction)
        return outcome

    def iter_outcomes(self) -> tuple[LearningCleanTradeOutcome, ...]:
        outcomes = tuple(
            self._load_outcome_path(path)
            for path in sorted(self.outcomes_root.glob("*.json"))
        )
        if len({item.prediction_id for item in outcomes}) != len(outcomes):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_OUTCOME_DUPLICATE"
            )
        if len({item.source_trade_id for item in outcomes}) != len(outcomes):
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_SOURCE_TRADE_DUPLICATE"
            )
        return tuple(
            sorted(
                outcomes,
                key=lambda item: (
                    item.closed_at_ms,
                    item.opened_at_ms,
                    item.prediction_id,
                ),
            )
        )

    @property
    def unsettled_trade_prediction_ids(self) -> tuple[str, ...]:
        predictions = self.iter_predictions()
        settled = {item.prediction_id for item in self.iter_outcomes()}
        return tuple(
            item.prediction_id
            for item in predictions
            if item.trade_eligible and item.prediction_id not in settled
        )

    @property
    def state_digest(self) -> str:
        self._verify_manifest()
        predictions = self.iter_predictions()
        outcomes = self.iter_outcomes()
        return _sha256_json(
            {
                "manifest_id": self.manifest.manifest_id,
                "predictions": tuple(
                    {
                        "prediction_id": item.prediction_id,
                        "sha256": _sha256_bytes(
                            (
                                self.predictions_root
                                / f"{item.prediction_id}.json"
                            ).read_bytes()
                        ),
                    }
                    for item in predictions
                ),
                "outcomes": tuple(
                    {
                        "prediction_id": item.prediction_id,
                        "outcome_id": item.outcome_id,
                        "sha256": _sha256_bytes(
                            (
                                self.outcomes_root
                                / f"{item.prediction_id}.json"
                            ).read_bytes()
                        ),
                    }
                    for item in outcomes
                ),
            }
        )

    def verify(self) -> None:
        self._verify_manifest()
        self.iter_predictions()
        self.iter_outcomes()
        allowed = {"manifest.json"}
        allowed.update(
            f"predictions/{item.prediction_id}.json"
            for item in self.iter_predictions()
        )
        allowed.update(
            f"outcomes/{item.prediction_id}.json"
            for item in self.iter_outcomes()
        )
        actual = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        if actual != allowed:
            raise LearningCleanEvidenceError(
                "LEARNING_CLEAN_EVIDENCE_FILE_SET_INVALID"
            )
