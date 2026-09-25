from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from cocomelon.research.learning_clean_review_decision import (
    DECISION_ADVANCE,
    verify_learning_clean_review_decision,
)
from cocomelon.research.learning_clean_review_dossier import PROMOTION_REQUIREMENTS

LEARNING_SHADOW_ADMISSION_SCHEMA_VERSION = 1
LEARNING_SHADOW_POLICY = "learned-candidate-shadow-evaluation-v1"

MIN_CLOSED_MAINNET_PAPER_TRADES = 500
MIN_SHADOW_CALENDAR_DAYS = 45
MIN_PROFIT_FACTOR = Decimal("1.20")
MAX_PAPER_DRAWDOWN_FRACTION = Decimal("0.08")
MAX_MARKET_POSITIVE_PNL_FRACTION = Decimal("0.35")
MAX_SEVEN_DAY_POSITIVE_PNL_FRACTION = Decimal("0.50")


class LearningShadowAdmissionError(RuntimeError):
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
        raise LearningShadowAdmissionError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningShadowAdmissionError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningShadowAdmissionError(f"{field} must be a non-negative integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningShadowAdmissionError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningShadowAdmissionError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except Exception as exc:
        raise LearningShadowAdmissionError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise LearningShadowAdmissionError(f"{field} must be finite")
    return resolved


@dataclass(frozen=True, slots=True)
class LearningShadowAdmission:
    candidate_id: str
    candidate_package_id: str
    validation_spec_id: str
    validation_score_id: str
    finalization_id: str
    review_dossier_id: str
    review_decision_id: str
    reviewed_at_ms: int
    shadow_start_ms: int
    minimum_closed_mainnet_paper_trades: int
    minimum_shadow_calendar_days: int
    minimum_profit_factor: Decimal
    maximum_paper_drawdown_fraction: Decimal
    maximum_market_positive_pnl_fraction: Decimal
    maximum_seven_day_positive_pnl_fraction: Decimal
    promotion_requirement_states: tuple[tuple[str, str], ...]
    policy: str = LEARNING_SHADOW_POLICY
    shadow_evaluation_authorized: bool = True
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    live_promotion_authorized: bool = False
    schema_version: int = LEARNING_SHADOW_ADMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "candidate_package_id",
            "validation_spec_id",
            "validation_score_id",
            "finalization_id",
            "review_dossier_id",
            "review_decision_id",
        ):
            _require_sha256(getattr(self, field), field)
        if self.reviewed_at_ms < 0 or self.shadow_start_ms < 0:
            raise ValueError("shadow admission timestamps must be non-negative")
        if self.shadow_start_ms < self.reviewed_at_ms:
            raise ValueError("shadow evaluation cannot backfill before human review")
        if self.minimum_closed_mainnet_paper_trades != MIN_CLOSED_MAINNET_PAPER_TRADES:
            raise ValueError("minimum paper-trade floor must remain frozen")
        if self.minimum_shadow_calendar_days != MIN_SHADOW_CALENDAR_DAYS:
            raise ValueError("minimum shadow-day floor must remain frozen")
        if self.minimum_profit_factor != MIN_PROFIT_FACTOR:
            raise ValueError("minimum profit-factor floor must remain frozen")
        if self.maximum_paper_drawdown_fraction != MAX_PAPER_DRAWDOWN_FRACTION:
            raise ValueError("paper drawdown ceiling must remain frozen")
        if self.maximum_market_positive_pnl_fraction != MAX_MARKET_POSITIVE_PNL_FRACTION:
            raise ValueError("market concentration ceiling must remain frozen")
        if (
            self.maximum_seven_day_positive_pnl_fraction
            != MAX_SEVEN_DAY_POSITIVE_PNL_FRACTION
        ):
            raise ValueError("seven-day concentration ceiling must remain frozen")
        expected_keys = tuple(key for key, _description in PROMOTION_REQUIREMENTS)
        actual_keys = tuple(key for key, _state in self.promotion_requirement_states)
        if actual_keys != expected_keys:
            raise ValueError("promotion requirement keys must match source-of-truth order")
        if any(state != "not_yet_evaluated" for _key, state in self.promotion_requirement_states):
            raise ValueError("shadow admission cannot pre-satisfy promotion requirements")
        if self.policy != LEARNING_SHADOW_POLICY:
            raise ValueError("unsupported learning shadow admission policy")
        if not self.shadow_evaluation_authorized:
            raise ValueError("shadow admission requires shadow evaluation authority")
        if not self.paper_only or not self.research_only:
            raise ValueError("shadow admission must remain paper research")
        if self.promotion_eligible:
            raise ValueError("shadow admission cannot authorize live promotion")
        if self.execution_ready:
            raise ValueError("shadow admission cannot authorize execution")
        if self.live_promotion_authorized:
            raise ValueError("shadow admission cannot authorize live capital")
        if self.schema_version != LEARNING_SHADOW_ADMISSION_SCHEMA_VERSION:
            raise ValueError("unsupported learning shadow admission schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_package_id": self.candidate_package_id,
            "validation_spec_id": self.validation_spec_id,
            "validation_score_id": self.validation_score_id,
            "finalization_id": self.finalization_id,
            "review_dossier_id": self.review_dossier_id,
            "review_decision_id": self.review_decision_id,
            "reviewed_at_ms": self.reviewed_at_ms,
            "shadow_start_ms": self.shadow_start_ms,
            "minimum_closed_mainnet_paper_trades": (
                self.minimum_closed_mainnet_paper_trades
            ),
            "minimum_shadow_calendar_days": self.minimum_shadow_calendar_days,
            "minimum_profit_factor": str(self.minimum_profit_factor),
            "maximum_paper_drawdown_fraction": str(
                self.maximum_paper_drawdown_fraction
            ),
            "maximum_market_positive_pnl_fraction": str(
                self.maximum_market_positive_pnl_fraction
            ),
            "maximum_seven_day_positive_pnl_fraction": str(
                self.maximum_seven_day_positive_pnl_fraction
            ),
            "promotion_requirement_states": tuple(
                {"requirement": key, "state": state}
                for key, state in self.promotion_requirement_states
            ),
            "policy": self.policy,
            "shadow_evaluation_authorized": self.shadow_evaluation_authorized,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "live_promotion_authorized": self.live_promotion_authorized,
            "schema_version": self.schema_version,
        }

    @property
    def shadow_admission_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "shadow_admission_id": self.shadow_admission_id}


