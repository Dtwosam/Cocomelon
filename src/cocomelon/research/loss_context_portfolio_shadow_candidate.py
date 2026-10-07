from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)

LOSS_CONTEXT_PORTFOLIO_SHADOW_SCHEMA_VERSION: Final = 1
LOSS_CONTEXT_PORTFOLIO_SHADOW_KIND: Final = (
    "loss_context_portfolio_shadow_v1"
)


class LossContextPortfolioShadowCandidateError(RuntimeError):
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
        raise LossContextPortfolioShadowCandidateError(
            f"{field} must be an object"
        )
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise LossContextPortfolioShadowCandidateError(
            f"{field} must be an array"
        )
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LossContextPortfolioShadowCandidateError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LossContextPortfolioShadowCandidateError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LossContextPortfolioShadowCandidateError(
            f"{field} must be boolean"
        )
    return value


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise LossContextPortfolioShadowCandidateError(
            f"{field} must be a lowercase SHA-256"
        )


def _require_commit_sha(value: str, field: str) -> None:
    if len(value) != 40 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise LossContextPortfolioShadowCandidateError(
            f"{field} must be a lowercase git SHA"
        )


def _validate_composition(
    composition: dict[str, object],
) -> tuple[
    str,
    tuple[str, ...],
    tuple[str, ...],
    tuple[int, ...],
    int,
]:
    candidate_id = _string(
        composition.get("candidate_id"),
        "candidate_id",
    )
    _require_sha256(candidate_id, "candidate_id")
    if _boolean(composition.get("research_only"), "research_only") is not True:
        raise LossContextPortfolioShadowCandidateError(
            "portfolio composition must remain research only"
        )
    for field in (
        "changes_strategy",
        "changes_risk_limits",
        "changes_positions",
        "promotion_authority",
        "execution_authority",
        "horizon_selection_performed",
        "cross_horizon_economics_aggregated",
        "chronological_account_state_replayed",
        "portfolio_counterfactual_complete",
        "strategy_level_realized_pnl_claimed",
    ):
        if _boolean(composition.get(field), field) is not False:
            raise LossContextPortfolioShadowCandidateError(
                "portfolio composition authority or methodology drift"
            )
    for field in (
        "gate_open",
        "all_horizons_structurally_composable",
        "ready_for_chronological_portfolio_replay",
    ):
        if _boolean(composition.get(field), field) is not True:
            raise LossContextPortfolioShadowCandidateError(
                "portfolio composition is not shadow-freeze ready"
            )

    dimensions = tuple(
        _string(value, "dimension")
        for value in _sequence(
            composition.get("dimensions"),
            "dimensions",
        )
    )
    values = tuple(
        _string(value, "value")
        for value in _sequence(composition.get("values"), "values")
    )
    if not dimensions or len(dimensions) != len(values):
        raise LossContextPortfolioShadowCandidateError(
            "portfolio shadow context is invalid"
        )
    if "lead_strategy" not in dimensions or dimensions == ("direction",):
        raise LossContextPortfolioShadowCandidateError(
            "portfolio shadow must retain contextual strategy identity"
        )

    horizons = tuple(
        _integer(value, "horizon_ms")
        for value in _sequence(
            composition.get("horizons_ms"),
            "horizons_ms",
        )
    )
    if (
        not horizons
        or any(value <= 0 for value in horizons)
        or tuple(sorted(set(horizons))) != horizons
    ):
        raise LossContextPortfolioShadowCandidateError(
            "portfolio shadow horizons must be positive and ordered"
        )
    summaries = _mapping(
        composition.get("horizon_summaries"),
        "horizon_summaries",
    )
    if set(summaries) != {str(value) for value in horizons}:
        raise LossContextPortfolioShadowCandidateError(
            "portfolio shadow horizon summaries do not match horizon set"
        )
    for horizon in horizons:
        item = _mapping(
            summaries[str(horizon)],
            f"horizon {horizon}",
        )
        if (
            item.get("horizon_ms") != horizon
            or item.get("structurally_composable") is not True
            or item.get("chronological_account_state_replayed") is not False
            or item.get("portfolio_counterfactual_complete") is not False
            or item.get("strategy_level_realized_pnl_claimed") is not False
        ):
            raise LossContextPortfolioShadowCandidateError(
                "portfolio shadow horizon is not freeze eligible"
            )

    source_max_timestamp_ms = _integer(
        composition.get("source_max_timestamp_ms"),
        "source_max_timestamp_ms",
    )
    if source_max_timestamp_ms <= 0:
        raise LossContextPortfolioShadowCandidateError(
            "portfolio composition source boundary is missing"
        )
    return (
        candidate_id,
        dimensions,
        values,
        horizons,
        source_max_timestamp_ms,
    )


