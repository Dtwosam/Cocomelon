from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)

NO_TRADE_CONTEXT_CANDIDATE_SCHEMA_VERSION = 1
NO_TRADE_CONTEXT_SELECTION_SCHEMA_VERSION = 1
NO_TRADE_CONTEXT_SELECTION_POLICY: Final = (
    "max_validation_lift_then_validation_share_then_support_v1"
)
NO_TRADE_CONTEXT_CANDIDATE_KIND: Final = (
    "continuous_paper_no_trade_context_shadow"
)


class NoTradeContextCandidateError(RuntimeError):
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
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise NoTradeContextCandidateError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise NoTradeContextCandidateError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NoTradeContextCandidateError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise NoTradeContextCandidateError(
            f"{field} must be a non-negative integer"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise NoTradeContextCandidateError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise NoTradeContextCandidateError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise NoTradeContextCandidateError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise NoTradeContextCandidateError(f"{field} must be finite")
    return result


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise NoTradeContextCandidateError(
            f"{field} must be a lowercase SHA-256"
        )


def _require_artifact_digest(value: str, field: str) -> None:
    if not value.startswith("sha256:"):
        raise NoTradeContextCandidateError(f"{field} must be a SHA-256 digest")
    _require_sha256(value.removeprefix("sha256:"), field)


def _require_commit_sha(value: str, field: str) -> None:
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise NoTradeContextCandidateError(
            f"{field} must be a lowercase git SHA"
        )


def _selection_payload(
    raw: dict[str, object],
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    source_id = _string(raw.get("source_record_id"), "source_record_id")
    _require_sha256(source_id, "source_record_id")
    identity = {key: value for key, value in raw.items() if key != "source_record_id"}
    if _sha256_json(identity) != source_id:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_SELECTION_ID_MISMATCH"
        )
    if _integer(raw.get("schema_version"), "schema_version") != 1:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_SELECTION_SCHEMA_INVALID"
        )
    if (
        _string(raw.get("selection_policy"), "selection_policy")
        != NO_TRADE_CONTEXT_SELECTION_POLICY
    ):
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_SELECTION_POLICY_INVALID"
        )
    if _integer(
        raw.get("forward_opportunity_schema_version"),
        "forward_opportunity_schema_version",
    ) != 2:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_FORWARD_SCHEMA_INVALID"
        )
    if _integer(
        raw.get("context_stability_schema_version"),
        "context_stability_schema_version",
    ) != 3:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_STABILITY_SCHEMA_INVALID"
        )
    if (
        _string(
            raw.get("directional_candidate_source"),
            "directional_candidate_source",
        )
        != "strategy_abstained_only"
    ):
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_SELECTION_SOURCE_INVALID"
        )
    for field in (
        "market_aware",
        "validation_block_consistency_required",
        "research_only",
    ):
        if _boolean(raw.get(field), field) is not True:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_SELECTION_AUTHORITY_INVALID"
            )
    for field in ("promotion_eligible", "execution_ready"):
        if _boolean(raw.get(field), field) is not False:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_SELECTION_AUTHORITY_INVALID"
            )

    for field in ("source_decision_state_digest", "source_feature_state_digest"):
        _require_sha256(_string(raw.get(field), field), field)
    for field in (
        "source_evidence_artifact_digest",
        "source_upstream_artifact_digest",
    ):
        _require_artifact_digest(_string(raw.get(field), field), field)
    for field in ("source_evidence_head_sha", "source_upstream_head_sha"):
        _require_commit_sha(_string(raw.get(field), field)

        )
    for field in (
        "source_evidence_run_id",
        "source_evidence_run_attempt",
        "source_upstream_run_id",
        "source_upstream_run_attempt",
        "source_forward_as_of_ms",
        "source_max_decision_timestamp_ms",
    ):
        _integer(raw.get(field), field)

    candidates_raw = _sequence(
        raw.get("validated_candidates"),
        "validated_candidates",
    )
    expected_count = _integer(
        raw.get("validated_candidate_count"),
        "validated_candidate_count",
    )
    if expected_count != len(candidates_raw) or expected_count <= 0:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_VALIDATED_CANDIDATE_COUNT_INVALID"
        )
    candidates: list[dict[str, object]] = []
    for raw_candidate in candidates_raw:
        candidate = _mapping(raw_candidate, "validated candidate")
        if _boolean(
            candidate.get("stable_on_validation"),
            "stable_on_validation",
        ) is not True:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_NOT_STABLE"
            )
        if _boolean(
            candidate.get("stable_across_validation_blocks"),
            "stable_across_validation_blocks",
        ) is not True:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_BLOCKS_UNSTABLE"
            )
        if _boolean(
            candidate.get("strategy_authority"),
            "strategy_authority",
        ) is not False:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_AUTHORITY_INVALID"
            )
        direction = _string(
            candidate.get("dominant_direction"),
            "dominant_direction",
        )
        if direction not in {Direction.LONG.value, Direction.SHORT.value}:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_DIRECTION_INVALID"
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
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_CONTEXT_INVALID"
            )
        _integer(candidate.get("horizon_ms"), "horizon_ms")
        if _integer(candidate.get("threshold_bps"), "threshold_bps") <= 0:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_THRESHOLD_INVALID"
            )
        for field in (
            "discovery_direction_share",
            "validation_same_direction_share",
            "validation_baseline_direction_share",
            "validation_lift_vs_baseline",
        ):
            _decimal(candidate.get(field), field)
        _integer(
            candidate.get("discovery_material_outcomes"),
            "discovery_material_outcomes",
        )
        _integer(
            candidate.get("validation_material_outcomes"),
            "validation_material_outcomes",
        )
        block_outcomes = _sequence(
            candidate.get("validation_block_outcomes"),
            "validation_block_outcomes",
        )
        block_shares = _sequence(
            candidate.get("validation_block_direction_shares"),
            "validation_block_direction_shares",
        )
        if not block_outcomes or len(block_outcomes) != len(block_shares):
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_BLOCKS_INVALID"
            )
        for value in block_outcomes:
            _integer(value, "validation_block_outcome")
        for value in block_shares:
            _decimal(value, "validation_block_direction_share")
        candidates.append(candidate)
    return raw, tuple(candidates)