def build_learning_shadow_admission(
    *,
    review_decision_path: Path,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    evidence_root: Path,
    shadow_start_ms: int | None = None,
) -> LearningShadowAdmission:
    decision = verify_learning_clean_review_decision(
        review_decision_path,
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
    )
    if (
        decision.decision != DECISION_ADVANCE
        or not decision.shadow_evaluation_authorized
    ):
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_REVIEW_NOT_APPROVED"
        )
    resolved_start = (
        decision.reviewed_at_ms if shadow_start_ms is None else shadow_start_ms
    )
    if resolved_start < decision.reviewed_at_ms:
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_PRE_REVIEW_START"
        )

    return LearningShadowAdmission(
        candidate_id=decision.candidate_id,
        candidate_package_id=decision.candidate_package_id,
        validation_spec_id=decision.validation_spec_id,
        validation_score_id=decision.validation_score_id,
        finalization_id=decision.finalization_id,
        review_dossier_id=decision.review_dossier_id,
        review_decision_id=decision.review_decision_id,
        reviewed_at_ms=decision.reviewed_at_ms,
        shadow_start_ms=resolved_start,
        minimum_closed_mainnet_paper_trades=MIN_CLOSED_MAINNET_PAPER_TRADES,
        minimum_shadow_calendar_days=MIN_SHADOW_CALENDAR_DAYS,
        minimum_profit_factor=MIN_PROFIT_FACTOR,
        maximum_paper_drawdown_fraction=MAX_PAPER_DRAWDOWN_FRACTION,
        maximum_market_positive_pnl_fraction=MAX_MARKET_POSITIVE_PNL_FRACTION,
        maximum_seven_day_positive_pnl_fraction=MAX_SEVEN_DAY_POSITIVE_PNL_FRACTION,
        promotion_requirement_states=tuple(
            (key, "not_yet_evaluated") for key, _description in PROMOTION_REQUIREMENTS
        ),
    )


