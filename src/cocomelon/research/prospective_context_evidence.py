from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import cast

from cocomelon.domain.market import Candle, MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_discovery_freeze import (
    HistoricalDiscoveryFreezeSpec,
    ProspectiveContextDecision,
)

ZERO = Decimal("0")
ONE = Decimal("1")
PROSPECTIVE_EVIDENCE_CLASS = "prospective_clean"
CAMPAIGN_SCHEMA_VERSION = 1
RECORD_SCHEMA_VERSION = 1
MAX_ENTRY_CANDLE_AGE_MS = 15 * 60 * 1_000
FROZEN_CONTEXT_BASKET = ("BTC", "ETH", "HYPE", "SOL")


class ProspectiveEvidenceConsistencyError(RuntimeError):
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


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_finite_positive(value: Decimal, field: str) -> None:
    if not value.is_finite() or value <= ZERO:
        raise ValueError(f"{field} must be positive and finite")


def _require_finite_nonnegative(value: Decimal, field: str) -> None:
    if not value.is_finite() or value < ZERO:
        raise ValueError(f"{field} must be non-negative and finite")


def _market(value: str) -> MarketId:
    if ":" in value:
        dex, _coin = value.split(":", 1)
        return MarketId.from_wire_name(dex, value)
    return MarketId.from_wire_name("", value)


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, MarketId):
        return value.canonical
    if isinstance(value, tuple):
        return tuple(_json_value(item) for item in value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported prospective evidence value: {type(value).__name__}")


def candle_identity(candle: Candle) -> str:
    for field in ("open_px", "high_px", "low_px", "close_px"):
        _require_finite_positive(cast(Decimal, getattr(candle, field)), field)
    if not candle.volume.is_finite() or candle.volume < ZERO:
        raise ValueError("volume must be non-negative and finite")
    if candle.end_ms < candle.start_ms:
        raise ValueError("candle end_ms must be >= start_ms")
    if candle.received_at_ms < 0:
        raise ValueError("candle received_at_ms must be non-negative")
    if candle.schema_version <= 0:
        raise ValueError("candle schema_version must be positive")
    payload = {
        "market": candle.market.canonical,
        "interval": candle.interval,
        "start_ms": candle.start_ms,
        "end_ms": candle.end_ms,
        "open_px": str(candle.open_px),
        "high_px": str(candle.high_px),
        "low_px": str(candle.low_px),
        "close_px": str(candle.close_px),
        "volume": str(candle.volume),
        "trade_count": candle.trade_count,
        "source": candle.source,
        "received_at_ms": candle.received_at_ms,
        "schema_version": candle.schema_version,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ProspectiveCampaignManifest:
    candidate_spec_id: str
    candidate_id: str
    validation_not_before_ms: int
    basket_markets: tuple[str, ...] = FROZEN_CONTEXT_BASKET
    evidence_class: str = PROSPECTIVE_EVIDENCE_CLASS
    promotion_eligible: bool = False
    schema_version: int = CAMPAIGN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.candidate_spec_id, "candidate_spec_id")
        _require_nonempty(self.candidate_id, "candidate_id")
        if self.validation_not_before_ms < 0:
            raise ValueError("validation_not_before_ms must be non-negative")
        if self.basket_markets != FROZEN_CONTEXT_BASKET:
            raise ValueError("prospective campaign basket must match frozen discovery")
        if self.evidence_class != PROSPECTIVE_EVIDENCE_CLASS:
            raise ValueError("prospective campaign evidence_class is fixed")
        if self.promotion_eligible:
            raise ValueError("prospective research campaign is not promotion eligible")
        if self.schema_version != CAMPAIGN_SCHEMA_VERSION:
            raise ValueError("unsupported prospective campaign schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_spec_id": self.candidate_spec_id,
            "candidate_id": self.candidate_id,
            "validation_not_before_ms": self.validation_not_before_ms,
            "basket_markets": self.basket_markets,
            "evidence_class": self.evidence_class,
            "promotion_eligible": self.promotion_eligible,
            "schema_version": self.schema_version,
        }

    @property
    def campaign_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProspectiveObservation:
    candidate_spec_id: str
    raw_decision_id: str
    market: MarketId
    decision_as_of_ms: int
    source_received_at_ms: int
    anchor_end_ms: int
    target_end_ms: int
    raw_direction: Direction
    effective_direction: Direction
    hold_until_ms: int | None
    context_state_1h: str
    feature_snapshot_id: str
    cross_market_snapshot_id: str
    entry_candle_id: str
    entry_px: Decimal
    modeled_cost_fraction: Decimal
    reason_codes: tuple[str, ...]
    occupancy_blocked_by_observation_id: str | None = None
    schema_version: int = RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.candidate_spec_id, "candidate_spec_id")
        _require_nonempty(self.raw_decision_id, "raw_decision_id")
        if self.decision_as_of_ms < 0:
            raise ValueError("decision_as_of_ms must be non-negative")
        if self.source_received_at_ms < 0:
            raise ValueError("source_received_at_ms must be non-negative")
        if self.source_received_at_ms > self.decision_as_of_ms:
            raise ValueError("source_received_at_ms must not be after decision")
        if self.anchor_end_ms < 0 or self.anchor_end_ms > self.decision_as_of_ms:
            raise ValueError("anchor_end_ms must be closed by decision time")
        if self.target_end_ms <= self.anchor_end_ms:
            raise ValueError("target_end_ms must be after anchor_end_ms")
        _require_nonempty(self.context_state_1h, "context_state_1h")
        _require_nonempty(self.feature_snapshot_id, "feature_snapshot_id")
        _require_nonempty(self.cross_market_snapshot_id, "cross_market_snapshot_id")
        _require_nonempty(self.entry_candle_id, "entry_candle_id")
        _require_finite_positive(self.entry_px, "entry_px")
        _require_finite_nonnegative(self.modeled_cost_fraction, "modeled_cost_fraction")
        if not self.reason_codes or any(not code.strip() for code in self.reason_codes):
            raise ValueError("reason_codes must not be empty")
        if self.schema_version != RECORD_SCHEMA_VERSION:
            raise ValueError("unsupported prospective observation schema")

        if self.raw_direction is Direction.NO_TRADE:
            if self.effective_direction is not Direction.NO_TRADE:
                raise ValueError("NO_TRADE raw decision cannot become directional")
            if self.occupancy_blocked_by_observation_id is not None:
                raise ValueError("raw NO_TRADE cannot be occupancy blocked")
        elif self.effective_direction not in {self.raw_direction, Direction.NO_TRADE}:
            raise ValueError("occupancy may only preserve or suppress raw direction")

        if self.effective_direction is Direction.NO_TRADE:
            if self.hold_until_ms is not None:
                raise ValueError("NO_TRADE observation cannot have hold_until_ms")
        else:
            if self.hold_until_ms != self.target_end_ms:
                raise ValueError("directional observation must hold through target_end_ms")
            if self.occupancy_blocked_by_observation_id is not None:
                raise ValueError("directional observation cannot be occupancy blocked")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_spec_id": self.candidate_spec_id,
            "raw_decision_id": self.raw_decision_id,
            "market": self.market.canonical,
            "decision_as_of_ms": self.decision_as_of_ms,
            "source_received_at_ms": self.source_received_at_ms,
            "anchor_end_ms": self.anchor_end_ms,
            "target_end_ms": self.target_end_ms,
            "raw_direction": self.raw_direction.value,
            "effective_direction": self.effective_direction.value,
            "hold_until_ms": self.hold_until_ms,
            "context_state_1h": self.context_state_1h,
            "feature_snapshot_id": self.feature_snapshot_id,
            "cross_market_snapshot_id": self.cross_market_snapshot_id,
            "entry_candle_id": self.entry_candle_id,
            "entry_px": str(self.entry_px),
            "modeled_cost_fraction": str(self.modeled_cost_fraction),
            "reason_codes": self.reason_codes,
            "occupancy_blocked_by_observation_id": (
                self.occupancy_blocked_by_observation_id
            ),
            "schema_version": self.schema_version,
        }

    @property
    def observation_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ProspectiveOutcome:
    candidate_spec_id: str
    observation_id: str
    market: MarketId
    anchor_end_ms: int
    target_end_ms: int
    direction: Direction
    entry_px: Decimal
    exit_px: Decimal
    exit_candle_id: str
    exit_source_received_at_ms: int
    gross_return: Decimal
    modeled_cost_fraction: Decimal
    net_return: Decimal
    schema_version: int = RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.candidate_spec_id, "candidate_spec_id")
        _require_nonempty(self.observation_id, "observation_id")
        if self.direction not in {Direction.LONG, Direction.SHORT}:
            raise ValueError("outcome requires a directional observation")
        if self.anchor_end_ms < 0 or self.target_end_ms <= self.anchor_end_ms:
            raise ValueError("invalid outcome anchor/target timestamps")
        _require_finite_positive(self.entry_px, "entry_px")
        _require_finite_positive(self.exit_px, "exit_px")
        _require_nonempty(self.exit_candle_id, "exit_candle_id")
        if self.exit_source_received_at_ms < self.target_end_ms:
            raise ValueError("exit candle must be received after target close")
        for field in ("gross_return", "modeled_cost_fraction", "net_return"):
            value = cast(Decimal, getattr(self, field))
            if not value.is_finite():
                raise ValueError(f"{field} must be finite")
        if self.modeled_cost_fraction < ZERO:
            raise ValueError("modeled_cost_fraction must be non-negative")
        if self.net_return != self.gross_return - self.modeled_cost_fraction:
            raise ValueError("net_return must equal gross_return minus modeled cost")
        if self.schema_version != RECORD_SCHEMA_VERSION:
            raise ValueError("unsupported prospective outcome schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_spec_id": self.candidate_spec_id,
            "observation_id": self.observation_id,
            "market": self.market.canonical,
            "anchor_end_ms": self.anchor_end_ms,
            "target_end_ms": self.target_end_ms,
            "direction": self.direction.value,
            "entry_px": str(self.entry_px),
            "exit_px": str(self.exit_px),
            "exit_candle_id": self.exit_candle_id,
            "exit_source_received_at_ms": self.exit_source_received_at_ms,
            "gross_return": str(self.gross_return),
            "modeled_cost_fraction": str(self.modeled_cost_fraction),
            "net_return": str(self.net_return),
            "schema_version": self.schema_version,
        }

    @property
    def outcome_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()[:24]