def _candidate_sort_key(candidate: dict[str, object]) -> tuple[object, ...]:
    dimensions = tuple(
        _string(item, "dimension")
        for item in _sequence(candidate.get("dimensions"), "dimensions")
    )
    values = tuple(
        _string(item, "value")
        for item in _sequence(candidate.get("values"), "values")
    )
    return (
        -_decimal(
            candidate.get("validation_lift_vs_baseline"),
            "validation_lift_vs_baseline",
        ),
        -_decimal(
            candidate.get("validation_same_direction_share"),
            "validation_same_direction_share",
        ),
        -_integer(
            candidate.get("validation_material_outcomes"),
            "validation_material_outcomes",
        ),
        -_integer(
            candidate.get("discovery_material_outcomes"),
            "discovery_material_outcomes",
        ),
        _integer(candidate.get("horizon_ms"), "horizon_ms"),
        _integer(candidate.get("threshold_bps"), "threshold_bps"),
        dimensions,
        values,
        _string(candidate.get("dominant_direction"), "dominant_direction"),
    )


@dataclass(frozen=True, slots=True)
class NoTradeContextCandidateFreeze:
    source_record_id: str
    source_evidence_artifact_digest: str
    source_evidence_run_id: int
    source_evidence_run_attempt: int
    source_evidence_head_sha: str
    source_forward_as_of_ms: int
    source_max_decision_timestamp_ms: int
    source_decision_state_digest: str
    source_feature_state_digest: str
    source_upstream_run_id: int
    source_upstream_run_attempt: int
    source_upstream_head_sha: str
    source_upstream_artifact_digest: str
    horizon_ms: int
    threshold_bps: int
    dimensions: tuple[str, ...]
    values: tuple[str, ...]
    direction: Direction
    discovery_material_outcomes: int
    discovery_direction_share: Decimal
    validation_material_outcomes: int
    validation_same_direction_share: Decimal
    validation_baseline_direction_share: Decimal
    validation_lift_vs_baseline: Decimal
    validation_block_outcomes: tuple[int, ...]
    validation_block_direction_shares: tuple[Decimal, ...]
    frozen_at_ms: int
    prospective_not_before_ms: int
    selection_policy: str = NO_TRADE_CONTEXT_SELECTION_POLICY
    candidate_kind: str = NO_TRADE_CONTEXT_CANDIDATE_KIND
    prospective_only: bool = True
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    schema_version: int = NO_TRADE_CONTEXT_CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.source_record_id, "source_record_id")
        _require_artifact_digest(
            self.source_evidence_artifact_digest,
            "source_evidence_artifact_digest",
        )
        _require_commit_sha(self.source_evidence_head_sha, "source_evidence_head_sha")
        _require_sha256(
            self.source_decision_state_digest,
            "source_decision_state_digest",
        )
        _require_sha256(
            self.source_feature_state_digest,
            "source_feature_state_digest",
        )
        _require_commit_sha(self.source_upstream_head_sha, "source_upstream_head_sha")
        _require_artifact_digest(
            self.source_upstream_artifact_digest,
            "source_upstream_artifact_digest",
        )
        if self.horizon_ms <= 0 or self.threshold_bps <= 0:
            raise ValueError("candidate horizon and threshold must be positive")
        if not self.dimensions or len(self.dimensions) != len(self.values):
            raise ValueError("candidate context must be non-empty and aligned")
        if self.direction not in {Direction.LONG, Direction.SHORT}:
            raise ValueError("candidate direction must be LONG or SHORT")
        if self.frozen_at_ms < self.source_forward_as_of_ms:
            raise ValueError("freeze must not precede source evidence")
        if self.prospective_not_before_ms != (
            self.frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ):
            raise ValueError("prospective boundary must equal freeze plus embargo")
        if self.selection_policy != NO_TRADE_CONTEXT_SELECTION_POLICY:
            raise ValueError("unsupported candidate selection policy")
        if self.candidate_kind != NO_TRADE_CONTEXT_CANDIDATE_KIND:
            raise ValueError("unsupported candidate kind")
        if not self.prospective_only or not self.paper_only or not self.research_only:
            raise ValueError("candidate freeze must remain prospective paper research")
        if self.promotion_eligible or self.execution_ready:
            raise ValueError("candidate freeze cannot authorize promotion or execution")
        if self.schema_version != NO_TRADE_CONTEXT_CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported candidate freeze schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "source_record_id": self.source_record_id,
            "source_evidence_artifact_digest": self.source_evidence_artifact_digest,
            "source_evidence_run_id": self.source_evidence_run_id,
            "source_evidence_run_attempt": self.source_evidence_run_attempt,
            "source_evidence_head_sha": self.source_evidence_head_sha,
            "source_forward_as_of_ms": self.source_forward_as_of_ms,
            "source_max_decision_timestamp_ms": self.source_max_decision_timestamp_ms,
            "source_decision_state_digest": self.source_decision_state_digest,
            "source_feature_state_digest": self.source_feature_state_digest,
            "source_upstream_run_id": self.source_upstream_run_id,
            "source_upstream_run_attempt": self.source_upstream_run_attempt,
            "source_upstream_head_sha": self.source_upstream_head_sha,
            "source_upstream_artifact_digest": self.source_upstream_artifact_digest,
            "horizon_ms": self.horizon_ms,
            "threshold_bps": self.threshold_bps,
            "dimensions": self.dimensions,
            "values": self.values,
            "direction": self.direction.value,
            "discovery_material_outcomes": self.discovery_material_outcomes,
            "discovery_direction_share": str(self.discovery_direction_share),
            "validation_material_outcomes": self.validation_material_outcomes,
            "validation_same_direction_share": str(
                self.validation_same_direction_share
            ),
            "validation_baseline_direction_share": str(
                self.validation_baseline_direction_share
            ),
            "validation_lift_vs_baseline": str(self.validation_lift_vs_baseline),
            "validation_block_outcomes": self.validation_block_outcomes,
            "validation_block_direction_shares": tuple(
                str(value) for value in self.validation_block_direction_shares
            ),
            "frozen_at_ms": self.frozen_at_ms,
            "prospective_not_before_ms": self.prospective_not_before_ms,
            "selection_policy": self.selection_policy,
            "candidate_kind": self.candidate_kind,
            "prospective_only": self.prospective_only,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "schema_version": self.schema_version,
        }

    @property
    def candidate_id(self) -> str:
        return _sha256_json(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "candidate_id": self.candidate_id}


