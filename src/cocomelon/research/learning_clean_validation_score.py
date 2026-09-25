from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.research.learning_candidate_package import (
    verify_learning_candidate_package,
)
from cocomelon.research.learning_clean_evidence import (
    LearningCleanEvidenceStore,
    LearningCleanTradeOutcome,
)
from cocomelon.research.learning_clean_validation_spec import (
    LearningCleanValidationSpec,
    verify_learning_clean_validation_spec,
)

LEARNING_CLEAN_VALIDATION_SCORE_SCHEMA_VERSION = 1


class LearningCleanValidationScoreError(RuntimeError):
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


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("cannot compute mean of empty values")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCleanValidationScoreError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCleanValidationScoreError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCleanValidationScoreError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCleanValidationScoreError(f"{field} must be boolean")
    return value


def _optional_boolean(value: object, field: str) -> bool | None:
    if value is None:
        return None
    return _boolean(value, field)


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LearningCleanValidationScoreError(
            f"{field} must be a decimal string or null"
        )
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise LearningCleanValidationScoreError(
            f"{field} must be a decimal string or null"
        ) from exc
    if not resolved.is_finite():
        raise LearningCleanValidationScoreError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class LearningCleanValidationBlock:
    block_index: int
    prediction_ids: tuple[str, ...]
    outcome_ids: tuple[str, ...]
    mean_net_r: Decimal

    def __post_init__(self) -> None:
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        if not self.prediction_ids or len(self.prediction_ids) != len(self.outcome_ids):
            raise ValueError("validation block prediction/outcome ids must align")
        if len(set(self.prediction_ids)) != len(self.prediction_ids):
            raise ValueError("validation block prediction ids must be unique")
        if len(set(self.outcome_ids)) != len(self.outcome_ids):
            raise ValueError("validation block outcome ids must be unique")
        for value in (*self.prediction_ids, *self.outcome_ids):
            _require_sha256(value, "validation block identity")
        if not self.mean_net_r.is_finite():
            raise ValueError("validation block mean_net_r must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "prediction_ids": self.prediction_ids,
            "outcome_ids": self.outcome_ids,
            "trade_count": len(self.outcome_ids),
            "mean_net_r": str(self.mean_net_r),
        }


