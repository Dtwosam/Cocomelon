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
from cocomelon.research.learning_clean_evidence import LearningCleanEvidenceStore
from cocomelon.research.learning_clean_finalization import (
    VERDICT_ELIGIBLE,
    verify_learning_clean_finalization,
)
from cocomelon.research.learning_clean_validation_score import (
    verify_learning_clean_validation_score,
)
from cocomelon.research.learning_clean_validation_spec import (
    verify_learning_clean_validation_spec,
)

LEARNING_CLEAN_REVIEW_DOSSIER_SCHEMA_VERSION = 1
PROMOTION_GATE_STATUS = "not_asserted_by_review_dossier"
PROMOTION_REQUIREMENTS = (
    ("closed_mainnet_paper_trades", "at least 500 closed mainnet paper trades under the candidate champion"),
    ("shadow_calendar_days", "at least 45 calendar days of live mainnet shadow operation"),
    ("positive_net_expectancy_after_costs", "positive net expectancy after modeled fees, funding, and slippage"),
    ("positive_untouched_oos", "positive untouched out-of-sample results"),
    ("walk_forward_stability", "stable walk-forward performance rather than one lucky window"),
    ("profit_factor", "profit factor of at least 1.20 overall"),
    ("maximum_paper_drawdown", "maximum paper drawdown no worse than 8% under the locked risk model"),
    ("market_concentration", "no single market contributes more than 35% of total positive net PnL"),
    ("seven_day_concentration", "no single seven-day period contributes more than 50% of total positive net PnL"),
    ("risk_invariants", "zero unresolved risk-invariant violations"),
    ("recovery_reconciliation", "successful restart, recovery, and reconciliation tests"),
    ("explicit_live_authorization", "explicit user live-promotion authorization and capital amount"),
)


class LearningCleanReviewDossierError(RuntimeError):
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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningCleanReviewDossierError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningCleanReviewDossierError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningCleanReviewDossierError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningCleanReviewDossierError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningCleanReviewDossierError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except Exception as exc:
        raise LearningCleanReviewDossierError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise LearningCleanReviewDossierError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class LearningCleanReviewOutcome:
    outcome_id: str
    prediction_id: str
    source_trade_id: str
    market: str
    direction: str
    opened_at_ms: int
    closed_at_ms: int
    net_r: Decimal

    def __post_init__(self) -> None:
        _require_sha256(self.outcome_id, "outcome_id")
        _require_sha256(self.prediction_id, "prediction_id")
        if not self.source_trade_id.strip() or not self.market.strip():
            raise ValueError("review outcome source trade and market must not be empty")
        if self.direction not in {"long", "short"}:
            raise ValueError("review outcome direction must be long or short")
        if self.opened_at_ms < 0 or self.closed_at_ms < self.opened_at_ms:
            raise ValueError("review outcome timestamps are invalid")
        if not self.net_r.is_finite():
            raise ValueError("review outcome net_r must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome_id": self.outcome_id,
            "prediction_id": self.prediction_id,
            "source_trade_id": self.source_trade_id,
            "market": self.market,
            "direction": self.direction,
            "opened_at_ms": self.opened_at_ms,
            "closed_at_ms": self.closed_at_ms,
            "net_r": str(self.net_r),
        }


@dataclass(frozen=True, slots=True)
class PromotionGateNotice:
    gate: str
    requirement: str
    status: str = PROMOTION_GATE_STATUS

    def __post_init__(self) -> None:
        if not self.gate.strip() or not self.requirement.strip():
            raise ValueError("promotion gate notice fields must not be empty")
        if self.status != PROMOTION_GATE_STATUS:
            raise ValueError("review dossier cannot assert a live-promotion gate")

    def to_dict(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "requirement": self.requirement,
            "status": self.status,
        }


def _promotion_gate_notices() -> tuple[PromotionGateNotice, ...]:
    return tuple(
        PromotionGateNotice(gate=gate, requirement=requirement)
        for gate, requirement in PROMOTION_REQUIREMENTS
    )