def build_no_trade_context_candidate_freeze(
    selection_record: dict[str, object],
    *,
    frozen_at_ms: int,
) -> NoTradeContextCandidateFreeze:
    raw, candidates = _selection_payload(selection_record)
    if frozen_at_ms < 0:
        raise ValueError("frozen_at_ms must be non-negative")
    selected = sorted(candidates, key=_candidate_sort_key)[0]
    dimensions = tuple(
        _string(item, "dimension")
        for item in _sequence(selected.get("dimensions"), "dimensions")
    )
    values = tuple(
        _string(item, "value")
        for item in _sequence(selected.get("values"), "values")
    )
    block_outcomes = tuple(
        _integer(item, "validation_block_outcome")
        for item in _sequence(
            selected.get("validation_block_outcomes"),
            "validation_block_outcomes",
        )
    )
    block_shares = tuple(
        _decimal(item, "validation_block_direction_share")
        for item in _sequence(
            selected.get("validation_block_direction_shares"),
            "validation_block_direction_shares",
        )
    )
    return NoTradeContextCandidateFreeze(
        source_record_id=_string(raw.get("source_record_id"), "source_record_id"),
        source_evidence_artifact_digest=_string(
            raw.get("source_evidence_artifact_digest"),
            "source_evidence_artifact_digest",
        ),
        source_evidence_run_id=_integer(
            raw.get("source_evidence_run_id"),
            "source_evidence_run_id",
        ),
        source_evidence_run_attempt=_integer(
            raw.get("source_evidence_run_attempt"),
            "source_evidence_run_attempt",
        ),
        source_evidence_head_sha=_string(
            raw.get("source_evidence_head_sha"),
            "source_evidence_head_sha",
        ),
        source_forward_as_of_ms=_integer(
            raw.get("source_forward_as_of_ms"),
            "source_forward_as_of_ms",
        ),
        source_max_decision_timestamp_ms=_integer(
            raw.get("source_max_decision_timestamp_ms"),
            "source_max_decision_timestamp_ms",
        ),
        source_decision_state_digest=_string(
            raw.get("source_decision_state_digest"),
            "source_decision_state_digest",
        ),
        source_feature_state_digest=_string(
            raw.get("source_feature_state_digest"),
            "source_feature_state_digest",
        ),
        source_upstream_run_id=_integer(
            raw.get("source_upstream_run_id"),
            "source_upstream_run_id",
        ),
        source_upstream_run_attempt=_integer(
            raw.get("source_upstream_run_attempt"),
            "source_upstream_run_attempt",
        ),
        source_upstream_head_sha=_string(
            raw.get("source_upstream_head_sha"),
            "source_upstream_head_sha",
        ),
        source_upstream_artifact_digest=_string(
            raw.get("source_upstream_artifact_digest"),
            "source_upstream_artifact_digest",
        ),
        horizon_ms=_integer(selected.get("horizon_ms"), "horizon_ms"),
        threshold_bps=_integer(selected.get("threshold_bps"), "threshold_bps"),
        dimensions=dimensions,
        values=values,
        direction=Direction(
            _string(selected.get("dominant_direction"), "dominant_direction")
        ),
        discovery_material_outcomes=_integer(
            selected.get("discovery_material_outcomes"),
            "discovery_material_outcomes",
        ),
        discovery_direction_share=_decimal(
            selected.get("discovery_direction_share"),
            "discovery_direction_share",
        ),
        validation_material_outcomes=_integer(
            selected.get("validation_material_outcomes"),
            "validation_material_outcomes",
        ),
        validation_same_direction_share=_decimal(
            selected.get("validation_same_direction_share"),
            "validation_same_direction_share",
        ),
        validation_baseline_direction_share=_decimal(
            selected.get("validation_baseline_direction_share"),
            "validation_baseline_direction_share",
        ),
        validation_lift_vs_baseline=_decimal(
            selected.get("validation_lift_vs_baseline"),
            "validation_lift_vs_baseline",
        ),
        validation_block_outcomes=block_outcomes,
        validation_block_direction_shares=block_shares,
        frozen_at_ms=frozen_at_ms,
        prospective_not_before_ms=(
            frozen_at_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ),
    )