@dataclass(frozen=True, slots=True)
class LearningCleanValidationScore:
    candidate_id: str
    validation_spec_id: str
    candidate_package_id: str
    as_of_ms: int
    evidence_sample_digest: str
    eligible_settled_trade_count: int
    target_settled_trades: int
    selected_prediction_ids: tuple[str, ...]
    selected_outcome_ids: tuple[str, ...]
    selected_source_trade_ids: tuple[str, ...]
    status: str
    overall_mean_net_r: Decimal | None
    blocks: tuple[LearningCleanValidationBlock, ...]
    qualifies_clean_validation: bool | None
    paper_only: bool = True
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CLEAN_VALIDATION_SCORE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "validation_spec_id",
            "candidate_package_id",
            "evidence_sample_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.eligible_settled_trade_count < 0:
            raise ValueError("eligible_settled_trade_count must be non-negative")
        if self.target_settled_trades <= 0:
            raise ValueError("target_settled_trades must be positive")

        selected_count = len(self.selected_outcome_ids)
        if (
            len(self.selected_prediction_ids) != selected_count
            or len(self.selected_source_trade_ids) != selected_count
        ):
            raise ValueError("selected clean validation identities must align")
        if selected_count > self.target_settled_trades:
            raise ValueError("selected clean validation sample exceeds target")
        if len(set(self.selected_prediction_ids)) != selected_count:
            raise ValueError("selected prediction ids must be unique")
        if len(set(self.selected_outcome_ids)) != selected_count:
            raise ValueError("selected outcome ids must be unique")
        if len(set(self.selected_source_trade_ids)) != selected_count:
            raise ValueError("selected source trade ids must be unique")
        for value in (*self.selected_prediction_ids, *self.selected_outcome_ids):
            _require_sha256(value, "selected clean validation identity")
        if any(not value.strip() for value in self.selected_source_trade_ids):
            raise ValueError("selected source trade ids must not be empty")
        if self.status not in {"collecting", "complete"}:
            raise ValueError("unsupported clean validation score status")

        if self.status == "collecting":
            if self.eligible_settled_trade_count >= self.target_settled_trades:
                raise ValueError("collecting score must remain below target")
            if selected_count != self.eligible_settled_trade_count:
                raise ValueError("collecting score must expose every settled identity")
            if self.overall_mean_net_r is not None or self.blocks:
                raise ValueError("collecting score must remain economically blind")
            if self.qualifies_clean_validation is not None:
                raise ValueError("collecting score cannot qualify candidate")
        else:
            if self.eligible_settled_trade_count < self.target_settled_trades:
                raise ValueError("complete score requires frozen trade capacity")
            if selected_count != self.target_settled_trades:
                raise ValueError("complete score must freeze exactly target trades")
            if self.overall_mean_net_r is None or not self.overall_mean_net_r.is_finite():
                raise ValueError("complete score requires finite overall mean")
            if self.qualifies_clean_validation is None:
                raise ValueError("complete score requires qualification decision")
            if not self.blocks:
                raise ValueError("complete score requires stability blocks")
            flattened_predictions = tuple(
                value for block in self.blocks for value in block.prediction_ids
            )
            flattened_outcomes = tuple(
                value for block in self.blocks for value in block.outcome_ids
            )
            if flattened_predictions != self.selected_prediction_ids:
                raise ValueError("validation blocks must preserve selected prediction order")
            if flattened_outcomes != self.selected_outcome_ids:
                raise ValueError("validation blocks must preserve selected outcome order")

        if not self.paper_only or not self.prospective_only or not self.research_only:
            raise ValueError("clean validation score must remain prospective paper research")
        if self.promotion_eligible:
            raise ValueError("clean validation score cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("clean validation score cannot authorize execution")
        if self.schema_version != LEARNING_CLEAN_VALIDATION_SCORE_SCHEMA_VERSION:
            raise ValueError("unsupported clean validation score schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "candidate_package_id": self.candidate_package_id,
            "as_of_ms": self.as_of_ms,
            "evidence_sample_digest": self.evidence_sample_digest,
            "eligible_settled_trade_count": self.eligible_settled_trade_count,
            "target_settled_trades": self.target_settled_trades,
            "selected_prediction_ids": self.selected_prediction_ids,
            "selected_outcome_ids": self.selected_outcome_ids,
            "selected_source_trade_ids": self.selected_source_trade_ids,
            "status": self.status,
            "overall_mean_net_r": (
                None if self.overall_mean_net_r is None else str(self.overall_mean_net_r)
            ),
            "blocks": tuple(block.to_dict() for block in self.blocks),
            "qualifies_clean_validation": self.qualifies_clean_validation,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def score_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "score_id": self.score_id}


def _eligible_outcomes(
    store: LearningCleanEvidenceStore,
    *,
    as_of_ms: int,
) -> tuple[LearningCleanTradeOutcome, ...]:
    return tuple(
        outcome
        for outcome in store.iter_outcomes()
        if outcome.closed_at_ms <= as_of_ms
    )


def _sample_digest(
    *,
    store: LearningCleanEvidenceStore,
    outcomes: tuple[LearningCleanTradeOutcome, ...],
) -> str:
    prediction_by_id = {
        prediction.prediction_id: prediction
        for prediction in store.iter_predictions()
    }
    return _sha256_json(
        {
            "manifest_id": store.manifest.manifest_id,
            "sample": tuple(
                {
                    "prediction": prediction_by_id[outcome.prediction_id].to_dict(),
                    "outcome": outcome.to_dict(),
                }
                for outcome in outcomes
            ),
        }
    )


def score_learning_clean_validation(
    *,
    evidence_root: Path,
    package_root: Path,
    validation_spec_path: Path,
    as_of_ms: int,
) -> LearningCleanValidationScore:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    package = verify_learning_candidate_package(package_root)
    spec = verify_learning_clean_validation_spec(
        validation_spec_path,
        package_root=package_root,
    )
    if spec.candidate_id != package.candidate_id:
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_CANDIDATE_MISMATCH"
        )
    if spec.candidate_package_id != package.package_id:
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_PACKAGE_MISMATCH"
        )
    if as_of_ms < spec.validation_start_ms:
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_BEFORE_START"
        )

    store = LearningCleanEvidenceStore(evidence_root, spec=spec)
    store.verify()
    eligible = _eligible_outcomes(store, as_of_ms=as_of_ms)
    selected = eligible[: spec.target_settled_trades]
    prediction_ids = tuple(item.prediction_id for item in selected)
    outcome_ids = tuple(item.outcome_id for item in selected)
    trade_ids = tuple(item.source_trade_id for item in selected)
    sample_digest = _sample_digest(store=store, outcomes=selected)

    if len(selected) < spec.target_settled_trades:
        return LearningCleanValidationScore(
            candidate_id=spec.candidate_id,
            validation_spec_id=spec.spec_id,
            candidate_package_id=spec.candidate_package_id,
            as_of_ms=as_of_ms,
            evidence_sample_digest=sample_digest,
            eligible_settled_trade_count=len(eligible),
            target_settled_trades=spec.target_settled_trades,
            selected_prediction_ids=prediction_ids,
            selected_outcome_ids=outcome_ids,
            selected_source_trade_ids=trade_ids,
            status="collecting",
            overall_mean_net_r=None,
            blocks=(),
            qualifies_clean_validation=None,
        )

    values = tuple(item.net_r for item in selected)
    overall = _mean(values)
    blocks: list[LearningCleanValidationBlock] = []
    for block_index in range(spec.stability_blocks):
        start = block_index * spec.trades_per_block
        end = start + spec.trades_per_block
        block_outcomes = selected[start:end]
        blocks.append(
            LearningCleanValidationBlock(
                block_index=block_index + 1,
                prediction_ids=tuple(
                    item.prediction_id for item in block_outcomes
                ),
                outcome_ids=tuple(item.outcome_id for item in block_outcomes),
                mean_net_r=_mean(tuple(item.net_r for item in block_outcomes)),
            )
        )

    qualifies = (
        overall > spec.min_overall_mean_net_r
        and all(
            block.mean_net_r > spec.min_block_mean_net_r
            for block in blocks
        )
    )
    return LearningCleanValidationScore(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        candidate_package_id=spec.candidate_package_id,
        as_of_ms=as_of_ms,
        evidence_sample_digest=sample_digest,
        eligible_settled_trade_count=len(eligible),
        target_settled_trades=spec.target_settled_trades,
        selected_prediction_ids=prediction_ids,
        selected_outcome_ids=outcome_ids,
        selected_source_trade_ids=trade_ids,
        status="complete",
        overall_mean_net_r=overall,
        blocks=tuple(blocks),
        qualifies_clean_validation=qualifies,
    )