@dataclass(frozen=True, slots=True)
class LearningCleanReviewDossier:
    candidate_id: str
    candidate_package_id: str
    validation_spec_id: str
    validation_score_id: str
    finalization_id: str
    model_family: str
    validation_start_ms: int
    validation_score_as_of_ms: int
    finalized_at_ms: int
    selected_evidence_digest: str
    settled_trade_count: int
    overall_mean_net_r: Decimal
    block_mean_net_r: tuple[Decimal, ...]
    outcomes: tuple[LearningCleanReviewOutcome, ...]
    promotion_gates: tuple[PromotionGateNotice, ...]
    verdict: str = VERDICT_ELIGIBLE
    human_review_required: bool = True
    paper_only: bool = True
    prospective_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_CLEAN_REVIEW_DOSSIER_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_package_id",
            "validation_spec_id",
            "validation_score_id",
            "finalization_id",
            "selected_evidence_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.model_family.strip():
            raise ValueError("model_family must not be empty")
        if (
            self.validation_start_ms < 0
            or self.validation_score_as_of_ms < self.validation_start_ms
            or self.finalized_at_ms < self.validation_score_as_of_ms
        ):
            raise ValueError("review dossier timestamps are invalid")
        if self.settled_trade_count <= 0:
            raise ValueError("review dossier settled trade count must be positive")
        if len(self.outcomes) != self.settled_trade_count:
            raise ValueError("review dossier outcome count must match settled trades")
        if len({item.outcome_id for item in self.outcomes}) != len(self.outcomes):
            raise ValueError("review dossier outcomes must be unique")
        if not self.overall_mean_net_r.is_finite():
            raise ValueError("review dossier overall mean must be finite")
        if not self.block_mean_net_r or any(
            not item.is_finite() for item in self.block_mean_net_r
        ):
            raise ValueError("review dossier block means must be finite")
        if self.promotion_gates != _promotion_gate_notices():
            raise ValueError("review dossier must preserve every live-promotion gate notice")
        if self.verdict != VERDICT_ELIGIBLE:
            raise ValueError("review dossier requires review-eligible finalization")
        if not self.human_review_required:
            raise ValueError("review dossier must preserve human review boundary")
        if not self.paper_only or not self.prospective_only or not self.research_only:
            raise ValueError("review dossier must remain prospective paper research")
        if self.promotion_eligible:
            raise ValueError("review dossier cannot authorize promotion")
        if self.execution_ready:
            raise ValueError("review dossier cannot authorize execution")
        if self.schema_version != LEARNING_CLEAN_REVIEW_DOSSIER_SCHEMA_VERSION:
            raise ValueError("unsupported learning clean review dossier schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "validation_spec_id": self.validation_spec_id,
            "validation_score_id": self.validation_score_id,
            "finalization_id": self.finalization_id,
            "model_family": self.model_family,
            "validation_start_ms": self.validation_start_ms,
            "validation_score_as_of_ms": self.validation_score_as_of_ms,
            "finalized_at_ms": self.finalized_at_ms,
            "selected_evidence_digest": self.selected_evidence_digest,
            "settled_trade_count": self.settled_trade_count,
            "overall_mean_net_r": str(self.overall_mean_net_r),
            "block_mean_net_r": tuple(str(item) for item in self.block_mean_net_r),
            "outcomes": tuple(item.to_dict() for item in self.outcomes),
            "promotion_gates": tuple(item.to_dict() for item in self.promotion_gates),
            "verdict": self.verdict,
            "human_review_required": self.human_review_required,
            "paper_only": self.paper_only,
            "prospective_only": self.prospective_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def dossier_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "dossier_id": self.dossier_id}


