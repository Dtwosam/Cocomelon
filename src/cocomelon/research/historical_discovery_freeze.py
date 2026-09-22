from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.features.cross_market import CrossMarketContextSnapshot
from cocomelon.research.historical_baselines import ExecutionCostAssumptions

TOUCHED_EVIDENCE_CLASS = "touched_development"
ONE_POSITION_PER_MARKET = "one_position_per_market"
MIN_PROSPECTIVE_EMBARGO_MS = 6 * 60 * 60 * 1_000


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


@dataclass(frozen=True, slots=True)
class HistoricalDiscoveryFreezeSpec:
    candidate_id: str
    market: MarketId
    anchor_interval: str
    context_state_1h: str
    direction: Direction
    horizon_ms: int
    discovery_start_ms: int
    discovery_end_ms: int
    validation_not_before_ms: int
    discovery_report_id: str
    discovery_dataset_id: str
    occupancy_report_id: str
    occupancy_dataset_id: str
    costs: ExecutionCostAssumptions
    occupancy_mode: str = ONE_POSITION_PER_MARKET
    source_evidence_class: str = TOUCHED_EVIDENCE_CLASS
    prospective_only: bool = True
    promotion_eligible: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        if self.anchor_interval != "1h":
            raise ValueError("historical discovery candidate anchor_interval must be 1h")
        if not self.context_state_1h.strip():
            raise ValueError("context_state_1h must not be empty")
        if self.direction not in {Direction.LONG, Direction.SHORT}:
            raise ValueError("historical discovery candidate must be LONG or SHORT")
        if self.horizon_ms <= 0:
            raise ValueError("horizon_ms must be positive")
        if self.discovery_start_ms < 0:
            raise ValueError("discovery_start_ms must be non-negative")
        if self.discovery_end_ms <= self.discovery_start_ms:
            raise ValueError("discovery_end_ms must be after discovery_start_ms")
        if self.validation_not_before_ms < (
            self.discovery_end_ms + MIN_PROSPECTIVE_EMBARGO_MS
        ):
            raise ValueError(
                "validation_not_before_ms must be after the discovery embargo"
            )
        for field in (
            "discovery_report_id",
            "discovery_dataset_id",
            "occupancy_report_id",
            "occupancy_dataset_id",
        ):
            _require_sha256(getattr(self, field), field)
        if self.occupancy_mode != ONE_POSITION_PER_MARKET:
            raise ValueError("unsupported occupancy_mode")
        if self.source_evidence_class != TOUCHED_EVIDENCE_CLASS:
            raise ValueError("historical discovery evidence must remain touched")
        if not self.prospective_only:
            raise ValueError("historical discovery freeze must be prospective_only")
        if self.promotion_eligible:
            raise ValueError("historical discovery freeze cannot be promotion eligible")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "market": self.market.canonical,
            "anchor_interval": self.anchor_interval,
            "context_state_1h": self.context_state_1h,
            "direction": self.direction.value,
            "horizon_ms": self.horizon_ms,
            "discovery_start_ms": self.discovery_start_ms,
            "discovery_end_ms": self.discovery_end_ms,
            "validation_not_before_ms": self.validation_not_before_ms,
            "discovery_report_id": self.discovery_report_id,
            "discovery_dataset_id": self.discovery_dataset_id,
            "occupancy_report_id": self.occupancy_report_id,
            "occupancy_dataset_id": self.occupancy_dataset_id,
            "costs": {
                "round_trip_fee_fraction": str(
                    self.costs.round_trip_fee_fraction
                ),
                "round_trip_slippage_fraction": str(
                    self.costs.round_trip_slippage_fraction
                ),
                "funding_reserve_fraction_per_hour": str(
                    self.costs.funding_reserve_fraction_per_hour
                ),
            },
            "occupancy_mode": self.occupancy_mode,
            "source_evidence_class": self.source_evidence_class,
            "prospective_only": self.prospective_only,
            "promotion_eligible": self.promotion_eligible,
            "schema_version": self.schema_version,
        }

    @property
    def spec_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()


HYPE_DOWN_BEARISH_NEAR_BASKET_LONG_4H_V1 = HistoricalDiscoveryFreezeSpec(
    candidate_id="hype-down-bearish-near-basket-long-4h-v1",
    market=MarketId("", "HYPE"),
    anchor_interval="1h",
    context_state_1h="down/bearish/near_basket",
    direction=Direction.LONG,
    horizon_ms=14_400_000,
    discovery_start_ms=1_772_323_200_000,
    discovery_end_ms=1_789_862_400_000,
    validation_not_before_ms=1_790_121_600_000,
    discovery_report_id=(
        "f3b38a6625ad2ea2d1b2df7e736f5dbded6f2b415c53c80db35514e4f3589481"
    ),
    discovery_dataset_id=(
        "268aa965584316f35a9db520b13848fd030123eadc99482a89cd7bc68ffc091f"
    ),
    occupancy_report_id=(
        "fc083ac327d1cbc758af4515393a35647b980ae231f9a3763e1e8005286414c9"
    ),
    occupancy_dataset_id=(
        "543e919969cc3160f4b72ef687102f1a989ec8446d4f691b05c376b6d19b72df"
    ),
    costs=ExecutionCostAssumptions(
        round_trip_fee_fraction=Decimal("0.0007"),
        round_trip_slippage_fraction=Decimal("0.0005"),
        funding_reserve_fraction_per_hour=Decimal("0.0001"),
    ),
)


