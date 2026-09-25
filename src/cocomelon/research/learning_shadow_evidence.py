from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_shadow_admission import LearningShadowAdmission
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)

LEARNING_SHADOW_EVIDENCE_MANIFEST_SCHEMA_VERSION = 1
SHADOW_SOURCE_EVIDENCE_CLASS = "learned_shadow_evaluation"


class LearningShadowEvidenceError(RuntimeError):
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
        raise LearningShadowEvidenceError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningShadowEvidenceError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningShadowEvidenceError(f"{field} must be a non-negative integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LearningShadowEvidenceError(f"{field} must be a decimal string")
    try:
        resolved = Decimal(value)
    except Exception as exc:
        raise LearningShadowEvidenceError(f"{field} must be a decimal string") from exc
    if not resolved.is_finite():
        raise LearningShadowEvidenceError(f"{field} must be finite")
    return resolved


def _market_from_canonical(value: str) -> MarketId:
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    if not dex or not coin or ":" in coin:
        raise LearningShadowEvidenceError("shadow execution market is invalid")
    return MarketId(dex, coin)


@dataclass(frozen=True, slots=True)
class LearningShadowEvidenceManifest:
    shadow_admission_id: str
    candidate_id: str
    shadow_start_ms: int
    minimum_closed_mainnet_paper_trades: int
    minimum_shadow_calendar_days: int
    source_evidence_class: str = SHADOW_SOURCE_EVIDENCE_CLASS
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = LEARNING_SHADOW_EVIDENCE_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.shadow_admission_id, "shadow_admission_id")
        _require_sha256(self.candidate_id, "candidate_id")
        if self.shadow_start_ms < 0:
            raise ValueError("shadow_start_ms must be non-negative")
        if self.minimum_closed_mainnet_paper_trades <= 0:
            raise ValueError("minimum paper-trade floor must be positive")
        if self.minimum_shadow_calendar_days <= 0:
            raise ValueError("minimum shadow-day floor must be positive")
        if self.source_evidence_class != SHADOW_SOURCE_EVIDENCE_CLASS:
            raise ValueError("unsupported shadow source evidence class")
        if not self.paper_only or not self.research_only:
            raise ValueError("shadow evidence manifest must remain paper research")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("shadow evidence manifest cannot authorize promotion or execution")
        if self.schema_version != LEARNING_SHADOW_EVIDENCE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported learning shadow evidence manifest schema")

    @classmethod
    def from_admission(
        cls,
        admission: LearningShadowAdmission,
    ) -> LearningShadowEvidenceManifest:
        return cls(
            shadow_admission_id=admission.shadow_admission_id,
            candidate_id=admission.candidate_id,
            shadow_start_ms=admission.shadow_start_ms,
            minimum_closed_mainnet_paper_trades=(
                admission.minimum_closed_mainnet_paper_trades
            ),
            minimum_shadow_calendar_days=admission.minimum_shadow_calendar_days,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "shadow_admission_id": self.shadow_admission_id,
            "candidate_id": self.candidate_id,
            "shadow_start_ms": self.shadow_start_ms,
            "minimum_closed_mainnet_paper_trades": (
                self.minimum_closed_mainnet_paper_trades
            ),
            "minimum_shadow_calendar_days": self.minimum_shadow_calendar_days,
            "source_evidence_class": self.source_evidence_class,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def manifest_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "manifest_id": self.manifest_id}


def learning_shadow_execution_from_payload(
    raw: dict[str, object],
) -> LearningEvidenceRecord:
    try:
        record = LearningEvidenceRecord(
            kind=LearningEvidenceKind(_string(raw.get("kind"), "kind")),
            source_record_id=_string(
                raw.get("source_record_id"),
                "source_record_id",
            ),
            source_evidence_class=_string(
                raw.get("source_evidence_class"),
                "source_evidence_class",
            ),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            candidate_spec_id=_optional_string(
                raw.get("candidate_spec_id"),
                "candidate_spec_id",
            ),
            campaign_id=_optional_string(raw.get("campaign_id"), "campaign_id"),
            market=_market_from_canonical(_string(raw.get("market"), "market")),
            direction=Direction(_string(raw.get("direction"), "direction")),
            opened_at_ms=_integer(raw.get("opened_at_ms"), "opened_at_ms"),
            closed_at_ms=_integer(raw.get("closed_at_ms"), "closed_at_ms"),
            feature_snapshot_id=_string(
                raw.get("feature_snapshot_id"),
                "feature_snapshot_id",
            ),
            research_eligible_at_ms=_integer(
                raw.get("research_eligible_at_ms"),
                "research_eligible_at_ms",
            ),
            context_state_1h=_optional_string(
                raw.get("context_state_1h"),
                "context_state_1h",
            ),
            gross_realized_pnl=_decimal(
                raw.get("gross_realized_pnl"),
                "gross_realized_pnl",
            ),
            entry_fees=_decimal(raw.get("entry_fees"), "entry_fees"),
            exit_fees=_decimal(raw.get("exit_fees"), "exit_fees"),
            funding_cash_pnl=_decimal(
                raw.get("funding_cash_pnl"),
                "funding_cash_pnl",
            ),
            entry_slippage_fraction=_decimal(
                raw.get("entry_slippage_fraction"),
                "entry_slippage_fraction",
            ),
            exit_slippage_fraction=_decimal(
                raw.get("exit_slippage_fraction"),
                "exit_slippage_fraction",
            ),
            net_pnl=_decimal(raw.get("net_pnl"), "net_pnl"),
            net_r=_decimal(raw.get("net_r"), "net_r"),
            schema_version=_integer(raw.get("schema_version"), "schema_version"),
        )
    except ValueError as exc:
        raise LearningShadowEvidenceError(
            "LEARNING_SHADOW_EXECUTION_INVALID"
        ) from exc
    if raw.get("record_id") is not None and raw.get("record_id") != record.record_id:
        raise LearningShadowEvidenceError(
            "LEARNING_SHADOW_EXECUTION_ID_MISMATCH"
        )
    return record