def write_no_trade_context_candidate_freeze(
    path: Path,
    freeze: NoTradeContextCandidateFreeze,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (_canonical_json(freeze.to_dict()) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise NoTradeContextCandidateError(
                "NO_TRADE_CONTEXT_CANDIDATE_FREEZE_CONFLICT"
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


def _freeze_from_payload(raw: dict[str, object]) -> NoTradeContextCandidateFreeze:
    try:
        freeze = NoTradeContextCandidateFreeze(
            source_record_id=_string(raw.get("source_record_id"), "source_record_id"),
            source_evidence_artifact_digest=_string(
                raw.get("source_evidence_artifact_digest"),
                "source_evidence_artifact_digest",
            ),
            source_evidence_run_id=_integer(
                raw.get("source_evidence_run_id"),
                "source_evidence_run_id",
            ),
            source_evidence_run_attempt=_integer(
                raw.get("source_evidence_run_attempt"),
                "source_evidence_run_attempt",
            ),
            source_evidence_head_sha=_string(
                raw.get("source_evidence_head_sha"),
                "source_evidence_head_sha",
            ),
            source_forward_as_of_ms=_integer(
                raw.get("source_forward_as_of_ms"),
                "source_forward_as_of_ms",
            ),
            source_max_decision_timestamp_ms=_integer(
                raw.get("source_max_decision_timestamp_ms"),
                "source_max_decision_timestamp_ms",
            ),
            source_decision_state_digest=_string(
                raw.get("source_decision_state_digest"),
                "source_decision_state_digest",
            ),
            source_feature_state_digest=_string(
                raw.get("source_feature_state_digest"),
                "source_feature_state_digest",
            ),
            source_upstream_run_id=_integer(
                raw.get("source_upstream_run_id"),
                "source_upstream_run_id",
            ),
            source_upstream_run_attempt=_integer(
                raw.get("source_upstream_run_attempt"),
                "source_upstream_run_attempt",
            ),
            source_upstream_head_sha=_string(
                raw.get("source_upstream_head_sha"),
                "source_upstream_head_sha",
            ),
            source_upstream_artifact_digest=_string(
                raw.get("source_upstream_artifact_digest"),
                "source_upstream_artifact_digest",
            ),
            horizon_ms=_integer(raw.get("horizon_ms"), "horizon_ms"),
            threshold_bps=_integer(raw.get("threshold_bps"), "threshold_bps"),
            dimensions=tuple(
                _string(item, "dimension")
                for item in _sequence(raw.get("dimensions"), "dimensions")
            ),
            values=tuple(
                _string(item, "value")
                for item in _sequence(raw.get("values"), "values")
            ),
            direction=Direction(_string(raw.get("direction"), "direction")),
            discovery_material_outcomes=_integer(
                raw.get("discovery_material_outcomes"),
                "discovery_material_outcomes",
            ),
            discovery_direction_share=_decimal(
                raw.get("discovery_direction_share"),
                "discovery_direction_share",
            ),
            validation_material_outcomes=_integer(
                raw.get("validation_material_outcomes"),
                "validation_material_outcomes",
            ),
            validation_same_direction_share=_decimal(
                raw.get("validation_same_direction_share"),
                "validation_same_direction_share",
            ),
            validation_baseline_direction_share=_decimal(
                raw.get("validation_baseline_direction_share"),
                "validation_baseline_direction_share",
            ),
            validation_lift_vs_baseline=_decimal(
                raw.get("validation_lift_vs_baseline"),
                "validation_lift_vs_baseline",
            ),
            validation_block_outcomes=tuple(
                _integer(item, "validation_block_outcome")
                for item in _sequence(
                    raw.get("validation_block_outcomes"),
                    "validation_block_outcomes",
                )
            ),
            validation_block_direction_shares=tuple(
                _decimal(item, "validation_block_direction_share")
                for item in _sequence(
                    raw.get("validation_block_direction_shares"),
                    "validation_block_direction_shares",
                )
            ),
            frozen_at_ms=_integer(raw.get("frozen_at_ms"), "frozen_at_ms"),
            prospective_not_before_ms=_integer(
                raw.get("prospective_not_before_ms"),
                "prospective_not_before_ms",
            ),
            selection_policy=_string(
                raw.get("selection_policy"),
                "selection_policy",
            ),
            candidate_kind=_string(raw.get("candidate_kind"), "candidate_kind"),
            prospective_only=_boolean(
                raw.get("prospective_only"),
                "prospective_only",
            ),
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
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_CANDIDATE_FREEZE_INVALID"
        ) from exc
    candidate_id = _string(raw.get("candidate_id"), "candidate_id")
    if candidate_id != freeze.candidate_id:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_CANDIDATE_ID_MISMATCH"
        )
    return freeze


def verify_no_trade_context_candidate_freeze(
    freeze_path: Path,
    *,
    selection_record_path: Path,
) -> NoTradeContextCandidateFreeze:
    try:
        selection_bytes = selection_record_path.read_bytes()
        freeze_bytes = freeze_path.read_bytes()
        selection_raw = _mapping(
            json.loads(selection_bytes),
            "selection record",
        )
        freeze_raw = _mapping(json.loads(freeze_bytes), "candidate freeze")
    except (OSError, json.JSONDecodeError) as exc:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_CANDIDATE_FILE_INVALID"
        ) from exc

    _selection_payload(selection_raw)
    if selection_bytes != (
        _canonical_json(selection_raw) + "\n"
    ).encode("utf-8"):
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_SELECTION_NON_CANONICAL"
        )

    freeze = _freeze_from_payload(freeze_raw)
    if freeze_bytes != (
        _canonical_json(freeze.to_dict()) + "\n"
    ).encode("utf-8"):
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_CANDIDATE_NON_CANONICAL"
        )
    expected = build_no_trade_context_candidate_freeze(
        selection_raw,
        frozen_at_ms=freeze.frozen_at_ms,
    )
    if expected != freeze:
        raise NoTradeContextCandidateError(
            "NO_TRADE_CONTEXT_CANDIDATE_SOURCE_MISMATCH"
        )
    return freeze
