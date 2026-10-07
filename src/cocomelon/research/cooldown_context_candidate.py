from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.cooldown_context_selection import (
    COOLDOWN_CONTEXT_SELECTION_POLICY,
    COOLDOWN_CONTEXT_SELECTION_SCHEMA_VERSION,
)
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)

ZERO: Final = Decimal("0")
COOLDOWN_CONTEXT_CANDIDATE_SCHEMA_VERSION = 1
COOLDOWN_CONTEXT_CANDIDATE_KIND: Final = (
    "prospective_consecutive_loss_cooldown_context_shadow"
)
EXPECTED_COOLDOWN_CANDIDATE_ID: Final = (
    "prospective-consecutive-loss-cooldown-relaxation-v1"
)


class CooldownContextCandidateError(RuntimeError):
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
        raise CooldownContextCandidateError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise CooldownContextCandidateError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CooldownContextCandidateError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CooldownContextCandidateError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise CooldownContextCandidateError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise CooldownContextCandidateError(
            f"{field} must be a decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise CooldownContextCandidateError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise CooldownContextCandidateError(f"{field} must be finite")
    return result


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise CooldownContextCandidateError(
            f"{field} must be a lowercase SHA-256"
        )


def _require_commit_sha(value: str, field: str) -> None:
    if len(value) != 40 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise CooldownContextCandidateError(
            f"{field} must be a lowercase git SHA"
        )


def _validate_selection(
    selection: dict[str, object],
) -> dict[str, object]:
    source_record_id = _string(
        selection.get("source_record_id"),
        "source_record_id",
    )
    _require_sha256(source_record_id, "source_record_id")
    identity = {
        key: value
        for key, value in selection.items()
        if key != "source_record_id"
    }
    if _sha256_json(identity) != source_record_id:
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_SELECTION_ID_MISMATCH"
        )
    if (
        _integer(selection.get("schema_version"), "schema_version")
        != COOLDOWN_CONTEXT_SELECTION_SCHEMA_VERSION
    ):
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_SELECTION_SCHEMA_INVALID"
        )
    if (
        _string(selection.get("selection_policy"), "selection_policy")
        != COOLDOWN_CONTEXT_SELECTION_POLICY
    ):
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_SELECTION_POLICY_INVALID"
        )
    for field in (
        "lead_strategy_context_required",
        "relaxation_window_context_required",
        "window_eligible_outcomes_only",
        "prospective_freeze_required_before_strategy_use",
        "research_only",
        "descriptive_only",
    ):
        if _boolean(selection.get(field), field) is not True:
            raise CooldownContextCandidateError(
                "COOLDOWN_CONTEXT_SELECTION_METHODOLOGY_INVALID"
            )
    for field in (
        "direction_only_candidates_allowed",
        "changes_strategy",
        "changes_risk_limits",
        "promotion_authority",
        "execution_authority",
    ):
        if _boolean(selection.get(field), field) is not False:
            raise CooldownContextCandidateError(
                "COOLDOWN_CONTEXT_SELECTION_AUTHORITY_INVALID"
            )
    for field in (
        "cooldown_source_digest",
        "stability_source_digest",
    ):
        _require_sha256(_string(selection.get(field), field), field)

    selected = selection.get("selected_candidate")
    if selected is None:
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_SELECTION_HAS_NO_CANDIDATE"
        )
    candidate = _mapping(selected, "selected_candidate")
    if candidate.get("stable_on_validation") is not True:
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_SELECTED_CANDIDATE_NOT_STABLE"
        )
    dimensions = tuple(
        _string(item, "dimension")
        for item in _sequence(candidate.get("dimensions"), "dimensions")
    )
    values = tuple(
        _string(item, "value")
        for item in _sequence(candidate.get("values"), "values")
    )
    if not dimensions or len(dimensions) != len(values):
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_SELECTED_CONTEXT_INVALID"
        )
    if "relaxation_window_ms" not in dimensions:
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_RELAXATION_WINDOW_REQUIRED"
        )
    if "lead_strategy" not in dimensions:
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_LEAD_STRATEGY_REQUIRED"
        )
    if dimensions == ("direction",):
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_DIRECTION_ONLY_FORBIDDEN"
        )
    return candidate