def _validate_entry_candle(
    spec: HistoricalDiscoveryFreezeSpec,
    raw_decision: ProspectiveContextDecision,
    candle: Candle,
) -> None:
    if candle.market != spec.market or candle.market != raw_decision.market:
        raise ValueError("entry candle market must match candidate")
    if candle.interval != spec.anchor_interval:
        raise ValueError(f"entry candle must use {spec.anchor_interval} interval")
    if candle.received_at_ms > raw_decision.as_of_ms:
        raise ValueError("entry candle was received after decision")
    if candle.end_ms > raw_decision.as_of_ms:
        raise ValueError("entry candle must be closed by decision time")
    if raw_decision.as_of_ms - candle.end_ms > MAX_ENTRY_CANDLE_AGE_MS:
        raise ValueError("entry candle is stale for prospective anchor")
    _require_finite_positive(candle.close_px, "entry candle close")


def build_prospective_observation(
    spec: HistoricalDiscoveryFreezeSpec,
    *,
    raw_decision: ProspectiveContextDecision,
    entry_candle: Candle,
    prior_observations: tuple[ProspectiveObservation, ...],
) -> ProspectiveObservation:
    if raw_decision.candidate_spec_id != spec.spec_id:
        raise ValueError("raw decision candidate spec does not match frozen spec")
    if entry_candle.end_ms < spec.validation_not_before_ms:
        raise ValueError("entry candle anchor predates prospective cutover")
    if raw_decision.market != spec.market:
        raise ValueError("raw decision market does not match frozen spec")
    _validate_entry_candle(spec, raw_decision, entry_candle)

    target_end_ms = entry_candle.end_ms + spec.horizon_ms
    effective = raw_decision.direction
    hold_until_ms = target_end_ms if effective is not Direction.NO_TRADE else None
    blocked_by: str | None = None
    reason_codes = raw_decision.reason_codes

    if raw_decision.direction is not Direction.NO_TRADE:
        active = tuple(
            observation
            for observation in prior_observations
            if observation.candidate_spec_id == spec.spec_id
            and observation.market == spec.market
            and observation.effective_direction is not Direction.NO_TRADE
            and observation.anchor_end_ms < entry_candle.end_ms
            and observation.hold_until_ms is not None
            and observation.hold_until_ms > entry_candle.end_ms
        )
        if active:
            blocker = max(active, key=lambda item: (item.anchor_end_ms, item.observation_id))
            effective = Direction.NO_TRADE
            hold_until_ms = None
            blocked_by = blocker.observation_id
            reason_codes = (*reason_codes, "one_position_per_market_occupied")

    return ProspectiveObservation(
        candidate_spec_id=spec.spec_id,
        raw_decision_id=raw_decision.decision_id,
        market=spec.market,
        decision_as_of_ms=raw_decision.as_of_ms,
        source_received_at_ms=max(
            raw_decision.source_received_at_ms,
            entry_candle.received_at_ms,
        ),
        anchor_end_ms=entry_candle.end_ms,
        target_end_ms=target_end_ms,
        raw_direction=raw_decision.direction,
        effective_direction=effective,
        hold_until_ms=hold_until_ms,
        context_state_1h=raw_decision.context_state_1h,
        feature_snapshot_id=raw_decision.feature_snapshot_id,
        cross_market_snapshot_id=raw_decision.cross_market_snapshot_id,
        entry_candle_id=candle_identity(entry_candle),
        entry_px=entry_candle.close_px,
        modeled_cost_fraction=spec.costs.total_cost_fraction(spec.horizon_ms),
        reason_codes=reason_codes,
        occupancy_blocked_by_observation_id=blocked_by,
    )