def _score_from_payload(raw: dict[str, object]) -> LearningCleanValidationScore:
    prediction_ids_raw = raw.get("selected_prediction_ids")
    outcome_ids_raw = raw.get("selected_outcome_ids")
    trade_ids_raw = raw.get("selected_source_trade_ids")
    if not isinstance(prediction_ids_raw, list) or not all(
        isinstance(item, str) for item in prediction_ids_raw
    ):
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_PREDICTION_IDS_INVALID"
        )
    if not isinstance(outcome_ids_raw, list) or not all(
        isinstance(item, str) for item in outcome_ids_raw
    ):
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_OUTCOME_IDS_INVALID"
        )
    if not isinstance(trade_ids_raw, list) or not all(
        isinstance(item, str) for item in trade_ids_raw
    ):
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_TRADE_IDS_INVALID"
        )

    raw_blocks = raw.get("blocks")
    if not isinstance(raw_blocks, list):
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_BLOCKS_INVALID"
        )
    blocks: list[LearningCleanValidationBlock] = []
    for index, raw_block in enumerate(raw_blocks):
        block = _mapping(raw_block, f"blocks[{index}]")
        block_prediction_ids = block.get("prediction_ids")
        block_outcome_ids = block.get("outcome_ids")
        if not isinstance(block_prediction_ids, list) or not all(
            isinstance(item, str) for item in block_prediction_ids
        ):
            raise LearningCleanValidationScoreError(
                "LEARNING_CLEAN_VALIDATION_SCORE_BLOCKS_INVALID"
            )
        if not isinstance(block_outcome_ids, list) or not all(
            isinstance(item, str) for item in block_outcome_ids
        ):
            raise LearningCleanValidationScoreError(
                "LEARNING_CLEAN_VALIDATION_SCORE_BLOCKS_INVALID"
            )
        trade_count = _integer(block.get("trade_count"), "block trade_count")
        if (
            trade_count != len(block_prediction_ids)
            or trade_count != len(block_outcome_ids)
        ):
            raise LearningCleanValidationScoreError(
                "LEARNING_CLEAN_VALIDATION_SCORE_BLOCK_COUNT_MISMATCH"
            )
        mean = _optional_decimal(block.get("mean_net_r"), "block mean_net_r")
        if mean is None:
            raise LearningCleanValidationScoreError(
                "LEARNING_CLEAN_VALIDATION_SCORE_BLOCK_MEAN_REQUIRED"
            )
        blocks.append(
            LearningCleanValidationBlock(
                block_index=_integer(block.get("block_index"), "block_index"),
                prediction_ids=tuple(block_prediction_ids),
                outcome_ids=tuple(block_outcome_ids),
                mean_net_r=mean,
            )
        )

    try:
        score = LearningCleanValidationScore(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            candidate_package_id=_string(
                raw.get("candidate_package_id"),
                "candidate_package_id",
            ),
            as_of_ms=_integer(raw.get("as_of_ms"), "as_of_ms"),
            evidence_sample_digest=_string(
                raw.get("evidence_sample_digest"),
                "evidence_sample_digest",
            ),
            eligible_settled_trade_count=_integer(
                raw.get("eligible_settled_trade_count"),
                "eligible_settled_trade_count",
            ),
            target_settled_trades=_integer(
                raw.get("target_settled_trades"),
                "target_settled_trades",
            ),
            selected_prediction_ids=tuple(prediction_ids_raw),
            selected_outcome_ids=tuple(outcome_ids_raw),
            selected_source_trade_ids=tuple(trade_ids_raw),
            status=_string(raw.get("status"), "status"),
            overall_mean_net_r=_optional_decimal(
                raw.get("overall_mean_net_r"),
                "overall_mean_net_r",
            ),
            blocks=tuple(blocks),
            qualifies_clean_validation=_optional_boolean(
                raw.get("qualifies_clean_validation"),
                "qualifies_clean_validation",
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
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_INVALID"
        ) from exc
    if raw.get("score_id") != score.score_id:
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_ID_MISMATCH"
        )
    return score


def load_learning_clean_validation_score(
    path: Path,
) -> LearningCleanValidationScore:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(
            json.loads(stored_bytes),
            "learning clean validation score",
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_INVALID"
        ) from exc
    score = _score_from_payload(raw)
    canonical = (_canonical_json(score.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_NON_CANONICAL"
        )
    return score


def verify_learning_clean_validation_score(
    path: Path,
    *,
    evidence_root: Path,
    package_root: Path,
    validation_spec_path: Path,
) -> LearningCleanValidationScore:
    stored = load_learning_clean_validation_score(path)
    expected = score_learning_clean_validation(
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        as_of_ms=stored.as_of_ms,
    )
    if stored != expected:
        raise LearningCleanValidationScoreError(
            "LEARNING_CLEAN_VALIDATION_SCORE_EVIDENCE_MISMATCH"
        )
    return stored


def write_learning_clean_validation_score(
    output_root: Path,
    score: LearningCleanValidationScore,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "candidate-validation-score.json"
    payload = (_canonical_json(score.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCleanValidationScoreError(
                "LEARNING_CLEAN_VALIDATION_SCORE_CONFLICT"
            )
        return path
    temporary = output_root / ".candidate-validation-score.json.tmp"
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
