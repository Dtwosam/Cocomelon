from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final, cast

from cocomelon.domain.strategy import Direction

ZERO: Final = Decimal("0")
BPS: Final = Decimal("10000")
FROZEN_NO_TRADE_SHADOW_SCHEMA_VERSION = 1
FROZEN_SOURCE_EVIDENCE_CLASS = "touched_development"
FROZEN_PROSPECTIVE_EVIDENCE_CLASS = "prospective_shadow"
FROZEN_VALIDATION_BLOCK_COUNT = 3
FROZEN_MIN_BLOCK_ROWS = 5
FROZEN_MIN_BLOCK_SHORT_SHARE = Decimal("0.55")
FROZEN_MIN_REVIEW_MATERIAL_OUTCOMES = 30
FROZEN_MIN_REVIEW_SHORT_SHARE = Decimal("0.60")


class FrozenNoTradeShadowError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 identity")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise FrozenNoTradeShadowError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise FrozenNoTradeShadowError(f"{field} must be an array")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise FrozenNoTradeShadowError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrozenNoTradeShadowError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise FrozenNoTradeShadowError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise FrozenNoTradeShadowError(
            f"{field} must be a decimal string"
        ) from exc
    if not result.is_finite():
        raise FrozenNoTradeShadowError(f"{field} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class FrozenNoTradeContextCandidate:
    candidate_id: str
    market: str
    volatility_regime: str
    direction: Direction
    horizon_ms: int
    material_threshold_bps: int
    source_decision_state_digest: str
    source_feature_state_digest: str
    source_context_stability_digest: str
    source_receipt_digest: str
    source_evidence_artifact_digest: str
    source_evidence_run_id: int
    source_upstream_run_id: int
    source_max_decision_timestamp_ms: int
    validation_not_before_ms: int
    discovery_material_outcomes: int
    discovery_direction_share: Decimal
    validation_material_outcomes: int
    validation_direction_share: Decimal
    validation_block_outcomes: tuple[int, ...]
    validation_block_direction_shares: tuple[Decimal, ...]
    source_evidence_class: str = FROZEN_SOURCE_EVIDENCE_CLASS
    prospective_evidence_class: str = FROZEN_PROSPECTIVE_EVIDENCE_CLASS
    prospective_only: bool = True
    promotion_eligible: bool = False
    execution_authority: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if not self.volatility_regime.strip():
            raise ValueError("volatility_regime must not be empty")
        if self.direction is not Direction.SHORT:
            raise ValueError("frozen candidate direction must be SHORT")
        if self.horizon_ms != 3_600_000:
            raise ValueError("frozen candidate horizon must be 1h")
        if self.material_threshold_bps <= 0:
            raise ValueError("material_threshold_bps must be positive")
        for field in (
            "source_decision_state_digest",
            "source_feature_state_digest",
            "source_context_stability_digest",
            "source_receipt_digest",
        ):
            _require_sha256(getattr(self, field), field)
        if (
            not self.source_evidence_artifact_digest.startswith("sha256:")
            or len(self.source_evidence_artifact_digest) != 71
        ):
            raise ValueError(
                "source_evidence_artifact_digest must be sha256:<digest>"
            )
        _require_sha256(
            self.source_evidence_artifact_digest.removeprefix("sha256:"),
            "source_evidence_artifact_digest",
        )
        if self.source_evidence_run_id <= 0 or self.source_upstream_run_id <= 0:
            raise ValueError("source run ids must be positive")
        if self.source_max_decision_timestamp_ms < 0:
            raise ValueError("source_max_decision_timestamp_ms must be non-negative")
        if self.validation_not_before_ms <= self.source_max_decision_timestamp_ms:
            raise ValueError(
                "validation_not_before_ms must be after source evidence"
            )
        if self.validation_not_before_ms < (
            self.source_max_decision_timestamp_ms + 6 * 60 * 60 * 1_000
        ):
            raise ValueError("frozen candidate requires a 6h prospective embargo")
        if self.discovery_material_outcomes <= 0:
            raise ValueError("discovery_material_outcomes must be positive")
        if self.validation_material_outcomes <= 0:
            raise ValueError("validation_material_outcomes must be positive")
        for value, field in (
            (self.discovery_direction_share, "discovery_direction_share"),
            (self.validation_direction_share, "validation_direction_share"),
        ):
            if not Decimal("0.5") < value <= Decimal("1"):
                raise ValueError(f"{field} must be in (0.5, 1]")
        if len(self.validation_block_outcomes) != FROZEN_VALIDATION_BLOCK_COUNT:
            raise ValueError("validation block outcome count is not frozen")
        if len(self.validation_block_direction_shares) != FROZEN_VALIDATION_BLOCK_COUNT:
            raise ValueError("validation block share count is not frozen")
        if any(value < FROZEN_MIN_BLOCK_ROWS for value in self.validation_block_outcomes):
            raise ValueError("frozen validation block row floor was not met")
        if any(
            value < FROZEN_MIN_BLOCK_SHORT_SHARE
            for value in self.validation_block_direction_shares
        ):
            raise ValueError("frozen validation block direction floor was not met")
        if self.source_evidence_class != FROZEN_SOURCE_EVIDENCE_CLASS:
            raise ValueError("source evidence class must remain touched")
        if self.prospective_evidence_class != FROZEN_PROSPECTIVE_EVIDENCE_CLASS:
            raise ValueError("prospective evidence class is fixed")
        if not self.prospective_only:
            raise ValueError("frozen candidate must remain prospective_only")
        if self.promotion_eligible:
            raise ValueError("frozen candidate cannot be promotion eligible")
        if self.execution_authority:
            raise ValueError("frozen candidate cannot have execution authority")
        if self.schema_version != 1:
            raise ValueError("unsupported frozen candidate schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "market": self.market,
            "volatility_regime": self.volatility_regime,
            "direction": self.direction.value,
            "horizon_ms": self.horizon_ms,
            "material_threshold_bps": self.material_threshold_bps,
            "source_decision_state_digest": self.source_decision_state_digest,
            "source_feature_state_digest": self.source_feature_state_digest,
            "source_context_stability_digest": self.source_context_stability_digest,
            "source_receipt_digest": self.source_receipt_digest,
            "source_evidence_artifact_digest": self.source_evidence_artifact_digest,
            "source_evidence_run_id": self.source_evidence_run_id,
            "source_upstream_run_id": self.source_upstream_run_id,
            "source_max_decision_timestamp_ms": self.source_max_decision_timestamp_ms,
            "validation_not_before_ms": self.validation_not_before_ms,
            "discovery_material_outcomes": self.discovery_material_outcomes,
            "discovery_direction_share": str(self.discovery_direction_share),
            "validation_material_outcomes": self.validation_material_outcomes,
            "validation_direction_share": str(self.validation_direction_share),
            "validation_block_outcomes": self.validation_block_outcomes,
            "validation_block_direction_shares": tuple(
                str(value) for value in self.validation_block_direction_shares
            ),
            "source_evidence_class": self.source_evidence_class,
            "prospective_evidence_class": self.prospective_evidence_class,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_authority": self.execution_authority,
            "schema_version": self.schema_version,
        }

    @property
    def spec_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()


MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1 = FrozenNoTradeContextCandidate(
    candidate_id="mon-normal-volatility-short-1h-50bps-v1",
    market="MON",
    volatility_regime="normal",
    direction=Direction.SHORT,
    horizon_ms=3_600_000,
    material_threshold_bps=50,
    source_decision_state_digest=(
        "cf2c1b1acfdea5e76f0585d45388ae13e81a8562796034cf9e134ad49da3a04f"
    ),
    source_feature_state_digest=(
        "5d8e49fe5bb93e037be9af5d1a8315e642bde103ae1f36e803902c18c1ea9d0b"
    ),
    source_context_stability_digest=(
        "c94922dafddb7394a74929a7239023ecfc155bcd6513b1c569b2b41847c688e6"
    ),
    source_receipt_digest=(
        "6acdcd3c85372eb59c8df492c033aabf397b389fd7bfa4338c4d01ef5846e74b"
    ),
    source_evidence_artifact_digest=(
        "sha256:b91486afbd31778b075712512b81d7e94b6c2db716683fc0fe4d4954ba388ca1"
    ),
    source_evidence_run_id=374_666_517_10,
    source_upstream_run_id=374_453_536_28,
    source_max_decision_timestamp_ms=1_791_283_530_000,
    validation_not_before_ms=1_791_305_130_000,
    discovery_material_outcomes=52,
    discovery_direction_share=Decimal(
        "0.6153846153846153846153846154"
    ),
    validation_material_outcomes=25,
    validation_direction_share=Decimal("0.76"),
    validation_block_outcomes=(8, 8, 9),
    validation_block_direction_shares=(
        Decimal("0.75"),
        Decimal("0.75"),
        Decimal("0.7777777777777777777777777778"),
    ),
)


@dataclass(frozen=True, slots=True)
class FrozenNoTradeShadowReport:
    candidate_spec_id: str
    candidate_id: str
    validation_not_before_ms: int
    source_decision_state_digest: str
    current_decision_state_digest: str
    current_feature_state_digest: str
    matching_labeled_outcomes: int
    material_outcomes: int
    short_favored_material_outcomes: int
    long_favored_material_outcomes: int
    flat_material_outcomes: int
    short_material_share: Decimal | None
    mean_forward_return: Decimal | None
    first_matching_decision_timestamp_ms: int | None
    last_matching_decision_timestamp_ms: int | None
    validation_block_outcomes: tuple[int, ...]
    validation_block_short_shares: tuple[Decimal | None, ...]
    validation_blocks_meeting_row_floor: int
    validation_blocks_directionally_consistent: int
    ready_for_review: bool
    schema_version: int = FROZEN_NO_TRADE_SHADOW_SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_spec_id": self.candidate_spec_id,
            "candidate_id": self.candidate_id,
            "validation_not_before_ms": self.validation_not_before_ms,
            "source_decision_state_digest": self.source_decision_state_digest,
            "current_decision_state_digest": self.current_decision_state_digest,
            "current_feature_state_digest": self.current_feature_state_digest,
            "matching_labeled_outcomes": self.matching_labeled_outcomes,
            "material_outcomes": self.material_outcomes,
            "short_favored_material_outcomes": self.short_favored_material_outcomes,
            "long_favored_material_outcomes": self.long_favored_material_outcomes,
            "flat_material_outcomes": self.flat_material_outcomes,
            "short_material_share": (
                None
                if self.short_material_share is None
                else str(self.short_material_share)
            ),
            "mean_forward_return": (
                None
                if self.mean_forward_return is None
                else str(self.mean_forward_return)
            ),
            "first_matching_decision_timestamp_ms": (
                self.first_matching_decision_timestamp_ms
            ),
            "last_matching_decision_timestamp_ms": (
                self.last_matching_decision_timestamp_ms
            ),
            "validation_block_outcomes": self.validation_block_outcomes,
            "validation_block_short_shares": tuple(
                None if value is None else str(value)
                for value in self.validation_block_short_shares
            ),
            "validation_blocks_meeting_row_floor": (
                self.validation_blocks_meeting_row_floor
            ),
            "validation_blocks_directionally_consistent": (
                self.validation_blocks_directionally_consistent
            ),
            "ready_for_review": self.ready_for_review,
            "evidence_class": FROZEN_PROSPECTIVE_EVIDENCE_CLASS,
            "prospective_only": True,
            "review_only": True,
            "promotion_eligible": False,
            "strategy_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class _ShadowOutcome:
    timestamp_ms: int
    forward_return: Decimal

    @property
    def direction(self) -> str:
        if self.forward_return < ZERO:
            return "short"
        if self.forward_return > ZERO:
            return "long"
        return "flat"


def _chronological_blocks(
    outcomes: tuple[_ShadowOutcome, ...],
    *,
    count: int,
) -> tuple[tuple[_ShadowOutcome, ...], ...]:
    if not outcomes:
        return ()
    timestamps = tuple(sorted({item.timestamp_ms for item in outcomes}))
    resolved = min(count, len(timestamps))
    blocks: list[tuple[_ShadowOutcome, ...]] = []
    for index in range(resolved):
        start = (len(timestamps) * index) // resolved
        end = (len(timestamps) * (index + 1)) // resolved
        block_timestamps = set(timestamps[start:end])
        if not block_timestamps:
            continue
        blocks.append(
            tuple(
                item
                for item in outcomes
                if item.timestamp_ms in block_timestamps
            )
        )
    return tuple(blocks)


def build_frozen_no_trade_shadow_report(
    forward_report: dict[str, object],
    *,
    candidate: FrozenNoTradeContextCandidate = (
        MON_NORMAL_VOLATILITY_SHORT_1H_50BPS_V1
    ),
) -> FrozenNoTradeShadowReport:
    if forward_report.get("diagnostic_only") is not True:
        raise FrozenNoTradeShadowError(
            "source forward report must be diagnostic-only"
        )
    if forward_report.get("hypothetical_pnl") is not False:
        raise FrozenNoTradeShadowError(
            "source forward report must not claim hypothetical PnL"
        )
    if forward_report.get("execution_authority") is not False:
        raise FrozenNoTradeShadowError(
            "source forward report must have no execution authority"
        )
    if forward_report.get("schema_version") != 2:
        raise FrozenNoTradeShadowError(
            "source forward report schema is unsupported"
        )

    current_decision_digest = _string(
        forward_report.get("decision_state_digest"),
        "decision_state_digest",
    )
    current_feature_digest = _string(
        forward_report.get("feature_state_digest"),
        "feature_state_digest",
    )
    _require_sha256(current_decision_digest, "decision_state_digest")
    _require_sha256(current_feature_digest, "feature_state_digest")

    matching: list[_ShadowOutcome] = []
    threshold = Decimal(candidate.material_threshold_bps) / BPS
    for raw_value in _sequence(forward_report.get("outcomes"), "outcomes"):
        raw = _mapping(raw_value, "outcome")
        if _string(raw.get("decision_stage"), "decision_stage") != "strategy_abstained":
            continue
        if _string(raw.get("market"), "market") != candidate.market:
            continue
        if (
            _string(raw.get("volatility_regime"), "volatility_regime")
            != candidate.volatility_regime
        ):
            continue
        if _integer(raw.get("horizon_ms"), "horizon_ms") != candidate.horizon_ms:
            continue
        timestamp_ms = _integer(
            raw.get("decision_timestamp_ms"),
            "decision_timestamp_ms",
        )
        if timestamp_ms < candidate.validation_not_before_ms:
            continue
        forward_return = _decimal(
            raw.get("forward_mark_return"),
            "forward_mark_return",
        )
        favored = _string(raw.get("favored_direction"), "favored_direction")
        expected = (
            "short"
            if forward_return < ZERO
            else "long"
            if forward_return > ZERO
            else "no_trade"
        )
        if favored != expected:
            raise FrozenNoTradeShadowError(
                "favored_direction does not match forward return"
            )
        matching.append(
            _ShadowOutcome(
                timestamp_ms=timestamp_ms,
                forward_return=forward_return,
            )
        )

    ordered = tuple(
        sorted(
            matching,
            key=lambda item: (
                item.timestamp_ms,
                item.forward_return,
            ),
        )
    )
    material = tuple(
        item for item in ordered if abs(item.forward_return) >= threshold
    )
    short_count = sum(item.direction == "short" for item in material)
    long_count = sum(item.direction == "long" for item in material)
    flat_count = len(material) - short_count - long_count
    short_share = (
        None
        if not material
        else Decimal(short_count) / Decimal(len(material))
    )
    mean_return = (
        None
        if not ordered
        else sum((item.forward_return for item in ordered), ZERO)
        / Decimal(len(ordered))
    )

    blocks = _chronological_blocks(
        material,
        count=FROZEN_VALIDATION_BLOCK_COUNT,
    )
    block_outcomes = tuple(len(block) for block in blocks)
    block_shares = tuple(
        (
            Decimal(sum(item.direction == "short" for item in block))
            / Decimal(len(block))
            if block
            else None
        )
        for block in blocks
    )
    blocks_meeting_row_floor = sum(
        count >= FROZEN_MIN_BLOCK_ROWS for count in block_outcomes
    )
    blocks_directionally_consistent = sum(
        count >= FROZEN_MIN_BLOCK_ROWS
        and share is not None
        and share >= FROZEN_MIN_BLOCK_SHORT_SHARE
        for count, share in zip(
            block_outcomes,
            block_shares,
            strict=True,
        )
    )
    ready_for_review = (
        len(material) >= FROZEN_MIN_REVIEW_MATERIAL_OUTCOMES
        and short_share is not None
        and short_share >= FROZEN_MIN_REVIEW_SHORT_SHARE
        and len(blocks) == FROZEN_VALIDATION_BLOCK_COUNT
        and blocks_meeting_row_floor == FROZEN_VALIDATION_BLOCK_COUNT
        and blocks_directionally_consistent == FROZEN_VALIDATION_BLOCK_COUNT
    )

    return FrozenNoTradeShadowReport(
        candidate_spec_id=candidate.spec_id,
        candidate_id=candidate.candidate_id,
        validation_not_before_ms=candidate.validation_not_before_ms,
        source_decision_state_digest=candidate.source_decision_state_digest,
        current_decision_state_digest=current_decision_digest,
        current_feature_state_digest=current_feature_digest,
        matching_labeled_outcomes=len(ordered),
        material_outcomes=len(material),
        short_favored_material_outcomes=short_count,
        long_favored_material_outcomes=long_count,
        flat_material_outcomes=flat_count,
        short_material_share=short_share,
        mean_forward_return=mean_return,
        first_matching_decision_timestamp_ms=(
            None if not ordered else ordered[0].timestamp_ms
        ),
        last_matching_decision_timestamp_ms=(
            None if not ordered else ordered[-1].timestamp_ms
        ),
        validation_block_outcomes=block_outcomes,
        validation_block_short_shares=block_shares,
        validation_blocks_meeting_row_floor=blocks_meeting_row_floor,
        validation_blocks_directionally_consistent=(
            blocks_directionally_consistent
        ),
        ready_for_review=ready_for_review,
    )