@dataclass(frozen=True, slots=True)
class ProspectiveContextDecision:
    candidate_spec_id: str
    market: MarketId
    as_of_ms: int
    source_received_at_ms: int
    direction: Direction
    hold_until_ms: int | None
    context_state_1h: str
    feature_snapshot_id: str
    cross_market_snapshot_id: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.candidate_spec_id, "candidate_spec_id")
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.source_received_at_ms < 0:
            raise ValueError("source_received_at_ms must be non-negative")
        if self.source_received_at_ms > self.as_of_ms:
            raise ValueError("source_received_at_ms must not be after as_of_ms")
        if not self.context_state_1h.strip():
            raise ValueError("context_state_1h must not be empty")
        if not self.feature_snapshot_id.strip():
            raise ValueError("feature_snapshot_id must not be empty")
        if not self.cross_market_snapshot_id.strip():
            raise ValueError("cross_market_snapshot_id must not be empty")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("reason_codes must not be empty")
        if self.direction is Direction.NO_TRADE:
            if self.hold_until_ms is not None:
                raise ValueError("NO_TRADE cannot have hold_until_ms")
        else:
            if self.hold_until_ms is None or self.hold_until_ms <= self.as_of_ms:
                raise ValueError("directional decision requires future hold_until_ms")

    @property
    def decision_id(self) -> str:
        payload = {
            "candidate_spec_id": self.candidate_spec_id,
            "market": self.market.canonical,
            "as_of_ms": self.as_of_ms,
            "source_received_at_ms": self.source_received_at_ms,
            "direction": self.direction.value,
            "hold_until_ms": self.hold_until_ms,
            "context_state_1h": self.context_state_1h,
            "feature_snapshot_id": self.feature_snapshot_id,
            "cross_market_snapshot_id": self.cross_market_snapshot_id,
            "reason_codes": self.reason_codes,
        }
        return hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()[:24]


def evaluate_prospective_context_candidate(
    spec: HistoricalDiscoveryFreezeSpec,
    *,
    feature: FeatureSnapshot,
    cross_market: CrossMarketContextSnapshot,
) -> ProspectiveContextDecision:
    if feature.market != spec.market or cross_market.market != spec.market:
        raise ValueError("candidate market must match feature and cross-market snapshots")
    if feature.as_of_ms != cross_market.as_of_ms:
        raise ValueError("feature and cross-market snapshots must use the same as_of_ms")

    context_state = cross_market.for_window("1h").context_state
    source_received_at_ms = max(
        feature.source_received_at_ms,
        cross_market.source_received_at_ms,
    )

    if feature.as_of_ms < spec.validation_not_before_ms:
        return ProspectiveContextDecision(
            candidate_spec_id=spec.spec_id,
            market=spec.market,
            as_of_ms=feature.as_of_ms,
            source_received_at_ms=source_received_at_ms,
            direction=Direction.NO_TRADE,
            hold_until_ms=None,
            context_state_1h=context_state,
            feature_snapshot_id=feature.snapshot_id,
            cross_market_snapshot_id=cross_market.snapshot_id,
            reason_codes=("before_prospective_cutover",),
        )

    if context_state != spec.context_state_1h:
        return ProspectiveContextDecision(
            candidate_spec_id=spec.spec_id,
            market=spec.market,
            as_of_ms=feature.as_of_ms,
            source_received_at_ms=source_received_at_ms,
            direction=Direction.NO_TRADE,
            hold_until_ms=None,
            context_state_1h=context_state,
            feature_snapshot_id=feature.snapshot_id,
            cross_market_snapshot_id=cross_market.snapshot_id,
            reason_codes=("context_mismatch",),
        )

    return ProspectiveContextDecision(
        candidate_spec_id=spec.spec_id,
        market=spec.market,
        as_of_ms=feature.as_of_ms,
        source_received_at_ms=source_received_at_ms,
        direction=spec.direction,
        hold_until_ms=feature.as_of_ms + spec.horizon_ms,
        context_state_1h=context_state,
        feature_snapshot_id=feature.snapshot_id,
        cross_market_snapshot_id=cross_market.snapshot_id,
        reason_codes=("frozen_historical_context_match",),
    )
