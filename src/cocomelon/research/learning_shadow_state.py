from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from cocomelon.research.learning_shadow_evidence import (
    open_verified_learning_shadow_evidence_store,
)

LEARNING_SHADOW_STATE_SCHEMA_VERSION = 1


class LearningShadowStateError(RuntimeError):
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
        raise LearningShadowStateError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningShadowStateError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningShadowStateError(f"{field} must be a non-negative integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningShadowStateError(f"{field} must be boolean")
    return value


@dataclass(frozen=True, slots=True)
class LearningShadowState:
    candidate_id: str
    shadow_admission_id: str
    review_decision_id: str
    shadow_start_ms: int
    as_of_ms: int
    shadow_evidence_state_digest: str
    closed_paper_trade_count: int
    campaign_count: int
    first_opened_at_ms: int | None
    latest_closed_at_ms: int | None
    minimum_closed_mainnet_paper_trades: int
    minimum_shadow_calendar_days: int
    status: str
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    live_promotion_authorized: bool = False
    schema_version: int = LEARNING_SHADOW_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "shadow_admission_id",
            "review_decision_id",
            "shadow_evidence_state_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if self.shadow_start_ms < 0 or self.as_of_ms < 0:
            raise ValueError("shadow state timestamps must be non-negative")
        if self.closed_paper_trade_count < 0 or self.campaign_count < 0:
            raise ValueError("shadow state counts must be non-negative")
        if self.minimum_closed_mainnet_paper_trades <= 0:
            raise ValueError("minimum paper-trade floor must be positive")
        if self.minimum_shadow_calendar_days <= 0:
            raise ValueError("minimum shadow-day floor must be positive")
        if self.first_opened_at_ms is None:
            if self.latest_closed_at_ms is not None or self.closed_paper_trade_count != 0:
                raise ValueError("empty shadow state timestamps do not reconcile")
        else:
            if self.latest_closed_at_ms is None:
                raise ValueError("non-empty shadow state requires latest close")
            if self.first_opened_at_ms < self.shadow_start_ms:
                raise ValueError("shadow state contains pre-admission trade")
            if self.latest_closed_at_ms < self.first_opened_at_ms:
                raise ValueError("shadow state trade interval is invalid")
            if self.latest_closed_at_ms > self.as_of_ms:
                raise ValueError("shadow state contains future evidence")
            if self.closed_paper_trade_count == 0:
                raise ValueError("shadow state timestamps require evidence")
        if self.status not in {"waiting_for_shadow_start", "collecting"}:
            raise ValueError("unsupported learning shadow state status")
        if self.status == "waiting_for_shadow_start":
            if self.as_of_ms >= self.shadow_start_ms:
                raise ValueError("waiting shadow state must precede shadow start")
            if self.closed_paper_trade_count or self.campaign_count:
                raise ValueError("pre-shadow state must not contain evidence")
        else:
            if self.as_of_ms < self.shadow_start_ms:
                raise ValueError("collecting shadow state cannot predate shadow start")
        if not self.paper_only or not self.research_only:
            raise ValueError("shadow state must remain paper research")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("shadow state cannot authorize promotion or execution")
        if self.live_promotion_authorized:
            raise ValueError("shadow state cannot authorize live capital")
        if self.schema_version != LEARNING_SHADOW_STATE_SCHEMA_VERSION:
            raise ValueError("unsupported learning shadow state schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "shadow_admission_id": self.shadow_admission_id,
            "review_decision_id": self.review_decision_id,
            "shadow_start_ms": self.shadow_start_ms,
            "as_of_ms": self.as_of_ms,
            "shadow_evidence_state_digest": self.shadow_evidence_state_digest,
            "closed_paper_trade_count": self.closed_paper_trade_count,
            "campaign_count": self.campaign_count,
            "first_opened_at_ms": self.first_opened_at_ms,
            "latest_closed_at_ms": self.latest_closed_at_ms,
            "minimum_closed_mainnet_paper_trades": (
                self.minimum_closed_mainnet_paper_trades
            ),
            "minimum_shadow_calendar_days": self.minimum_shadow_calendar_days,
            "status": self.status,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "live_promotion_authorized": self.live_promotion_authorized,
            "schema_version": self.schema_version,
        }

    @property
    def state_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "state_id": self.state_id}


