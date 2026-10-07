from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_streak_context_audit import (
    LOSS_STREAK_CONTEXT_SCHEMA_VERSION,
)

ZERO: Final = Decimal("0")
LOSS_CONTEXT_CANDIDATE_SCHEMA_VERSION = 1
LOSS_CONTEXT_SELECTION_POLICY: Final = (
    "simplest_context_then_validation_breadth_and_robustness_v1"
)


class LossContextCandidateError(RuntimeError):
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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise LossContextCandidateError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise LossContextCandidateError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LossContextCandidateError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextCandidateError(
            f"{field} must be a non-negative integer"
        )
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise LossContextCandidateError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise LossContextCandidateError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise LossContextCandidateError(f"{field} must be finite")
    return result


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise LossContextCandidateError(
            f"{field} must be a lowercase SHA-256"
        )


def _require_commit_sha(value: str, field: str) -> None:
    if len(value) != 40 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise LossContextCandidateError(
            f"{field} must be a lowercase git SHA"
        )


def _validate_audit(
    audit: dict[str, object],
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    if (
        _integer(audit.get("schema_version"), "schema_version")
        != LOSS_STREAK_CONTEXT_SCHEMA_VERSION
    ):
        raise LossContextCandidateError(
            "LOSS_CONTEXT_AUDIT_SCHEMA_INVALID"
        )
    for field in ("research_only", "descriptive_only"):
        if audit.get(field) is not True:
            raise LossContextCandidateError(
                "LOSS_CONTEXT_AUDIT_METHODOLOGY_INVALID"
            )
    for field in (
        "execution_authority",
        "promotion_authority",
        "changes_strategy",
        "changes_risk_limits",
    ):
        if audit.get(field) is not False:
            raise LossContextCandidateError(
                "LOSS_CONTEXT_AUDIT_AUTHORITY_INVALID"
            )
    if audit.get("baseline_normalization_complete") is not True:
        raise LossContextCandidateError(
            "LOSS_CONTEXT_BASELINE_INCOMPLETE"
        )

    stability = _mapping(
        audit.get("context_filter_stability"),
        "context_filter_stability",
    )
    if _integer(stability.get("schema_version"), "stability schema") != 1:
        raise LossContextCandidateError(
            "LOSS_CONTEXT_STABILITY_SCHEMA_INVALID"
        )
    if (
        stability.get("direction_only_candidates_allowed") is not False
        or stability.get("lead_strategy_context_required") is not True
        or stability.get("entry_time_context_only") is not True
        or stability.get("realized_net_pnl_economics_required") is not True
        or stability.get("chronological_holdout_required") is not True
        or stability.get("leave_one_trade_robustness_required") is not True
        or stability.get("leave_one_market_robustness_required") is not True
        or stability.get("validation_block_consistency_required") is not True
        or stability.get("prospective_freeze_required_before_strategy_use")
        is not True
    ):
        raise LossContextCandidateError(
            "LOSS_CONTEXT_STABILITY_METHODOLOGY_INVALID"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if stability.get(field) is not False:
            raise LossContextCandidateError(
                "LOSS_CONTEXT_STABILITY_AUTHORITY_INVALID"
            )

    raw_candidates = _sequence(stability.get("candidates"), "candidates")
    candidates = tuple(
        _mapping(item, "candidate") for item in raw_candidates
    )
    return stability, candidates


def _candidate_context(
    candidate: dict[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    dimensions = tuple(
        _string(item, "dimension")
        for item in _sequence(candidate.get("dimensions"), "dimensions")
    )
    values = tuple(
        _string(item, "value")
        for item in _sequence(candidate.get("values"), "values")
    )
    if not dimensions or len(dimensions) != len(values):
        raise LossContextCandidateError(
            "LOSS_CONTEXT_CANDIDATE_CONTEXT_INVALID"
        )
    if dimensions == ("direction",):
        raise LossContextCandidateError(
            "LOSS_CONTEXT_DIRECTION_ONLY_FORBIDDEN"
        )
    if "lead_strategy" not in dimensions:
        raise LossContextCandidateError(
            "LOSS_CONTEXT_LEAD_STRATEGY_REQUIRED"
        )
    return dimensions, values


def _stable_candidate(
    audit: dict[str, object],
) -> dict[str, object] | None:
    _stability, candidates = _validate_audit(audit)
    stable: list[dict[str, object]] = []
    for candidate in candidates:
        dimensions, _values = _candidate_context(candidate)
        if candidate.get("stable_on_validation") is not True:
            continue
        validation_rows = _integer(
            candidate.get("validation_rows"),
            "validation_rows",
        )
        validation_markets = _integer(
            candidate.get("validation_markets"),
            "validation_markets",
        )
        validation_delta = _decimal(
            candidate.get("validation_filter_delta_pnl"),
            "validation_filter_delta_pnl",
        )
        loo_trade = _decimal(
            candidate.get("validation_leave_one_trade_min_delta_pnl"),
            "validation_leave_one_trade_min_delta_pnl",
        )
        loo_market = _decimal(
            candidate.get("validation_leave_one_market_min_delta_pnl"),
            "validation_leave_one_market_min_delta_pnl",
        )
        if (
            validation_rows <= 0
            or validation_markets <= 0
            or validation_delta <= ZERO
            or loo_trade <= ZERO
            or loo_market <= ZERO
        ):
            raise LossContextCandidateError(
                "LOSS_CONTEXT_STABLE_CANDIDATE_INVALID"
            )
        if "lead_strategy" not in dimensions:
            raise LossContextCandidateError(
                "LOSS_CONTEXT_LEAD_STRATEGY_REQUIRED"
            )
        stable.append(candidate)

    if not stable:
        return None

    def sort_key(item: dict[str, object]) -> tuple[object, ...]:
        dimensions, values = _candidate_context(item)
        return (
            len(dimensions),
            -_integer(item.get("validation_rows"), "validation_rows"),
            -_integer(
                item.get("validation_markets"),
                "validation_markets",
            ),
            -_decimal(
                item.get("validation_leave_one_market_min_delta_pnl"),
                "validation_leave_one_market_min_delta_pnl",
            ),
            -_decimal(
                item.get("validation_filter_delta_pnl"),
                "validation_filter_delta_pnl",
            ),
            dimensions,
            values,
        )

    return sorted(stable, key=sort_key)[0]


@dataclass(frozen=True, slots=True)
class LossContextCandidateFreeze:
    source_audit_digest: str
    source_max_timestamp_ms: int
    source_paper_run_id: int
    source_paper_run_attempt: int
    source_paper_head_sha: str
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    discovery_rows: int
    discovery_markets: int
    discovery_loss_share: Decimal
    discovery_filter_delta_pnl: Decimal
    validation_rows: int
    validation_markets: int
    validation_loss_share: Decimal
    validation_filter_delta_pnl: Decimal
    validation_leave_one_trade_min_delta_pnl: Decimal
    validation_leave_one_market_min_delta_pnl: Decimal
    frozen_at_ms: int
    prospective_not_before_ms: int
    selection_policy: str = LOSS_CONTEXT_SELECTION_POLICY
    prospective_only: bool = True
    paper_only: bool = True
    research_only: bool = True
    changes_strategy: bool = False
    changes_risk_limits: bool = False
    promotion_authority: bool = False
    execution_authority: bool = False
    schema_version: int = LOSS_CONTEXT_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.source_audit_digest, "source_audit_digest")
        _require_commit_sha(
            self.source_paper_head_sha,
            "source_paper_head_sha",
        )
        if self.source_paper_run_id <= 0 or self.source_paper_run_attempt <= 0:
            raise ValueError("source paper run identity must be positive")
        if not self.dimensions or len(self.dimensions) != len(self.values):
            raise ValueError("frozen context must be non-empty and aligned")
        if "lead_strategy" not in self.dimensions:
            raise ValueError("frozen context must retain lead strategy")
        if self.dimensions == ("direction",):
            raise ValueError("direction-only frozen context is forbidden")
        if self.discovery_rows <= 0 or self.validation_rows <= 0:
            raise ValueError("frozen candidate row counts must be positive")
        if self.discovery_markets <= 0 or self.validation_markets <= 0:
            raise ValueError("frozen candidate market counts must be positive")
        for share, field in (
            (self.discovery_loss_share, "discovery_loss_share"),
            (self.validation_loss_share, "validation_loss_share"),
        ):
            if not ZERO < share <= Decimal("1"):
                raise ValueError(f"{field} must be in (0, 1]")
        for value, field in (
            (self.discovery_filter_delta_pnl, "discovery_filter_delta_pnl"),
            (self.validation_filter_delta_pnl, "validation_filter_delta_pnl"),
            (
                self.validation_leave_one_trade_min_delta_pnl,
                "validation_leave_one_trade_min_delta_pnl",
            ),
            (
                self.validation_leave_one_market_min_delta_pnl,
                "validation_leave_one_market_min_delta_pnl",
            ),
        ):
            if value <= ZERO:
                raise ValueError(f"{field} must be positive")
        if self.frozen_at_ms < self.source_max_timestamp_ms:
            raise ValueError("freeze must not precede source evidence")
        if self.prospective_not_before_ms != (
            self.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ):
            raise ValueError(
                "prospective boundary must equal freeze plus embargo"
            )
        if self.selection_policy != LOSS_CONTEXT_SELECTION_POLICY:
            raise ValueError("unsupported loss-context selection policy")
        if not self.prospective_only or not self.paper_only:
            raise ValueError("loss-context freeze must remain prospective paper")
        if not self.research_only:
            raise ValueError("loss-context freeze must remain research only")
        if self.changes_strategy or self.changes_risk_limits:
            raise ValueError("loss-context freeze cannot change behavior")
        if self.promotion_authority or self.execution_authority:
            raise ValueError("loss-context freeze cannot grant authority")
        if self.schema_version != LOSS_CONTEXT_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported loss-context candidate schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_audit_digest": self.source_audit_digest,
            "source_max_timestamp_ms": self.source_max_timestamp_ms,
            "source_paper_run_id": self.source_paper_run_id,
            "source_paper_run_attempt": self.source_paper_run_attempt,
            "source_paper_head_sha": self.source_paper_head_sha,
            "dimensions": self.dimensions,
            "values": self.values,
            "discovery_rows": self.discovery_rows,
            "discovery_markets": self.discovery_markets,
            "discovery_loss_share": str(self.discovery_loss_share),
            "discovery_filter_delta_pnl": str(
                self.discovery_filter_delta_pnl
            ),
            "validation_rows": self.validation_rows,
            "validation_markets": self.validation_markets,
            "validation_loss_share": str(self.validation_loss_share),
            "validation_filter_delta_pnl": str(
                self.validation_filter_delta_pnl
            ),
            "validation_leave_one_trade_min_delta_pnl": str(
                self.validation_leave_one_trade_min_delta_pnl
            ),
            "validation_leave_one_market_min_delta_pnl": str(
                self.validation_leave_one_market_min_delta_pnl
            ),
            "frozen_at_ms": self.frozen_at_ms,
            "prospective_not_before_ms": self.prospective_not_before_ms,
            "selection_policy": self.selection_policy,
            "prospective_only": self.prospective_only,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "changes_strategy": self.changes_strategy,
            "changes_risk_limits": self.changes_risk_limits,
            "promotion_authority": self.promotion_authority,
            "execution_authority": self.execution_authority,
            "schema_version": self.schema_version,
        }

    @property
    def candidate_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "candidate_id": self.candidate_id}


def build_loss_context_candidate_freeze(
    audit: dict[str, object],
    *,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> LossContextCandidateFreeze | None:
    candidate = _stable_candidate(audit)
    if candidate is None:
        return None
    if frozen_at_ms < 0:
        raise ValueError("frozen_at_ms must be non-negative")
    source_max_timestamp_ms = _integer(
        audit.get("max_trade_closed_at_ms"),
        "max_trade_closed_at_ms",
    )
    dimensions, values = _candidate_context(candidate)
    return LossContextCandidateFreeze(
        source_audit_digest=_sha256_json(audit),
        source_max_timestamp_ms=source_max_timestamp_ms,
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_paper_head_sha=source_paper_head_sha,
        dimensions=dimensions,
        values=values,
        discovery_rows=_integer(
            candidate.get("discovery_rows"),
            "discovery_rows",
        ),
        discovery_markets=_integer(
            candidate.get("discovery_markets"),
            "discovery_markets",
        ),
        discovery_loss_share=_decimal(
            candidate.get("discovery_loss_share"),
            "discovery_loss_share",
        ),
        discovery_filter_delta_pnl=_decimal(
            candidate.get("discovery_filter_delta_pnl"),
            "discovery_filter_delta_pnl",
        ),
        validation_rows=_integer(
            candidate.get("validation_rows"),
            "validation_rows",
        ),
        validation_markets=_integer(
            candidate.get("validation_markets"),
            "validation_markets",
        ),
        validation_loss_share=_decimal(
            candidate.get("validation_loss_share"),
            "validation_loss_share",
        ),
        validation_filter_delta_pnl=_decimal(
            candidate.get("validation_filter_delta_pnl"),
            "validation_filter_delta_pnl",
        ),
        validation_leave_one_trade_min_delta_pnl=_decimal(
            candidate.get("validation_leave_one_trade_min_delta_pnl"),
            "validation_leave_one_trade_min_delta_pnl",
        ),
        validation_leave_one_market_min_delta_pnl=_decimal(
            candidate.get("validation_leave_one_market_min_delta_pnl"),
            "validation_leave_one_market_min_delta_pnl",
        ),
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def _from_payload(
    payload: dict[str, object],
) -> LossContextCandidateFreeze:
    freeze = LossContextCandidateFreeze(
        source_audit_digest=_string(
            payload.get("source_audit_digest"),
            "source_audit_digest",
        ),
        source_max_timestamp_ms=_integer(
            payload.get("source_max_timestamp_ms"),
            "source_max_timestamp_ms",
        ),
        source_paper_run_id=_integer(
            payload.get("source_paper_run_id"),
            "source_paper_run_id",
        ),
        source_paper_run_attempt=_integer(
            payload.get("source_paper_run_attempt"),
            "source_paper_run_attempt",
        ),
        source_paper_head_sha=_string(
            payload.get("source_paper_head_sha"),
            "source_paper_head_sha",
        ),
        dimensions=tuple(
            _string(item, "dimension")
            for item in _sequence(payload.get("dimensions"), "dimensions")
        ),
        values=tuple(
            _string(item, "value")
            for item in _sequence(payload.get("values"), "values")
        ),
        discovery_rows=_integer(
            payload.get("discovery_rows"),
            "discovery_rows",
        ),
        discovery_markets=_integer(
            payload.get("discovery_markets"),
            "discovery_markets",
        ),
        discovery_loss_share=_decimal(
            payload.get("discovery_loss_share"),
            "discovery_loss_share",
        ),
        discovery_filter_delta_pnl=_decimal(
            payload.get("discovery_filter_delta_pnl"),
            "discovery_filter_delta_pnl",
        ),
        validation_rows=_integer(
            payload.get("validation_rows"),
            "validation_rows",
        ),
        validation_markets=_integer(
            payload.get("validation_markets"),
            "validation_markets",
        ),
        validation_loss_share=_decimal(
            payload.get("validation_loss_share"),
            "validation_loss_share",
        ),
        validation_filter_delta_pnl=_decimal(
            payload.get("validation_filter_delta_pnl"),
            "validation_filter_delta_pnl",
        ),
        validation_leave_one_trade_min_delta_pnl=_decimal(
            payload.get("validation_leave_one_trade_min_delta_pnl"),
            "validation_leave_one_trade_min_delta_pnl",
        ),
        validation_leave_one_market_min_delta_pnl=_decimal(
            payload.get("validation_leave_one_market_min_delta_pnl"),
            "validation_leave_one_market_min_delta_pnl",
        ),
        frozen_at_ms=_integer(
            payload.get("frozen_at_ms"),
            "frozen_at_ms",
        ),
        prospective_not_before_ms=_integer(
            payload.get("prospective_not_before_ms"),
            "prospective_not_before_ms",
        ),
        selection_policy=_string(
            payload.get("selection_policy"),
            "selection_policy",
        ),
        prospective_only=payload.get("prospective_only") is True,
        paper_only=payload.get("paper_only") is True,
        research_only=payload.get("research_only") is True,
        changes_strategy=payload.get("changes_strategy") is True,
        changes_risk_limits=payload.get("changes_risk_limits") is True,
        promotion_authority=payload.get("promotion_authority") is True,
        execution_authority=payload.get("execution_authority") is True,
        schema_version=_integer(
            payload.get("schema_version"),
            "schema_version",
        ),
    )
    candidate_id = _string(payload.get("candidate_id"), "candidate_id")
    _require_sha256(candidate_id, "candidate_id")
    if candidate_id != freeze.candidate_id:
        raise LossContextCandidateError(
            "LOSS_CONTEXT_CANDIDATE_ID_MISMATCH"
        )
    return freeze


def verify_loss_context_candidate_freeze(
    path: str | Path,
) -> LossContextCandidateFreeze:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LossContextCandidateError(
            "loss-context freeze is missing or invalid"
        ) from exc
    return _from_payload(_mapping(raw, "loss-context freeze"))


def write_loss_context_candidate_freeze(
    audit: dict[str, object],
    *,
    output_path: str | Path,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> tuple[LossContextCandidateFreeze | None, bool]:
    path = Path(output_path)
    if path.exists():
        return verify_loss_context_candidate_freeze(path), False

    freeze = build_loss_context_candidate_freeze(
        audit,
        frozen_at_ms=frozen_at_ms,
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_paper_head_sha=source_paper_head_sha,
    )
    if freeze is None:
        return None, False

    encoded = (_canonical_json(freeze.to_dict()) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return freeze, True