@dataclass(frozen=True, slots=True)
class CooldownContextCandidateFreeze:
    source_record_id: str
    cooldown_source_digest: str
    stability_source_digest: str
    source_max_timestamp_ms: int
    source_paper_run_id: int
    source_paper_run_attempt: int
    source_paper_head_sha: str
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    relaxation_window_ms: int
    lead_strategy: str
    discovery_rows: int
    discovery_markets: int
    discovery_positive_share: Decimal
    discovery_total_pnl: Decimal
    discovery_mean_return: Decimal
    validation_rows: int
    validation_markets: int
    validation_positive_share: Decimal
    validation_total_pnl: Decimal
    validation_mean_return: Decimal
    validation_leave_one_option_min_pnl: Decimal
    validation_leave_one_market_min_pnl: Decimal
    validation_block_rows: tuple[int, ...]
    validation_block_positive_shares: tuple[Decimal, ...]
    validation_block_pnl: tuple[Decimal, ...]
    frozen_at_ms: int
    prospective_not_before_ms: int
    selection_policy: str = COOLDOWN_CONTEXT_SELECTION_POLICY
    candidate_kind: str = COOLDOWN_CONTEXT_CANDIDATE_KIND
    prospective_only: bool = True
    paper_only: bool = True
    research_only: bool = True
    changes_strategy: bool = False
    changes_risk_limits: bool = False
    promotion_authority: bool = False
    execution_authority: bool = False
    schema_version: int = COOLDOWN_CONTEXT_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, field in (
            (self.source_record_id, "source_record_id"),
            (self.cooldown_source_digest, "cooldown_source_digest"),
            (self.stability_source_digest, "stability_source_digest"),
        ):
            _require_sha256(value, field)
        _require_commit_sha(
            self.source_paper_head_sha,
            "source_paper_head_sha",
        )
        if self.source_paper_run_id <= 0 or self.source_paper_run_attempt <= 0:
            raise ValueError("source paper run identity must be positive")
        if not self.dimensions or len(self.dimensions) != len(self.values):
            raise ValueError("frozen context must be non-empty and aligned")
        if "relaxation_window_ms" not in self.dimensions:
            raise ValueError("frozen context must retain relaxation window")
        if "lead_strategy" not in self.dimensions:
            raise ValueError("frozen context must retain lead strategy")
        if self.relaxation_window_ms <= 0:
            raise ValueError("relaxation_window_ms must be positive")
        context = dict(zip(self.dimensions, self.values, strict=True))
        if context["relaxation_window_ms"] != str(
            self.relaxation_window_ms
        ):
            raise ValueError("frozen relaxation window does not match context")
        if context["lead_strategy"] != self.lead_strategy:
            raise ValueError("frozen lead strategy does not match context")
        if self.discovery_rows <= 0 or self.validation_rows <= 0:
            raise ValueError("frozen candidate row counts must be positive")
        if self.discovery_markets <= 0 or self.validation_markets <= 0:
            raise ValueError("frozen candidate market counts must be positive")
        for value, field in (
            (self.discovery_positive_share, "discovery_positive_share"),
            (self.validation_positive_share, "validation_positive_share"),
        ):
            if not ZERO < value <= Decimal("1"):
                raise ValueError(f"{field} must be in (0, 1]")
        for value, field in (
            (self.discovery_total_pnl, "discovery_total_pnl"),
            (self.discovery_mean_return, "discovery_mean_return"),
            (self.validation_total_pnl, "validation_total_pnl"),
            (self.validation_mean_return, "validation_mean_return"),
            (
                self.validation_leave_one_option_min_pnl,
                "validation_leave_one_option_min_pnl",
            ),
            (
                self.validation_leave_one_market_min_pnl,
                "validation_leave_one_market_min_pnl",
            ),
        ):
            if value <= ZERO:
                raise ValueError(f"{field} must be positive")
        if (
            not self.validation_block_rows
            or len(self.validation_block_rows)
            != len(self.validation_block_positive_shares)
            or len(self.validation_block_rows) != len(self.validation_block_pnl)
        ):
            raise ValueError("frozen validation block evidence is invalid")
        if any(value <= 0 for value in self.validation_block_rows):
            raise ValueError("frozen validation block rows must be positive")
        if any(
            not ZERO < value <= Decimal("1")
            for value in self.validation_block_positive_shares
        ):
            raise ValueError(
                "frozen validation block positive shares must be in (0, 1]"
            )
        if any(value <= ZERO for value in self.validation_block_pnl):
            raise ValueError("frozen validation block pnl must be positive")
        if self.frozen_at_ms < self.source_max_timestamp_ms:
            raise ValueError("freeze must not precede source evidence")
        if self.prospective_not_before_ms != (
            self.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ):
            raise ValueError(
                "prospective boundary must equal freeze plus embargo"
            )
        if self.selection_policy != COOLDOWN_CONTEXT_SELECTION_POLICY:
            raise ValueError("unsupported cooldown selection policy")
        if self.candidate_kind != COOLDOWN_CONTEXT_CANDIDATE_KIND:
            raise ValueError("unsupported cooldown candidate kind")
        if not self.prospective_only or not self.paper_only:
            raise ValueError("cooldown freeze must remain prospective paper")
        if not self.research_only:
            raise ValueError("cooldown freeze must remain research only")
        if self.changes_strategy or self.changes_risk_limits:
            raise ValueError("cooldown freeze cannot change active behavior")
        if self.promotion_authority or self.execution_authority:
            raise ValueError("cooldown freeze cannot grant authority")
        if self.schema_version != COOLDOWN_CONTEXT_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported cooldown candidate schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_record_id": self.source_record_id,
            "cooldown_source_digest": self.cooldown_source_digest,
            "stability_source_digest": self.stability_source_digest,
            "source_max_timestamp_ms": self.source_max_timestamp_ms,
            "source_paper_run_id": self.source_paper_run_id,
            "source_paper_run_attempt": self.source_paper_run_attempt,
            "source_paper_head_sha": self.source_paper_head_sha,
            "dimensions": self.dimensions,
            "values": self.values,
            "relaxation_window_ms": self.relaxation_window_ms,
            "lead_strategy": self.lead_strategy,
            "discovery_rows": self.discovery_rows,
            "discovery_markets": self.discovery_markets,
            "discovery_positive_share": str(self.discovery_positive_share),
            "discovery_total_pnl": str(self.discovery_total_pnl),
            "discovery_mean_return": str(self.discovery_mean_return),
            "validation_rows": self.validation_rows,
            "validation_markets": self.validation_markets,
            "validation_positive_share": str(
                self.validation_positive_share
            ),
            "validation_total_pnl": str(self.validation_total_pnl),
            "validation_mean_return": str(self.validation_mean_return),
            "validation_leave_one_option_min_pnl": str(
                self.validation_leave_one_option_min_pnl
            ),
            "validation_leave_one_market_min_pnl": str(
                self.validation_leave_one_market_min_pnl
            ),
            "validation_block_rows": self.validation_block_rows,
            "validation_block_positive_shares": tuple(
                str(value)
                for value in self.validation_block_positive_shares
            ),
            "validation_block_pnl": tuple(
                str(value) for value in self.validation_block_pnl
            ),
            "frozen_at_ms": self.frozen_at_ms,
            "prospective_not_before_ms": self.prospective_not_before_ms,
            "selection_policy": self.selection_policy,
            "candidate_kind": self.candidate_kind,
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