def build_learning_shadow_state(
    *,
    shadow_evidence_root: Path,
    shadow_admission_path: Path,
    review_decision_path: Path,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    clean_evidence_root: Path,
    as_of_ms: int,
) -> LearningShadowState:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")

    store = open_verified_learning_shadow_evidence_store(
        shadow_evidence_root,
        shadow_admission_path=shadow_admission_path,
        review_decision_path=review_decision_path,
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
    )
    records = store.iter_records()
    for record in records:
        if record.closed_at_ms > as_of_ms or record.research_eligible_at_ms > as_of_ms:
            raise LearningShadowStateError("LEARNING_SHADOW_STATE_FUTURE_EVIDENCE")
    campaigns = {
        record.campaign_id
        for record in records
        if record.campaign_id is not None
    }
    if len(campaigns) > len(records):
        raise LearningShadowStateError("LEARNING_SHADOW_STATE_CAMPAIGN_COUNT_INVALID")

    first_opened_at_ms = (
        None if not records else min(record.opened_at_ms for record in records)
    )
    latest_closed_at_ms = (
        None if not records else max(record.closed_at_ms for record in records)
    )
    admission = store.admission
    status = (
        "waiting_for_shadow_start"
        if as_of_ms < admission.shadow_start_ms
        else "collecting"
    )
    return LearningShadowState(
        candidate_id=admission.candidate_id,
        shadow_admission_id=admission.shadow_admission_id,
        review_decision_id=admission.review_decision_id,
        shadow_start_ms=admission.shadow_start_ms,
        as_of_ms=as_of_ms,
        shadow_evidence_state_digest=store.state_digest,
        closed_paper_trade_count=len(records),
        campaign_count=len(campaigns),
        first_opened_at_ms=first_opened_at_ms,
        latest_closed_at_ms=latest_closed_at_ms,
        minimum_closed_mainnet_paper_trades=(
            admission.minimum_closed_mainnet_paper_trades
        ),
        minimum_shadow_calendar_days=admission.minimum_shadow_calendar_days,
        status=status,
    )


def write_learning_shadow_state(
    output_root: Path,
    state: LearningShadowState,
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "shadow-state.json"
    payload = (_canonical_json(state.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LearningShadowStateError("LEARNING_SHADOW_STATE_CONFLICT")
        return path
    temporary = output_root / ".shadow-state.json.tmp"
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


def _state_from_payload(raw: dict[str, object]) -> LearningShadowState:
    try:
        state = LearningShadowState(
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            shadow_admission_id=_string(
                raw.get("shadow_admission_id"),
                "shadow_admission_id",
            ),
            review_decision_id=_string(
                raw.get("review_decision_id"),
                "review_decision_id",
            ),
            shadow_start_ms=_integer(raw.get("shadow_start_ms"), "shadow_start_ms"),
            as_of_ms=_integer(raw.get("as_of_ms"), "as_of_ms"),
            shadow_evidence_state_digest=_string(
                raw.get("shadow_evidence_state_digest"),
                "shadow_evidence_state_digest",
            ),
            closed_paper_trade_count=_integer(
                raw.get("closed_paper_trade_count"),
                "closed_paper_trade_count",
            ),
            campaign_count=_integer(raw.get("campaign_count"), "campaign_count"),
            first_opened_at_ms=_optional_integer(
                raw.get("first_opened_at_ms"),
                "first_opened_at_ms",
            ),
            latest_closed_at_ms=_optional_integer(
                raw.get("latest_closed_at_ms"),
                "latest_closed_at_ms",
            ),
            minimum_closed_mainnet_paper_trades=_integer(
                raw.get("minimum_closed_mainnet_paper_trades"),
                "minimum_closed_mainnet_paper_trades",
            ),
            minimum_shadow_calendar_days=_integer(
                raw.get("minimum_shadow_calendar_days"),
                "minimum_shadow_calendar_days",
            ),
            status=_string(raw.get("status"), "status"),
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
            live_promotion_authorized=_boolean(
                raw.get("live_promotion_authorized"),
                "live_promotion_authorized",
            ),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except ValueError as exc:
        raise LearningShadowStateError("LEARNING_SHADOW_STATE_INVALID") from exc
    if raw.get("state_id") != state.state_id:
        raise LearningShadowStateError("LEARNING_SHADOW_STATE_ID_MISMATCH")
    return state


def load_learning_shadow_state(path: Path) -> LearningShadowState:
    try:
        stored = path.read_bytes()
        raw = _mapping(json.loads(stored), "learning shadow state")
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningShadowStateError("LEARNING_SHADOW_STATE_INVALID") from exc
    state = _state_from_payload(raw)
    canonical = (_canonical_json(state.to_dict()) + "\n").encode("utf-8")
    if stored != canonical:
        raise LearningShadowStateError("LEARNING_SHADOW_STATE_NON_CANONICAL")
    return state


def verify_learning_shadow_state(
    path: Path,
    *,
    shadow_evidence_root: Path,
    shadow_admission_path: Path,
    review_decision_path: Path,
    review_dossier_path: Path,
    package_root: Path,
    validation_spec_path: Path,
    validation_score_path: Path,
    finalization_path: Path,
    clean_evidence_root: Path,
) -> LearningShadowState:
    stored = load_learning_shadow_state(path)
    expected = build_learning_shadow_state(
        shadow_evidence_root=shadow_evidence_root,
        shadow_admission_path=shadow_admission_path,
        review_decision_path=review_decision_path,
        review_dossier_path=review_dossier_path,
        package_root=package_root,
        validation_spec_path=validation_spec_path,
        validation_score_path=validation_score_path,
        finalization_path=finalization_path,
        clean_evidence_root=clean_evidence_root,
        as_of_ms=stored.as_of_ms,
    )
    if stored != expected:
        raise LearningShadowStateError("LEARNING_SHADOW_STATE_EVIDENCE_MISMATCH")
    return stored