def build_learning_clean_review_dossier(
    *,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    evidence_root: Path,
) -> LearningCleanReviewDossier:
    package = verify_learning_candidate_package(package_root)
    spec = verify_learning_clean_validation_spec(
        validation_spec_path,
        package_root=package_root,
    )
    score = verify_learning_clean_validation_score(
        validation_score_path,
        evidence_root=evidence_root,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
    )
    finalization = verify_learning_clean_finalization(
        finalization_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        evidence_root=evidence_root,
    )
    if (
        not finalization.eligible_for_candidate_review
        or finalization.verdict != VERDICT_ELIGIBLE
    ):
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_NOT_REVIEW_ELIGIBLE"
        )
    if score.status != "complete" or score.qualifies_clean_validation is not True:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_SCORE_NOT_QUALIFIED"
        )
    if (
        package.candidate_id != spec.candidate_id
        or package.candidate_id != score.candidate_id
        or package.candidate_id != finalization.candidate_id
        or package.package_id != spec.candidate_package_id
        or package.package_id != score.candidate_package_id
        or spec.spec_id != score.validation_spec_id
        or score.score_id != finalization.validation_score_id
    ):
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_LINEAGE_MISMATCH"
        )

    evidence = LearningCleanEvidenceStore(evidence_root, spec=spec)
    evidence.verify()
    by_id = {item.outcome_id: item for item in evidence.iter_outcomes()}
    selected = []
    for outcome_id in score.selected_outcome_ids:
        outcome = by_id.get(outcome_id)
        if outcome is None:
            raise LearningCleanReviewDossierError(
                "LEARNING_CLEAN_REVIEW_DOSSIER_OUTCOME_MISSING"
            )
        selected.append(
            LearningCleanReviewOutcome(
                outcome_id=outcome.outcome_id,
                prediction_id=outcome.prediction_id,
                source_trade_id=outcome.source_trade_id,
                market=outcome.market,
                direction=outcome.direction,
                opened_at_ms=outcome.opened_at_ms,
                closed_at_ms=outcome.closed_at_ms,
                net_r=outcome.net_r,
            )
        )

    if score.overall_mean_net_r is None:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_SCORE_MEAN_MISSING"
        )
    return LearningCleanReviewDossier(
        candidate_id=package.candidate_id,
        candidate_package_id=package.package_id,
        validation_spec_id=spec.spec_id,
        validation_score_id=score.score_id,
        finalization_id=finalization.finalization_id,
        model_family=spec.model_family,
        validation_start_ms=spec.validation_start_ms,
        validation_score_as_of_ms=score.as_of_ms,
        finalized_at_ms=finalization.finalized_at_ms,
        selected_evidence_digest=score.selected_evidence_digest,
        settled_trade_count=score.selected_settled_trade_count,
        overall_mean_net_r=score.overall_mean_net_r,
        block_mean_net_r=tuple(block.mean_net_r for block in score.blocks),
        outcomes=tuple(selected),
        promotion_gates=_promotion_gate_notices(),
    )