def write_learning_shadow_admission(
    output_root: Path,
    admission: LearningShadowAdmission,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "shadow-admission.json"
    payload = (_canonical_json(admission.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningShadowAdmissionError("LEARNING_SHADOW_ADMISSION_CONFLICT")
        return path
    temporary = output_root / ".shadow-admission.json.tmp"
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


def _admission_from_payload(raw: dict[str, object]) -> LearningShadowAdmission:
    raw_states = raw.get("promotion_requirement_states")
    if not isinstance(raw_states, list):
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_REQUIREMENTS_INVALID"
        )
    states: list[tuple[str, str]] = []
    for index, item in enumerate(raw_states):
        mapped = _mapping(item, f"promotion_requirement_states[{index}]")
        if set(mapped) != {"requirement", "state"}:
            raise LearningShadowAdmissionError(
                "LEARNING_SHADOW_ADMISSION_REQUIREMENTS_INVALID"
            )
        states.append(
            (
                _string(mapped.get("requirement"), "requirement"),
                _string(mapped.get("state"), "state"),
            )
        )
    try:
        admission = LearningShadowAdmission(
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
            review_dossier_id=_string(
                raw.get("review_dossier_id"), "review_dossier_id"
            ),
            review_decision_id=_string(
                raw.get("review_decision_id"), "review_decision_id"
            ),
            reviewed_at_ms=_integer(raw.get("reviewed_at_ms"), "reviewed_at_ms"),
            shadow_start_ms=_integer(raw.get("shadow_start_ms"), "shadow_start_ms"),
            minimum_closed_mainnet_paper_trades=_integer(
                raw.get("minimum_closed_mainnet_paper_trades"),
                "minimum_closed_mainnet_paper_trades",
            ),
            minimum_shadow_calendar_days=_integer(
                raw.get("minimum_shadow_calendar_days"),
                "minimum_shadow_calendar_days",
            ),
            minimum_profit_factor=_decimal(
                raw.get("minimum_profit_factor"), "minimum_profit_factor"
            ),
            maximum_paper_drawdown_fraction=_decimal(
                raw.get("maximum_paper_drawdown_fraction"),
                "maximum_paper_drawdown_fraction",
            ),
            maximum_market_positive_pnl_fraction=_decimal(
                raw.get("maximum_market_positive_pnl_fraction"),
                "maximum_market_positive_pnl_fraction",
            ),
            maximum_seven_day_positive_pnl_fraction=_decimal(
                raw.get("maximum_seven_day_positive_pnl_fraction"),
                "maximum_seven_day_positive_pnl_fraction",
            ),
            promotion_requirement_states=tuple(states),
            policy=_string(raw.get("policy"), "policy"),
            shadow_evaluation_authorized=_boolean(
                raw.get("shadow_evaluation_authorized"),
                "shadow_evaluation_authorized",
            ),
            paper_only=_boolean(raw.get("paper_only"), "paper_only"),
            research_only=_boolean(raw.get("research_only"), "research_only"),
            promotion_eligible=_boolean(
                raw.get("promotion_eligible"), "promotion_eligible"
            ),
            execution_ready=_boolean(raw.get("execution_ready"), "execution_ready"),
            live_promotion_authorized=_boolean(
                raw.get("live_promotion_authorized"),
                "live_promotion_authorized",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except ValueError as exc:
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_INVALID"
        ) from exc
    if raw.get("shadow_admission_id") != admission.shadow_admission_id:
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_ID_MISMATCH"
        )
    return admission


def load_learning_shadow_admission(path: Path) -> LearningShadowAdmission:
    try:
        stored_bytes = path.read_bytes()
        raw = _mapping(json.loads(stored_bytes), "learning shadow admission")
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_INVALID"
        ) from exc
    admission = _admission_from_payload(raw)
    canonical = (_canonical_json(admission.to_dict()) + "\n").encode("utf-8")
    if stored_bytes != canonical:
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_NON_CANONICAL"
        )
    return admission


def verify_learning_shadow_admission(
    path: Path,
    *,
    review_decision_path: Path,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    evidence_root: Path,
) -> LearningShadowAdmission:
    stored = load_learning_shadow_admission(path)
    expected = build_learning_shadow_admission(
        review_decision_path=review_decision_path,
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        evidence_root=evidence_root,
        shadow_start_ms=stored.shadow_start_ms,
    )
    if stored != expected:
        raise LearningShadowAdmissionError(
            "LEARNING_SHADOW_ADMISSION_EVIDENCE_MISMATCH"
        )
    return stored