@dataclass(frozen=True, slots=True)
class LossContextPortfolioShadowFreeze:
    loss_context_candidate_id: str
    source_composition_digest: str
    source_max_timestamp_ms: int
    source_paper_run_id: int
    source_paper_run_attempt: int
    source_paper_head_sha: str
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    horizons_ms: tuple[int, ...]
    frozen_at_ms: int
    prospective_not_before_ms: int
    candidate_kind: str = LOSS_CONTEXT_PORTFOLIO_SHADOW_KIND
    shadow_only: bool = True
    prospective_only: bool = True
    paper_only: bool = True
    research_only: bool = True
    changes_strategy: bool = False
    changes_risk_limits: bool = False
    changes_positions: bool = False
    horizon_selection_performed: bool = False
    cross_horizon_economics_aggregated: bool = False
    promotion_authority: bool = False
    execution_authority: bool = False
    schema_version: int = LOSS_CONTEXT_PORTFOLIO_SHADOW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(
            self.loss_context_candidate_id,
            "loss_context_candidate_id",
        )
        _require_sha256(
            self.source_composition_digest,
            "source_composition_digest",
        )
        _require_commit_sha(
            self.source_paper_head_sha,
            "source_paper_head_sha",
        )
        if self.source_paper_run_id <= 0 or self.source_paper_run_attempt <= 0:
            raise ValueError("source paper run identity must be positive")
        if not self.dimensions or len(self.dimensions) != len(self.values):
            raise ValueError("portfolio shadow context must be aligned")
        if "lead_strategy" not in self.dimensions:
            raise ValueError("portfolio shadow must retain lead strategy")
        if (
            not self.horizons_ms
            or tuple(sorted(set(self.horizons_ms))) != self.horizons_ms
            or any(value <= 0 for value in self.horizons_ms)
        ):
            raise ValueError("portfolio shadow horizons must be positive and ordered")
        if self.frozen_at_ms < self.source_max_timestamp_ms:
            raise ValueError("shadow freeze must not precede source evidence")
        if self.prospective_not_before_ms != (
            self.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ):
            raise ValueError(
                "prospective boundary must equal freeze plus embargo"
            )
        if self.candidate_kind != LOSS_CONTEXT_PORTFOLIO_SHADOW_KIND:
            raise ValueError("unsupported portfolio shadow candidate kind")
        if not (
            self.shadow_only
            and self.prospective_only
            and self.paper_only
            and self.research_only
        ):
            raise ValueError("portfolio shadow must remain prospective research")
        if (
            self.changes_strategy
            or self.changes_risk_limits
            or self.changes_positions
            or self.horizon_selection_performed
            or self.cross_horizon_economics_aggregated
            or self.promotion_authority
            or self.execution_authority
        ):
            raise ValueError("portfolio shadow freeze cannot grant authority")
        if self.schema_version != LOSS_CONTEXT_PORTFOLIO_SHADOW_SCHEMA_VERSION:
            raise ValueError("unsupported portfolio shadow schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "loss_context_candidate_id": self.loss_context_candidate_id,
            "source_composition_digest": self.source_composition_digest,
            "source_max_timestamp_ms": self.source_max_timestamp_ms,
            "source_paper_run_id": self.source_paper_run_id,
            "source_paper_run_attempt": self.source_paper_run_attempt,
            "source_paper_head_sha": self.source_paper_head_sha,
            "dimensions": self.dimensions,
            "values": self.values,
            "horizons_ms": self.horizons_ms,
            "frozen_at_ms": self.frozen_at_ms,
            "prospective_not_before_ms": self.prospective_not_before_ms,
            "candidate_kind": self.candidate_kind,
            "shadow_only": self.shadow_only,
            "prospective_only": self.prospective_only,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "changes_strategy": self.changes_strategy,
            "changes_risk_limits": self.changes_risk_limits,
            "changes_positions": self.changes_positions,
            "horizon_selection_performed": self.horizon_selection_performed,
            "cross_horizon_economics_aggregated": (
                self.cross_horizon_economics_aggregated
            ),
            "promotion_authority": self.promotion_authority,
            "execution_authority": self.execution_authority,
            "schema_version": self.schema_version,
        }

    @property
    def candidate_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "candidate_id": self.candidate_id}