class LearningShadowEvidenceStore:
    def __init__(
        self,
        root: Path,
        *,
        admission: LearningShadowAdmission,
    ) -> None:
        self.root = root
        self.admission = admission
        self.manifest = LearningShadowEvidenceManifest.from_admission(admission)
        self.ledger = LearningEvidenceLedger(root / "ledger")
        self._write_manifest()
        self._verify_manifest()

    def _write_manifest(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "manifest.json"
        payload = (_canonical_json(self.manifest.to_dict()) + "\n").encode("utf-8")
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise LearningShadowEvidenceError(
                    "LEARNING_SHADOW_EVIDENCE_MANIFEST_CONFLICT"
                )
            return
        temporary = self.root / ".manifest.json.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _verify_manifest(self) -> None:
        path = self.root / "manifest.json"
        if path.is_symlink():
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_MANIFEST_SYMLINK_FORBIDDEN"
            )
        try:
            stored = path.read_bytes()
            raw = _mapping(json.loads(stored), "learning shadow evidence manifest")
        except (OSError, json.JSONDecodeError) as exc:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_MANIFEST_INVALID"
            ) from exc
        try:
            manifest = LearningShadowEvidenceManifest(
                shadow_admission_id=_string(
                    raw.get("shadow_admission_id"),
                    "shadow_admission_id",
                ),
                candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
                shadow_start_ms=_integer(
                    raw.get("shadow_start_ms"),
                    "shadow_start_ms",
                ),
                minimum_closed_mainnet_paper_trades=_integer(
                    raw.get("minimum_closed_mainnet_paper_trades"),
                    "minimum_closed_mainnet_paper_trades",
                ),
                minimum_shadow_calendar_days=_integer(
                    raw.get("minimum_shadow_calendar_days"),
                    "minimum_shadow_calendar_days",
                ),
                source_evidence_class=_string(
                    raw.get("source_evidence_class"),
                    "source_evidence_class",
                ),
                paper_only=bool(raw.get("paper_only")),
                research_only=bool(raw.get("research_only")),
                promotion_eligible=bool(raw.get("promotion_eligible")),
                execution_ready=bool(raw.get("execution_ready")),
                schema_version=_integer(raw.get("schema_version"), "schema_version"),
            )
        except ValueError as exc:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_MANIFEST_INVALID"
            ) from exc
        if raw.get("manifest_id") != manifest.manifest_id:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_MANIFEST_ID_MISMATCH"
            )
        if manifest != self.manifest:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_MANIFEST_ADMISSION_MISMATCH"
            )
        canonical = (_canonical_json(manifest.to_dict()) + "\n").encode("utf-8")
        if stored != canonical:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_MANIFEST_NON_CANONICAL"
            )

    def _validate_record(self, record: LearningEvidenceRecord) -> None:
        if record.kind is not LearningEvidenceKind.PAPER_EXECUTION:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_KIND_INVALID"
            )
        if record.source_evidence_class != SHADOW_SOURCE_EVIDENCE_CLASS:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_CLASS_INVALID"
            )
        if record.candidate_id != self.admission.candidate_id:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_CANDIDATE_MISMATCH"
            )
        if record.candidate_spec_id != self.admission.shadow_admission_id:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_ADMISSION_MISMATCH"
            )
        if record.campaign_id is None:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_CAMPAIGN_REQUIRED"
            )
        if record.opened_at_ms < self.admission.shadow_start_ms:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_PRE_ADMISSION_TRADE"
            )

    def record_execution(self, record: LearningEvidenceRecord) -> bool:
        self._validate_record(record)
        return self.ledger.record(record)

    def iter_records(self) -> tuple[LearningEvidenceRecord, ...]:
        records = self.ledger.iter_records()
        for record in records:
            self._validate_record(record)
        return records

    @property
    def state_digest(self) -> str:
        self._verify_manifest()
        records = self.iter_records()
        return _sha256_json(
            {
                "manifest_id": self.manifest.manifest_id,
                "record_ids": tuple(record.record_id for record in records),
                "ledger_state_digest": self.ledger.state_digest,
            }
        )

    def verify(self) -> None:
        self._verify_manifest()
        self.iter_records()
        for path in self.root.rglob("*"):
            if path.is_symlink():
                raise LearningShadowEvidenceError(
                    "LEARNING_SHADOW_EVIDENCE_SYMLINK_FORBIDDEN"
                )
        allowed = {"manifest.json"}
        allowed.update(
            path.relative_to(self.root).as_posix()
            for path in (self.root / "ledger" / "records").glob("*/*.json")
        )
        actual = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file()
        }
        if actual != allowed:
            raise LearningShadowEvidenceError(
                "LEARNING_SHADOW_EVIDENCE_FILE_SET_INVALID"
            )