def write_learning_clean_review_dossier(
    output_root: Path,
    dossier: LearningCleanReviewDossier,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "candidate-review-dossier.json"
    payload = (_canonical_json(dossier.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningCleanReviewDossierError(
                "LEARNING_CLEAN_REVIEW_DOSSIER_CONFLICT"
            )
        return path
    temporary = output_root / ".candidate-review-dossier.json.tmp"
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


def _outcome_from_payload(raw: dict[str, object]) -> LearningCleanReviewOutcome:
    try:
        return LearningCleanReviewOutcome(
            outcome_id=_string(raw.get("outcome_id"), "outcome_id"),
            prediction_id=_string(raw.get("prediction_id"), "prediction_id"),
            source_trade_id=_string(raw.get("source_trade_id"), "source_trade_id"),
            market=_string(raw.get("market"), "market"),
            direction=_string(raw.get("direction"), "direction"),
            opened_at_ms=_integer(raw.get("opened_at_ms"), "opened_at_ms"),
            closed_at_ms=_integer(raw.get("closed_at_ms"), "closed_at_ms"),
            net_r=_decimal(raw.get("net_r"), "net_r"),
        )
    except ValueError as exc:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_OUTCOME_INVALID"
        ) from exc


def _gate_from_payload(raw: dict[str, object]) -> PromotionGateNotice:
    try:
        return PromotionGateNotice(
            gate=_string(raw.get("gate"), "gate"),
            requirement=_string(raw.get("requirement"), "requirement"),
            status=_string(raw.get("status"), "status"),
        )
    except ValueError as exc:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_GATE_INVALID"
        ) from exc


def load_learning_clean_review_dossier(path: Path) -> LearningCleanReviewDossier:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(json.loads(stored_bytes), "learning clean review dossier")
        raw_outcomes = raw.get("outcomes")
        raw_gates = raw.get("promotion_gates")
        raw_blocks = raw.get("block_mean_net_r")
        if not isinstance(raw_outcomes, list) or not isinstance(raw_gates, list):
            raise LearningCleanReviewDossierError(
                "LEARNING_CLEAN_REVIEW_DOSSIER_INVALID"
            )
        if not isinstance(raw_blocks, list):
            raise LearningCleanReviewDossierError(
                "LEARNING_CLEAN_REVIEW_DOSSIER_INVALID"
            )
        outcomes = tuple(
            _outcome_from_payload(_mapping(item, "review outcome"))
            for item in raw_outcomes
        )
        gates = tuple(
            _gate_from_payload(_mapping(item, "promotion gate"))
            for item in raw_gates
        )
        blocks = tuple(_decimal(item, "block_mean_net_r") for item in raw_blocks)
        dossier = LearningCleanReviewDossier(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_package_id=_string(
                raw.get("candidate_package_id"), "candidate_package_id"
            ),
            validation_spec_id=_string(
                raw.get("validation_spec_id"), "validation_spec_id"
            ),
            validation_score_id=_string(
                raw.get("validation_score_id"), "validation_score_id"
            ),
            finalization_id=_string(raw.get("finalization_id"), "finalization_id"),
            model_family=_string(raw.get("model_family"), "model_family"),
            validation_start_ms=_integer(
                raw.get("validation_start_ms"), "validation_start_ms"
            ),
            validation_score_as_of_ms=_integer(
                raw.get("validation_score_as_of_ms"),
                "validation_score_as_of_ms",
            ),
            finalized_at_ms=_integer(raw.get("finalized_at_ms"), "finalized_at_ms"),
            selected_evidence_digest=_string(
                raw.get("selected_evidence_digest"), "selected_evidence_digest"
            ),
            settled_trade_count=_integer(
                raw.get("settled_trade_count"), "settled_trade_count"
            ),
            overall_mean_net_r=_decimal(
                raw.get("overall_mean_net_r"), "overall_mean_net_r"
            ),
            block_mean_net_r=blocks,
            outcomes=outcomes,
            promotion_gates=gates,
            verdict=_string(raw.get("verdict"), "verdict"),
            human_review_required=_boolean(
                raw.get("human_review_required"), "human_review_required"
            ),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            prospective_only=_boolean(
                raw.get("prospective_only"), "prospective_only"
            ),
            research_only=_boolean(raw.get("research_only"), "research_only"),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"), "promotion_eligible"
            ),
            execution_ready=_boolean(raw.get("execution_ready"), "execution_ready"),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_INVALID"
        ) from exc
    except ValueError as exc:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_INVALID"
        ) from exc
    if raw.get("dossier_id") != dossier.dossier_id:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_ID_MISMATCH"
        )
    canonical = (_canonical_json(dossier.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_NON_CANONICAL"
        )
    return dossier


def verify_learning_clean_review_dossier(
    path: Path,
    *,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    evidence_root: Path,
) -> LearningCleanReviewDossier:
    stored = load_learning_clean_review_dossier(path)
    expected = build_learning_clean_review_dossier(
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )
    if stored != expected:
        raise LearningCleanReviewDossierError(
            "LEARNING_CLEAN_REVIEW_DOSSIER_EVIDENCE_MISMATCH"
        )
    return stored