def build_loss_context_portfolio_shadow_freeze(
    composition: dict[str, object],
    *,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> LossContextPortfolioShadowFreeze:
    (
        loss_context_candidate_id,
        dimensions,
        values,
        horizons,
        source_max_timestamp_ms,
    ) = _validate_composition(composition)
    if frozen_at_ms < source_max_timestamp_ms:
        raise LossContextPortfolioShadowCandidateError(
            "portfolio shadow freeze predates source evidence"
        )
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id=loss_context_candidate_id,
        source_composition_digest=_sha256_json(composition),
        source_max_timestamp_ms=source_max_timestamp_ms,
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_paper_head_sha=source_paper_head_sha,
        dimensions=dimensions,
        values=values,
        horizons_ms=horizons,
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def _from_payload(
    payload: dict[str, object],
) -> LossContextPortfolioShadowFreeze:
    freeze = LossContextPortfolioShadowFreeze(
        loss_context_candidate_id=_string(
            payload.get("loss_context_candidate_id"),
            "loss_context_candidate_id",
        ),
        source_composition_digest=_string(
            payload.get("source_composition_digest"),
            "source_composition_digest",
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
            _string(value, "dimension")
            for value in _sequence(payload.get("dimensions"), "dimensions")
        ),
        values=tuple(
            _string(value, "value")
            for value in _sequence(payload.get("values"), "values")
        ),
        horizons_ms=tuple(
            _integer(value, "horizon_ms")
            for value in _sequence(payload.get("horizons_ms"), "horizons_ms")
        ),
        frozen_at_ms=_integer(
            payload.get("frozen_at_ms"),
            "frozen_at_ms",
        ),
        prospective_not_before_ms=_integer(
            payload.get("prospective_not_before_ms"),
            "prospective_not_before_ms",
        ),
        candidate_kind=_string(
            payload.get("candidate_kind"),
            "candidate_kind",
        ),
        shadow_only=_boolean(payload.get("shadow_only"), "shadow_only"),
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
        changes_positions=_boolean(
            payload.get("changes_positions"),
            "changes_positions",
        ),
        horizon_selection_performed=_boolean(
            payload.get("horizon_selection_performed"),
            "horizon_selection_performed",
        ),
        cross_horizon_economics_aggregated=_boolean(
            payload.get("cross_horizon_economics_aggregated"),
            "cross_horizon_economics_aggregated",
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
    candidate_id = _string(payload.get("candidate_id"), "candidate_id")
    _require_sha256(candidate_id, "candidate_id")
    if candidate_id != freeze.candidate_id:
        raise LossContextPortfolioShadowCandidateError(
            "portfolio shadow candidate id mismatch"
        )
    return freeze


def verify_loss_context_portfolio_shadow_freeze(
    path: str | Path,
) -> LossContextPortfolioShadowFreeze:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LossContextPortfolioShadowCandidateError(
            "portfolio shadow freeze is missing or invalid"
        ) from exc
    return _from_payload(_mapping(raw, "portfolio shadow freeze"))


def write_loss_context_portfolio_shadow_freeze(
    composition: dict[str, object],
    *,
    output_path: str | Path,
    frozen_at_ms: int,
    source_paper_run_id: int,
    source_paper_run_attempt: int,
    source_paper_head_sha: str,
) -> tuple[LossContextPortfolioShadowFreeze, bool]:
    path = Path(output_path)
    if path.exists():
        return verify_loss_context_portfolio_shadow_freeze(path), False

    freeze = build_loss_context_portfolio_shadow_freeze(
        composition,
        frozen_at_ms=frozen_at_ms,
        source_paper_run_id=source_paper_run_id,
        source_paper_run_attempt=source_paper_run_attempt,
        source_paper_head_sha=source_paper_head_sha,
    )
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