def build_prospective_outcome(
    spec: HistoricalDiscoveryFreezeSpec,
    *,
    observation: ProspectiveObservation,
    exit_candle: Candle,
) -> ProspectiveOutcome:
    if observation.candidate_spec_id != spec.spec_id:
        raise ValueError("observation candidate spec does not match frozen spec")
    if observation.effective_direction not in {Direction.LONG, Direction.SHORT}:
        raise ValueError("outcome requires a directional observation")
    if exit_candle.market != observation.market:
        raise ValueError("exit candle market must match observation")
    if exit_candle.interval != spec.anchor_interval:
        raise ValueError(f"exit candle must use {spec.anchor_interval} interval")
    if exit_candle.end_ms != observation.target_end_ms:
        raise ValueError("target candle end must exactly match prospective target")
    _require_finite_positive(exit_candle.close_px, "exit candle close")

    long_return = exit_candle.close_px / observation.entry_px - ONE
    gross_return = (
        long_return
        if observation.effective_direction is Direction.LONG
        else -long_return
    )
    modeled_cost = spec.costs.total_cost_fraction(spec.horizon_ms)
    if modeled_cost != observation.modeled_cost_fraction:
        raise ValueError("observation modeled costs do not match frozen spec")

    return ProspectiveOutcome(
        candidate_spec_id=spec.spec_id,
        observation_id=observation.observation_id,
        market=observation.market,
        anchor_end_ms=observation.anchor_end_ms,
        target_end_ms=observation.target_end_ms,
        direction=observation.effective_direction,
        entry_px=observation.entry_px,
        exit_px=exit_candle.close_px,
        exit_candle_id=candle_identity(exit_candle),
        exit_source_received_at_ms=exit_candle.received_at_ms,
        gross_return=gross_return,
        modeled_cost_fraction=modeled_cost,
        net_return=gross_return - modeled_cost,
    )