def build_cooldown_context_candidate_freeze(
    selection_record: dict[str, object],
    *,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> CooldownContextCandidateFreeze:
    candidate = _validate_selection(selection_record)
    if frozen_at_ms < 0:
        raise ValueError("frozen_at_ms must be non-negative")

    dimensions = tuple(
        _string(item, "dimension")
        for item in _sequence(candidate.get("dimensions"), "dimensions")
    )
    values = tuple(
        _string(item, "value")
        for item in _sequence(candidate.get("values"), "values")
    )
    context = dict(zip(dimensions, values, strict=True))
    block_rows = tuple(
        _integer(item, "validation_block_row")
        for item in _sequence(
            candidate.get("validation_block_rows"),
            "validation_block_rows",
        )
    )
    block_shares = tuple(
        _decimal(item, "validation_block_positive_share")
        for item in _sequence(
            candidate.get("validation_block_positive_shares"),
            "validation_block_positive_shares",
        )
    )
    block_pnl = tuple(
        _decimal(item, "validation_block_pnl")
        for item in _sequence(
            candidate.get("validation_block_pnl"),
            "validation_block_pnl",
        )
    )
    return CooldownContextCandidateFreeze(
        source_record_id=_string(
            selection_record.get("source_record_id"),
            "source_record_id",
        ),
        cooldown_source_digest=_string(
            selection_record.get("cooldown_source_digest"),
            "cooldown_source_digest",
        ),
        stability_source_digest=_string(
            selection_record.get("stability_source_digest"),
            "stability_source_digest",
        ),
        source_max_timestamp_ms=_integer(
            selection_record.get("source_max_timestamp_ms"),
            "source_max_timestamp_ms",
        ),
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_paper_head_sha=source_paper_head_sha,
        dimensions=dimensions,
        values=values,
        relaxation_window_ms=int(context["relaxation_window_ms"]),
        lead_strategy=context["lead_strategy"],
        discovery_rows=_integer(
            candidate.get("discovery_rows"),
            "discovery_rows",
        ),
        discovery_markets=_integer(
            candidate.get("discovery_markets"),
            "discovery_markets",
        ),
        discovery_positive_share=_decimal(
            candidate.get("discovery_positive_share"),
            "discovery_positive_share",
        ),
        discovery_total_pnl=_decimal(
            candidate.get("discovery_total_pnl"),
            "discovery_total_pnl",
        ),
        discovery_mean_return=_decimal(
            candidate.get("discovery_mean_return"),
            "discovery_mean_return",
        ),
        validation_rows=_integer(
            candidate.get("validation_rows"),
            "validation_rows",
        ),
        validation_markets=_integer(
            candidate.get("validation_markets"),
            "validation_markets",
        ),
        validation_positive_share=_decimal(
            candidate.get("validation_positive_share"),
            "validation_positive_share",
        ),
        validation_total_pnl=_decimal(
            candidate.get("validation_total_pnl"),
            "validation_total_pnl",
        ),
        validation_mean_return=_decimal(
            candidate.get("validation_mean_return"),
            "validation_mean_return",
        ),
        validation_leave_one_option_min_pnl=_decimal(
            candidate.get("validation_leave_one_option_min_pnl"),
            "validation_leave_one_option_min_pnl",
        ),
        validation_leave_one_market_min_pnl=_decimal(
            candidate.get("validation_leave_one_market_min_pnl"),
            "validation_leave_one_market_min_pnl",
        ),
        validation_block_rows=block_rows,
        validation_block_positive_shares=block_shares,
        validation_block_pnl=block_pnl,
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def verify_cooldown_context_candidate_freeze(
    path: str | Path,
) -> CooldownContextCandidateFreeze:
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CooldownContextCandidateError(
            "cooldown candidate freeze is invalid"
        ) from exc
    payload = _mapping(raw, "cooldown candidate freeze")
    candidate_id = _string(payload.pop("candidate_id", None), "candidate_id")
    _require_sha256(candidate_id, "candidate_id")
    try:
        freeze = CooldownContextCandidateFreeze(
            source_record_id=_string(
                payload.get("source_record_id"),
                "source_record_id",
            ),
            cooldown_source_digest=_string(
                payload.get("cooldown_source_digest"),
                "cooldown_source_digest",
            ),
            stability_source_digest=_string(
                payload.get("stability_source_digest"),
                "stability_source_digest",
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
                for item in _sequence(
                    payload.get("dimensions"),
                    "dimensions",
                )
            ),
            values=tuple(
                _string(item, "value")
                for item in _sequence(payload.get("values"), "values")
            ),
            relaxation_window_ms=_integer(
                payload.get("relaxation_window_ms"),
                "relaxation_window_ms",
            ),
            lead_strategy=_string(
                payload.get("lead_strategy"),
                "lead_strategy",
            ),
            discovery_rows=_integer(
                payload.get("discovery_rows"),
                "discovery_rows",
            ),
            discovery_markets=_integer(
                payload.get("discovery_markets"),
                "discovery_markets",
            ),
            discovery_positive_share=_decimal(
                payload.get("discovery_positive_share"),
                "discovery_positive_share",
            ),
            discovery_total_pnl=_decimal(
                payload.get("discovery_total_pnl"),
                "discovery_total_pnl",
            ),
            discovery_mean_return=_decimal(
                payload.get("discovery_mean_return"),
                "discovery_mean_return",
            ),
            validation_rows=_integer(
                payload.get("validation_rows"),
                "validation_rows",
            ),
            validation_markets=_integer(
                payload.get("validation_markets"),
                "validation_markets",
            ),
            validation_positive_share=_decimal(
                payload.get("validation_positive_share"),
                "validation_positive_share",
            ),
            validation_total_pnl=_decimal(
                payload.get("validation_total_pnl"),
                "validation_total_pnl",
            ),
            validation_mean_return=_decimal(
                payload.get("validation_mean_return"),
                "validation_mean_return",
            ),
            validation_leave_one_option_min_pnl=_decimal(
                payload.get("validation_leave_one_option_min_pnl"),
                "validation_leave_one_option_min_pnl",
            ),
            validation_leave_one_market_min_pnl=_decimal(
                payload.get("validation_leave_one_market_min_pnl"),
                "validation_leave_one_market_min_pnl",
            ),
            validation_block_rows=tuple(
                _integer(item, "validation_block_row")
                for item in _sequence(
                    payload.get("validation_block_rows"),
                    "validation_block_rows",
                )
            ),
            validation_block_positive_shares=tuple(
                _decimal(item, "validation_block_positive_share")
                for item in _sequence(
                    payload.get("validation_block_positive_shares"),
                    "validation_block_positive_shares",
                )
            ),
            validation_block_pnl=tuple(
                _decimal(item, "validation_block_pnl")
                for item in _sequence(
                    payload.get("validation_block_pnl"),
                    "validation_block_pnl",
                )
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
            candidate_kind=_string(
                payload.get("candidate_kind"),
                "candidate_kind",
            ),
            prospective_only=_boolean(
                payload.get("prospective_only"),
                "prospective_only",
            ),
            paper_only=_boolean(payload.get("paper_only"), "paper_only"),
            research_only=_boolean(
                payload.get("research_only"),
                "research_only",
            ),
            changes_strategy=_boolean(
                payload.get("changes_strategy"),
                "changes_strategy",
            ),
            changes_risk_limits=_boolean(
                payload.get("changes_risk_limits"),
                "changes_risk_limits",
            ),
            promotion_authority=_boolean(
                payload.get("promotion_authority"),
                "promotion_authority",
            ),
            execution_authority=_boolean(
                payload.get("execution_authority"),
                "execution_authority",
            ),
            schema_version=_integer(
                payload.get("schema_version"),
                "schema_version",
            ),
        )
    except ValueError as exc:
        raise CooldownContextCandidateError(str(exc)) from exc
    if freeze.candidate_id != candidate_id:
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_CANDIDATE_ID_MISMATCH"
        )
    if _canonical_json(payload) != _canonical_json(freeze.identity_payload()):
        raise CooldownContextCandidateError(
            "COOLDOWN_CONTEXT_CANDIDATE_NON_CANONICAL"
        )
    return freeze


def write_cooldown_context_candidate_freeze(
    selection_record: dict[str, object],
    *,
    output_path: str | Path,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> tuple[CooldownContextCandidateFreeze, bool]:
    target = Path(output_path)
    if target.exists():
        return verify_cooldown_context_candidate_freeze(target), False

    freeze = build_cooldown_context_candidate_freeze(
        selection_record,
        frozen_at_ms=frozen_at_ms,
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_paper_head_sha=source_paper_head_sha,
    )
    encoded = (_canonical_json(freeze.to_dict()) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            return verify_cooldown_context_candidate_freeze(target), False
    finally:
        temporary.unlink(missing_ok=True)
    return freeze, True
