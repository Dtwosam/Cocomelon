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
from cocomelon.research.learning_clean_validation_spec import (
    LearningCleanValidationSpec,
    verify_learning_clean_validation_spec,
)
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
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


@dataclass(frozen=True, slots=True)
class LearningCleanValidationBlock:
    block_index: int
    record_ids: tuple[str, ...]
    mean_net_r: Decimal

    def __post_init__(self) -> None:
        if self.block_index <= 0:
            raise ValueError("block_index must be positive")
        if not self.record_ids:
            raise ValueError("clean validation block must not be empty")
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError("clean validation block record ids must be unique")
        for record_id in self.record_ids:
            _require_sha256(record_id, "record_id")
        if not self.mean_net_r.is_finite():
            raise ValueError("block mean_net_r must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "block_index": self.block_index,
            "record_ids": self.record_ids,
            "trade_count": len(self.record_ids),
            "mean_net_r": str(self.mean_net_r),
        }


@dataclass(frozen=True, slots=True)
class LearningCleanValidationScore:
    candidate_id: str
    validation_spec_id: str
    candidate_package_id: str
    as_of_ms: int
    ledger_state_digest: str
    eligible_settled_trade_count: int
    target_settled_trades: int
    selected_record_ids: tuple[str, ...]
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
            "ledger_state_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.eligible_settled_trade_count < 0:
            raise ValueError("eligible_settled_trade_count must be non-negative")
        if self.target_settled_trades <= 0:
            raise ValueError("target_settled_trades must be positive")
        if len(self.selected_record_ids) > self.target_settled_trades:
            raise ValueError("selected records cannot exceed frozen target")
        if len(set(self.selected_record_ids)) != len(self.selected_record_ids):
            raise ValueError("selected record ids must be unique")
        for record_id in self.selected_record_ids:
            _require_sha256(record_id, "selected_record_id")
        if self.status not in {"collecting", "complete"}:
            raise ValueError("unsupported clean validation score status")

        if self.status == "collecting":
            if self.eligible_settled_trade_count >= self.target_settled_trades:
                raise ValueError("collecting score must remain below target")
            if len(self.selected_record_ids) != self.eligible_settled_trade_count:
                raise ValueError("collecting score must expose all eligible record ids")
            if self.overall_mean_net_r is not None or self.blocks:
                raise ValueError("collecting score must remain economically blind")
            if self.qualifies_clean_validation is not None:
                raise ValueError("collecting score cannot qualify candidate")
        else:
            if self.eligible_settled_trade_count < self.target_settled_trades:
                raise ValueError("complete score requires target trade capacity")
            if len(self.selected_record_ids) != self.target_settled_trades:
                raise ValueError("complete score must freeze exactly target trades")
            if self.overall_mean_net_r is None or not self.overall_mean_net_r.is_finite():
                raise ValueError("complete score requires finite overall mean")
            if not self.blocks:
                raise ValueError("complete score requires stability blocks")
            if self.qualifies_clean_validation is None:
                raise ValueError("complete score requires qualification decision")

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
            "ledger_state_digest": self.ledger_state_digest,
            "eligible_settled_trade_count": self.eligible_settled_trade_count,
            "target_settled_trades": self.target_settled_trades,
            "selected_record_ids": self.selected_record_ids,
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


def _eligible_records(
    records: tuple[LearningEvidenceRecord, ...],
    *,
    spec: LearningCleanValidationSpec,
    as_of_ms: int,
) -> tuple[LearningEvidenceRecord, ...]:
    eligible: list[LearningEvidenceRecord] = []
    for record in records:
        if record.kind is not LearningEvidenceKind.PAPER_EXECUTION:
            continue
        if record.candidate_id != spec.candidate_id:
            continue
        if record.candidate_spec_id != spec.spec_id:
            continue
        if record.opened_at_ms < spec.validation_start_ms:
            continue
        if record.research_eligible_at_ms > as_of_ms:
            continue
        if record.net_r is None:
            raise LearningCleanValidationScoreError(
                "LEARNING_CLEAN_VALIDATION_NET_R_MISSING"
            )
        eligible.append(record)
    return tuple(
        sorted(
            eligible,
            key=lambda item: (
                item.closed_at_ms,
                item.opened_at_ms,
                item.market.canonical,
                item.record_id,
            ),
        )
    )


def score_learning_clean_validation(
    *,
    ledger_root: Path,
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

    ledger = LearningEvidenceLedger(ledger_root)
    records = ledger.iter_records()
    eligible = _eligible_records(records, spec=spec, as_of_ms=as_of_ms)
    selected = eligible[: spec.target_settled_trades]
    selected_ids = tuple(record.record_id for record in selected)

    if len(selected) < spec.target_settled_trades:
        return LearningCleanValidationScore(
            candidate_id=spec.candidate_id,
            validation_spec_id=spec.spec_id,
            candidate_package_id=spec.candidate_package_id,
            as_of_ms=as_of_ms,
            ledger_state_digest=ledger.state_digest,
            eligible_settled_trade_count=len(eligible),
            target_settled_trades=spec.target_settled_trades,
            selected_record_ids=selected_ids,
            status="collecting",
            overall_mean_net_r=None,
            blocks=(),
            qualifies_clean_validation=None,
        )

    values = tuple(cast(Decimal, record.net_r) for record in selected)
    overall = _mean(values)
    blocks: list[LearningCleanValidationBlock] = []
    for block_index in range(spec.stability_blocks):
        start = block_index * spec.trades_per_block
        end = start + spec.trades_per_block
        block_records = selected[start:end]
        block_values = tuple(cast(Decimal, record.net_r) for record in block_records)
        blocks.append(
            LearningCleanValidationBlock(
                block_index=block_index + 1,
                record_ids=tuple(record.record_id for record in block_records),
                mean_net_r=_mean(block_values),
            )
        )

    qualifies = (
        overall > spec.min_overall_mean_net_r
        and all(block.mean_net_r > spec.min_block_mean_net_r for block in blocks)
    )
    return LearningCleanValidationScore(
        candidate_id=spec.candidate_id,
        validation_spec_id=spec.spec_id,
        candidate_package_id=spec.candidate_package_id,
        as_of_ms=as_of_ms,
        ledger_state_digest=ledger.state_digest,
        eligible_settled_trade_count=len(eligible),
        target_settled_trades=spec.target_settled_trades,
        selected_record_ids=selected_ids,
        status="complete",
        overall_mean_net_r=overall,
        blocks=tuple(blocks),
        qualifies_clean_validation=qualifies,
    )


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