class ProspectiveEvidenceStore:
    def __init__(
        self,
        root: str | Path,
        *,
        spec: HistoricalDiscoveryFreezeSpec,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.spec = spec
        self.manifest = ProspectiveCampaignManifest(
            candidate_spec_id=spec.spec_id,
            candidate_id=spec.candidate_id,
            validation_not_before_ms=spec.validation_not_before_ms,
        )
        self.manifest_path = self.root / "manifest.json"
        self._ensure_manifest()

    def _ensure_manifest(self) -> None:
        payload = {
            **self.manifest.identity_payload(),
            "campaign_id": self.manifest.campaign_id,
        }
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        if self.manifest_path.exists():
            if self.manifest_path.read_bytes() != encoded:
                raise ProspectiveEvidenceConsistencyError(
                    "conflicting prospective campaign manifest"
                )
            return
        temporary = self.root / "manifest.json.tmp"
        with temporary.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.manifest_path)

    @staticmethod
    def _date_path(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date().isoformat()

    def _record_path(self, kind: str, timestamp_ms: int, record_id: str) -> Path:
        return self.root / kind / self._date_path(timestamp_ms) / f"{record_id}.json"

    @staticmethod
    def _write_consistent(path: Path, payload: dict[str, object]) -> Path:
        encoded = (_canonical_json(_json_value(payload)) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise ProspectiveEvidenceConsistencyError(
                    f"conflicting prospective evidence record: {path.name}"
                )
            return path
        try:
            with path.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise ProspectiveEvidenceConsistencyError(
                    f"conflicting prospective evidence record: {path.name}"
                ) from None
        return path

    def record_observation(self, observation: ProspectiveObservation) -> Path:
        if observation.candidate_spec_id != self.spec.spec_id:
            raise ValueError("observation does not belong to this campaign")
        try:
            existing = self.observation_for_anchor(observation.anchor_end_ms)
        except ProspectiveEvidenceConsistencyError as exc:
            raise ProspectiveEvidenceConsistencyError(
                "conflicting prospective observation evidence"
            ) from exc
        if existing is not None and existing != observation:
            raise ProspectiveEvidenceConsistencyError(
                "conflicting prospective observation for anchor"
            )
        if existing is not None:
            return self._record_path(
                "observations",
                existing.anchor_end_ms,
                existing.observation_id,
            )
        path = self._record_path(
            "observations",
            observation.anchor_end_ms,
            observation.observation_id,
        )
        return self._write_consistent(path, observation.identity_payload())

    def record_outcome(self, outcome: ProspectiveOutcome) -> Path:
        if outcome.candidate_spec_id != self.spec.spec_id:
            raise ValueError("outcome does not belong to this campaign")
        existing_for_observation = tuple(
            item for item in self.iter_outcomes() if item.observation_id == outcome.observation_id
        )
        if existing_for_observation:
            existing = existing_for_observation[0]
            if existing != outcome:
                raise ProspectiveEvidenceConsistencyError(
                    "conflicting outcome for prospective observation"
                )
            return self._record_path(
                "outcomes",
                existing.target_end_ms,
                existing.outcome_id,
            )
        path = self._record_path("outcomes", outcome.target_end_ms, outcome.outcome_id)
        return self._write_consistent(path, outcome.identity_payload())

    def observation_for_anchor(
        self,
        anchor_end_ms: int,
    ) -> ProspectiveObservation | None:
        matches = tuple(
            item
            for item in self.iter_observations()
            if item.anchor_end_ms == anchor_end_ms
        )
        if len(matches) > 1:
            raise ProspectiveEvidenceConsistencyError(
                "multiple prospective observations for one anchor"
            )
        return None if not matches else matches[0]

    def load_observation(self, observation_id: str) -> ProspectiveObservation | None:
        for path in sorted((self.root / "observations").glob("*/*.json")):
            if path.stem != observation_id:
                continue
            return self._load_observation_path(path)
        return None

    def load_outcome(self, outcome_id: str) -> ProspectiveOutcome | None:
        for path in sorted((self.root / "outcomes").glob("*/*.json")):
            if path.stem != outcome_id:
                continue
            return self._load_outcome_path(path)
        return None

    def iter_observations(self) -> tuple[ProspectiveObservation, ...]:
        root = self.root / "observations"
        if not root.exists():
            return ()
        values = tuple(
            self._load_observation_path(path)
            for path in sorted(root.glob("*/*.json"))
        )
        return tuple(sorted(values, key=lambda item: (item.anchor_end_ms, item.observation_id)))

    def iter_outcomes(self) -> tuple[ProspectiveOutcome, ...]:
        root = self.root / "outcomes"
        if not root.exists():
            return ()
        values = tuple(
            self._load_outcome_path(path)
            for path in sorted(root.glob("*/*.json"))
        )
        return tuple(sorted(values, key=lambda item: (item.target_end_ms, item.outcome_id)))

    def due_unsettled_observations(
        self,
        *,
        as_of_ms: int,
    ) -> tuple[ProspectiveObservation, ...]:
        if as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        settled = {outcome.observation_id for outcome in self.iter_outcomes()}
        return tuple(
            observation
            for observation in self.iter_observations()
            if observation.effective_direction in {Direction.LONG, Direction.SHORT}
            and observation.target_end_ms <= as_of_ms
            and observation.observation_id not in settled
        )

    def _load_observation_path(self, path: Path) -> ProspectiveObservation:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProspectiveEvidenceConsistencyError(
                "invalid prospective observation record"
            ) from exc
        observation = self._observation_from_payload(raw)
        if observation.candidate_spec_id != self.spec.spec_id:
            raise ProspectiveEvidenceConsistencyError(
                "prospective observation candidate spec mismatch"
            )
        if path.stem != observation.observation_id:
            raise ProspectiveEvidenceConsistencyError(
                "prospective observation identity mismatch"
            )
        return observation

    def _load_outcome_path(self, path: Path) -> ProspectiveOutcome:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProspectiveEvidenceConsistencyError(
                "invalid prospective outcome record"
            ) from exc
        outcome = self._outcome_from_payload(raw)
        if outcome.candidate_spec_id != self.spec.spec_id:
            raise ProspectiveEvidenceConsistencyError(
                "prospective outcome candidate spec mismatch"
            )
        if path.stem != outcome.outcome_id:
            raise ProspectiveEvidenceConsistencyError(
                "prospective outcome identity mismatch"
            )
        return outcome

    @staticmethod
    def _observation_from_payload(raw: object) -> ProspectiveObservation:
        if not isinstance(raw, dict):
            raise ProspectiveEvidenceConsistencyError(
                "prospective observation payload must be an object"
            )
        try:
            return ProspectiveObservation(
                candidate_spec_id=str(raw["candidate_spec_id"]),
                raw_decision_id=str(raw["raw_decision_id"]),
                market=_market(str(raw["market"])),
                decision_as_of_ms=int(raw["decision_as_of_ms"]),
                source_received_at_ms=int(raw["source_received_at_ms"]),
                anchor_end_ms=int(raw["anchor_end_ms"]),
                target_end_ms=int(raw["target_end_ms"]),
                raw_direction=Direction(str(raw["raw_direction"])),
                effective_direction=Direction(str(raw["effective_direction"])),
                hold_until_ms=(
                    None if raw["hold_until_ms"] is None else int(raw["hold_until_ms"])
                ),
                context_state_1h=str(raw["context_state_1h"]),
                feature_snapshot_id=str(raw["feature_snapshot_id"]),
                cross_market_snapshot_id=str(raw["cross_market_snapshot_id"]),
                entry_candle_id=str(raw["entry_candle_id"]),
                entry_px=Decimal(str(raw["entry_px"])),
                modeled_cost_fraction=Decimal(str(raw["modeled_cost_fraction"])),
                reason_codes=tuple(str(item) for item in cast(list[object], raw["reason_codes"])),
                occupancy_blocked_by_observation_id=(
                    None
                    if raw["occupancy_blocked_by_observation_id"] is None
                    else str(raw["occupancy_blocked_by_observation_id"])
                ),
                schema_version=int(raw["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveEvidenceConsistencyError(
                "invalid prospective observation payload"
            ) from exc

    @staticmethod
    def _outcome_from_payload(raw: object) -> ProspectiveOutcome:
        if not isinstance(raw, dict):
            raise ProspectiveEvidenceConsistencyError(
                "prospective outcome payload must be an object"
            )
        try:
            return ProspectiveOutcome(
                candidate_spec_id=str(raw["candidate_spec_id"]),
                observation_id=str(raw["observation_id"]),
                market=_market(str(raw["market"])),
                anchor_end_ms=int(raw["anchor_end_ms"]),
                target_end_ms=int(raw["target_end_ms"]),
                direction=Direction(str(raw["direction"])),
                entry_px=Decimal(str(raw["entry_px"])),
                exit_px=Decimal(str(raw["exit_px"])),
                exit_candle_id=str(raw["exit_candle_id"]),
                exit_source_received_at_ms=int(raw["exit_source_received_at_ms"]),
                gross_return=Decimal(str(raw["gross_return"])),
                modeled_cost_fraction=Decimal(str(raw["modeled_cost_fraction"])),
                net_return=Decimal(str(raw["net_return"])),
                schema_version=int(raw["schema_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProspectiveEvidenceConsistencyError(
                "invalid prospective outcome payload"
            ) from exc
