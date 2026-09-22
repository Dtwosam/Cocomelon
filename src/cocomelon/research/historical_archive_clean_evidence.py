from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from cocomelon.domain.market import Candle, MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.historical_archive_paper_scorer import (
    ArchivePaperAnchorResult,
    ArchivePaperPosition,
    ArchivePaperSignal,
    ArchivePaperState,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.historical_features import HistoricalFeatureRow

ZERO = Decimal("0")
ONE = Decimal("1")
MANIFEST_SCHEMA_VERSION = 1
ANCHOR_SCHEMA_VERSION = 1
OUTCOME_SCHEMA_VERSION = 1
CAPTURE_SCHEMA_VERSION = 1
SIGNAL_DISPOSITIONS = {
    "accepted",
    "raw_no_trade",
    "occupied_skip",
    "capacity_skip",
    "not_selected_horizon",
}


class HistoricalArchiveCleanEvidenceError(RuntimeError):
    pass


class HistoricalArchiveCleanEvidenceConsistencyError(
    HistoricalArchiveCleanEvidenceError
):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be lowercase SHA-256")


def _require_id24(value: str, field: str) -> None:
    if len(value) != 24 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be 24 lowercase hex characters")


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveCleanEvidenceError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise HistoricalArchiveCleanEvidenceError(f"{field} must be a sequence")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCleanEvidenceError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCleanEvidenceError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise HistoricalArchiveCleanEvidenceError(f"{field} must be boolean")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise HistoricalArchiveCleanEvidenceError(
            f"{field} must be a decimal string"
        )
    try:
        resolved = Decimal(value)
    except InvalidOperation as exc:
        raise HistoricalArchiveCleanEvidenceError(
            f"{field} must be a decimal string"
        ) from exc
    if not resolved.is_finite():
        raise HistoricalArchiveCleanEvidenceError(f"{field} must be finite")
    return resolved


def _optional_decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    return _decimal(value, field)


def _market_from_canonical(value: str) -> MarketId:
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    return MarketId(dex, coin)


def _position_payload(position: ArchivePaperPosition) -> dict[str, object]:
    return {
        "market": position.market,
        "opened_at_ms": position.opened_at_ms,
        "hold_until_ms": position.hold_until_ms,
        "horizon_ms": position.horizon_ms,
        "direction": position.direction.value,
        "expected_net_edge": str(position.expected_net_edge),
    }


def _state_payload(state: ArchivePaperState) -> dict[str, object]:
    return {
        "positions": tuple(_position_payload(item) for item in state.positions),
        "schema_version": state.schema_version,
    }


def _state_from_payload(value: object, field: str) -> ArchivePaperState:
    raw = _mapping(value, field)
    positions = tuple(
        ArchivePaperPosition(
            market=_string(item.get("market"), f"{field}.market"),
            opened_at_ms=_integer(
                item.get("opened_at_ms"),
                f"{field}.opened_at_ms",
            ),
            hold_until_ms=_integer(
                item.get("hold_until_ms"),
                f"{field}.hold_until_ms",
            ),
            horizon_ms=_integer(
                item.get("horizon_ms"),
                f"{field}.horizon_ms",
            ),
            direction=Direction(
                _string(item.get("direction"), f"{field}.direction")
            ),
            expected_net_edge=_decimal(
                item.get("expected_net_edge"),
                f"{field}.expected_net_edge",
            ),
        )
        for item in (
            _mapping(raw_item, f"{field}.position")
            for raw_item in _sequence(raw.get("positions"), f"{field}.positions")
        )
    )
    return ArchivePaperState(
        positions=positions,
        schema_version=_integer(raw.get("schema_version"), f"{field}.schema_version"),
    )


def _candle_id(candle: Candle) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
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
        ).encode("utf-8")
    ).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class ArchiveCleanCampaignManifest:
    validation_spec_id: str
    candidate_id: str
    model_artifact_id: str
    model_payload_sha256: str
    markets: tuple[str, ...]
    active_horizons: tuple[int, ...]
    validation_start_ms: int
    validation_end_ms: int
    finalization_not_before_ms: int
    expected_anchor_count: int
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "validation_spec_id",
            "candidate_id",
            "model_artifact_id",
            "model_payload_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if tuple(sorted(set(self.markets))) != self.markets or not self.markets:
            raise ValueError("manifest markets must be sorted unique and non-empty")
        if (
            tuple(sorted(set(self.active_horizons))) != self.active_horizons
            or not self.active_horizons
            or any(value <= 0 for value in self.active_horizons)
        ):
            raise ValueError("manifest active_horizons must be sorted positive unique")
        if self.validation_start_ms < 0:
            raise ValueError("validation_start_ms must be non-negative")
        if self.validation_end_ms <= self.validation_start_ms:
            raise ValueError("validation_end_ms must follow validation_start_ms")
        if self.finalization_not_before_ms < self.validation_end_ms:
            raise ValueError("finalization cannot precede validation end")
        if self.expected_anchor_count <= 0:
            raise ValueError("expected_anchor_count must be positive")
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported clean evidence manifest schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "model_payload_sha256": self.model_payload_sha256,
            "markets": self.markets,
            "active_horizons": self.active_horizons,
            "validation_start_ms": self.validation_start_ms,
            "validation_end_ms": self.validation_end_ms,
            "finalization_not_before_ms": self.finalization_not_before_ms,
            "expected_anchor_count": self.expected_anchor_count,
            "schema_version": self.schema_version,
        }

    @property
    def campaign_id(self) -> str:
        return _sha256(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "campaign_id": self.campaign_id}


@dataclass(frozen=True, slots=True)
class ArchiveCleanFeatureRef:
    market: str
    feature_id: str
    anchor_end_ms: int
    anchor_close_px: Decimal
    source_retrieved_at_ms: int
    source_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.market.strip():
            raise ValueError("feature market must not be empty")
        _require_id24(self.feature_id, "feature_id")
        if self.anchor_end_ms < 0:
            raise ValueError("feature anchor_end_ms must be non-negative")
        if not self.anchor_close_px.is_finite() or self.anchor_close_px <= ZERO:
            raise ValueError("feature anchor_close_px must be positive finite")
        if self.source_retrieved_at_ms < self.anchor_end_ms:
            raise ValueError("prospective feature source cannot precede anchor close")
        if (
            tuple(sorted(set(self.source_manifest_ids))) != self.source_manifest_ids
            or not self.source_manifest_ids
            or any(not item.strip() for item in self.source_manifest_ids)
        ):
            raise ValueError("source_manifest_ids must be sorted unique and non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "feature_id": self.feature_id,
            "anchor_end_ms": self.anchor_end_ms,
            "anchor_close_px": str(self.anchor_close_px),
            "source_retrieved_at_ms": self.source_retrieved_at_ms,
            "source_manifest_ids": self.source_manifest_ids,
        }


@dataclass(frozen=True, slots=True)
class ArchiveCleanSignalEvidence:
    candidate_id: str
    validation_spec_id: str
    model_artifact_id: str
    feature_id: str
    market: str
    anchor_end_ms: int
    horizon_ms: int
    target_end_ms: int
    direction: Direction
    expected_long_gross_return: Decimal
    expected_short_gross_return: Decimal
    expected_long_net_return: Decimal
    expected_short_net_return: Decimal
    expected_net_edge: Decimal
    cost_fraction: Decimal
    threshold: Decimal | None
    sample_count: int
    estimate_source: str
    reason_codes: tuple[str, ...]
    entry_px: Decimal
    disposition: str
    paper_only: bool = True

    def __post_init__(self) -> None:
        for field in (
            "candidate_id",
            "validation_spec_id",
            "model_artifact_id",
        ):
            _require_sha256(getattr(self, field), field)
        _require_id24(self.feature_id, "feature_id")
        if not self.market.strip():
            raise ValueError("signal market must not be empty")
        if self.anchor_end_ms < 0 or self.horizon_ms <= 0:
            raise ValueError("invalid signal timing")
        if self.target_end_ms != self.anchor_end_ms + self.horizon_ms:
            raise ValueError("signal target must match horizon")
        for field in (
            "expected_long_gross_return",
            "expected_short_gross_return",
            "expected_long_net_return",
            "expected_short_net_return",
            "expected_net_edge",
            "cost_fraction",
        ):
            if not getattr(self, field).is_finite():
                raise ValueError(f"{field} must be finite")
        if self.expected_short_gross_return != -self.expected_long_gross_return:
            raise ValueError("gross signal predictions must be symmetric")
        if self.expected_net_edge != max(
            self.expected_long_net_return,
            self.expected_short_net_return,
        ):
            raise ValueError("signal expected_net_edge must be best directional edge")
        if self.cost_fraction < ZERO:
            raise ValueError("signal cost_fraction must be non-negative")
        if self.threshold is not None and (
            not self.threshold.is_finite() or self.threshold < ZERO
        ):
            raise ValueError("signal threshold must be non-negative finite")
        if self.sample_count <= 0:
            raise ValueError("signal sample_count must be positive")
        if not self.estimate_source.strip():
            raise ValueError("signal estimate_source must not be empty")
        if not self.reason_codes or any(not item.strip() for item in self.reason_codes):
            raise ValueError("signal reason_codes must be non-empty")
        if not self.entry_px.is_finite() or self.entry_px <= ZERO:
            raise ValueError("signal entry_px must be positive finite")
        if self.disposition not in SIGNAL_DISPOSITIONS:
            raise ValueError("unsupported signal disposition")
        if self.disposition == "accepted" and self.direction is Direction.NO_TRADE:
            raise ValueError("accepted signal must be directional")
        if self.direction is Direction.NO_TRADE and self.disposition != "raw_no_trade":
            raise ValueError("raw NO_TRADE must use raw_no_trade disposition")
        if not self.paper_only:
            raise ValueError("clean signal evidence must remain paper-only")

    @property
    def accepted(self) -> bool:
        return self.disposition == "accepted"

    def identity_payload(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "validation_spec_id": self.validation_spec_id,
            "model_artifact_id": self.model_artifact_id,
            "feature_id": self.feature_id,
            "market": self.market,
            "anchor_end_ms": self.anchor_end_ms,
            "horizon_ms": self.horizon_ms,
            "target_end_ms": self.target_end_ms,
            "direction": self.direction.value,
            "expected_long_gross_return": str(self.expected_long_gross_return),
            "expected_short_gross_return": str(self.expected_short_gross_return),
            "expected_long_net_return": str(self.expected_long_net_return),
            "expected_short_net_return": str(self.expected_short_net_return),
            "expected_net_edge": str(self.expected_net_edge),
            "cost_fraction": str(self.cost_fraction),
            "threshold": None if self.threshold is None else str(self.threshold),
            "sample_count": self.sample_count,
            "estimate_source": self.estimate_source,
            "reason_codes": self.reason_codes,
            "entry_px": str(self.entry_px),
            "disposition": self.disposition,
            "paper_only": self.paper_only,
        }

    @property
    def signal_id(self) -> str:
        return _sha256(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "signal_id": self.signal_id}


@dataclass(frozen=True, slots=True)
class ArchiveCleanAnchorObservation:
    validation_spec_id: str
    candidate_id: str
    model_artifact_id: str
    anchor_end_ms: int
    decision_as_of_ms: int
    features: tuple[ArchiveCleanFeatureRef, ...]
    signals: tuple[ArchiveCleanSignalEvidence, ...]
    state_before: ArchivePaperState
    state_after: ArchivePaperState
    schema_version: int = ANCHOR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in ("validation_spec_id", "candidate_id", "model_artifact_id"):
            _require_sha256(getattr(self, field), field)
        if self.anchor_end_ms < 0 or self.decision_as_of_ms < self.anchor_end_ms:
            raise ValueError("invalid anchor observation timing")
        feature_markets = tuple(item.market for item in self.features)
        if (
            feature_markets != tuple(sorted(set(feature_markets)))
            or not feature_markets
        ):
            raise ValueError("observation features must be sorted unique by market")
        if any(item.anchor_end_ms != self.anchor_end_ms for item in self.features):
            raise ValueError("feature anchor mismatch")
        if any(
            item.source_retrieved_at_ms > self.decision_as_of_ms
            for item in self.features
        ):
            raise ValueError("feature source was retrieved after decision")
        signal_keys = tuple((item.market, item.horizon_ms) for item in self.signals)
        if (
            signal_keys != tuple(sorted(set(signal_keys)))
            or not signal_keys
        ):
            raise ValueError("observation signals must be sorted unique")
        if any(item.anchor_end_ms != self.anchor_end_ms for item in self.signals):
            raise ValueError("signal anchor mismatch")
        if any(
            item.validation_spec_id != self.validation_spec_id
            or item.candidate_id != self.candidate_id
            or item.model_artifact_id != self.model_artifact_id
            for item in self.signals
        ):
            raise ValueError("signal lineage mismatch")
        feature_ids = {item.market: item.feature_id for item in self.features}
        if any(feature_ids.get(item.market) != item.feature_id for item in self.signals):
            raise ValueError("signal feature lineage mismatch")
        if self.schema_version != ANCHOR_SCHEMA_VERSION:
            raise ValueError("unsupported clean anchor observation schema")

    @property
    def accepted_signals(self) -> tuple[ArchiveCleanSignalEvidence, ...]:
        return tuple(item for item in self.signals if item.accepted)

    @property
    def state_before_sha256(self) -> str:
        return _sha256(_state_payload(self.state_before))

    @property
    def state_after_sha256(self) -> str:
        return _sha256(_state_payload(self.state_after))

    def identity_payload(self) -> dict[str, object]:
        return {
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "anchor_end_ms": self.anchor_end_ms,
            "decision_as_of_ms": self.decision_as_of_ms,
            "features": tuple(item.to_dict() for item in self.features),
            "signals": tuple(item.to_dict() for item in self.signals),
            "state_before": _state_payload(self.state_before),
            "state_before_sha256": self.state_before_sha256,
            "state_after": _state_payload(self.state_after),
            "state_after_sha256": self.state_after_sha256,
            "schema_version": self.schema_version,
        }

    @property
    def observation_id(self) -> str:
        return _sha256(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "observation_id": self.observation_id}


@dataclass(frozen=True, slots=True)
class ArchiveCleanOutcome:
    validation_spec_id: str
    candidate_id: str
    model_artifact_id: str
    anchor_observation_id: str
    signal_id: str
    market: str
    anchor_end_ms: int
    target_end_ms: int
    horizon_ms: int
    direction: Direction
    entry_px: Decimal
    exit_px: Decimal
    exit_candle_id: str
    exit_source_received_at_ms: int
    gross_return: Decimal
    modeled_cost_fraction: Decimal
    net_return: Decimal
    schema_version: int = OUTCOME_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "validation_spec_id",
            "candidate_id",
            "model_artifact_id",
            "anchor_observation_id",
            "signal_id",
        ):
            _require_sha256(getattr(self, field), field)
        if not self.market.strip():
            raise ValueError("outcome market must not be empty")
        if self.anchor_end_ms < 0 or self.target_end_ms <= self.anchor_end_ms:
            raise ValueError("invalid outcome timing")
        if self.horizon_ms != self.target_end_ms - self.anchor_end_ms:
            raise ValueError("outcome horizon must match timing")
        if self.direction not in {Direction.LONG, Direction.SHORT}:
            raise ValueError("outcome requires directional signal")
        for field in ("entry_px", "exit_px"):
            value = getattr(self, field)
            if not value.is_finite() or value <= ZERO:
                raise ValueError(f"{field} must be positive finite")
        _require_id24(self.exit_candle_id, "exit_candle_id")
        if self.exit_source_received_at_ms < self.target_end_ms:
            raise ValueError("exit source must be received after target close")
        for field in ("gross_return", "modeled_cost_fraction", "net_return"):
            if not getattr(self, field).is_finite():
                raise ValueError(f"{field} must be finite")
        if self.modeled_cost_fraction < ZERO:
            raise ValueError("modeled_cost_fraction must be non-negative")
        if self.net_return != self.gross_return - self.modeled_cost_fraction:
            raise ValueError("net_return must equal gross return minus modeled cost")
        if self.schema_version != OUTCOME_SCHEMA_VERSION:
            raise ValueError("unsupported clean outcome schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "anchor_observation_id": self.anchor_observation_id,
            "signal_id": self.signal_id,
            "market": self.market,
            "anchor_end_ms": self.anchor_end_ms,
            "target_end_ms": self.target_end_ms,
            "horizon_ms": self.horizon_ms,
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
        return _sha256(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "outcome_id": self.outcome_id}


@dataclass(frozen=True, slots=True)
class ArchiveCleanCaptureSummary:
    as_of_ms: int
    expected_elapsed_anchor_count: int
    captured_elapsed_anchor_count: int
    missing_anchor_end_ms: tuple[int, ...]
    capture_coverage: Decimal | None
    validation_window_complete: bool
    schema_version: int = CAPTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.expected_elapsed_anchor_count < 0:
            raise ValueError("expected_elapsed_anchor_count must be non-negative")
        if self.captured_elapsed_anchor_count < 0:
            raise ValueError("captured_elapsed_anchor_count must be non-negative")
        if self.captured_elapsed_anchor_count > self.expected_elapsed_anchor_count:
            raise ValueError("captured anchors cannot exceed expected anchors")
        if tuple(sorted(set(self.missing_anchor_end_ms))) != self.missing_anchor_end_ms:
            raise ValueError("missing anchors must be sorted unique")
        if (
            len(self.missing_anchor_end_ms)
            != self.expected_elapsed_anchor_count - self.captured_elapsed_anchor_count
        ):
            raise ValueError("missing anchor count mismatch")
        if self.capture_coverage is None:
            if self.expected_elapsed_anchor_count != 0:
                raise ValueError("coverage required when anchors are expected")
        elif (
            not self.capture_coverage.is_finite()
            or self.capture_coverage < ZERO
            or self.capture_coverage > ONE
        ):
            raise ValueError("capture_coverage must be between zero and one")
        if self.schema_version != CAPTURE_SCHEMA_VERSION:
            raise ValueError("unsupported capture summary schema")


def _feature_ref(feature: HistoricalFeatureRow) -> ArchiveCleanFeatureRef:
    return ArchiveCleanFeatureRef(
        market=feature.market.canonical,
        feature_id=feature.row_id,
        anchor_end_ms=feature.anchor_end_ms,
        anchor_close_px=feature.anchor_close_px,
        source_retrieved_at_ms=feature.source_retrieved_at_ms,
        source_manifest_ids=feature.source_manifest_ids,
    )


def _signal_evidence(
    signal: ArchivePaperSignal,
    feature: ArchiveCleanFeatureRef,
    *,
    disposition: str,
) -> ArchiveCleanSignalEvidence:
    return ArchiveCleanSignalEvidence(
        candidate_id=signal.candidate_id,
        validation_spec_id=signal.validation_spec_id,
        model_artifact_id=signal.model_artifact_id,
        feature_id=feature.feature_id,
        market=signal.market,
        anchor_end_ms=signal.anchor_end_ms,
        horizon_ms=signal.horizon_ms,
        target_end_ms=signal.target_end_ms,
        direction=signal.direction,
        expected_long_gross_return=signal.expected_long_gross_return,
        expected_short_gross_return=signal.expected_short_gross_return,
        expected_long_net_return=signal.expected_long_net_return,
        expected_short_net_return=signal.expected_short_net_return,
        expected_net_edge=signal.expected_net_edge,
        cost_fraction=signal.cost_fraction,
        threshold=signal.threshold,
        sample_count=signal.sample_count,
        estimate_source=signal.estimate_source,
        reason_codes=signal.reason_codes,
        entry_px=feature.anchor_close_px,
        disposition=disposition,
        paper_only=signal.paper_only,
    )


def build_archive_clean_anchor_observation(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    features: tuple[HistoricalFeatureRow, ...],
    state_before: ArchivePaperState,
    result: ArchivePaperAnchorResult,
) -> ArchiveCleanAnchorObservation:
    if result.anchor_end_ms < spec.first_expected_anchor_ms:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_ANCHOR_BEFORE_WINDOW"
        )
    if result.anchor_end_ms >= spec.validation_end_ms:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_ANCHOR_AFTER_WINDOW"
        )
    feature_refs = tuple(_feature_ref(item) for item in features)
    feature_markets = tuple(item.market for item in feature_refs)
    if feature_markets != spec.markets:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_MARKET_COVERAGE_MISMATCH"
        )
    if any(item.anchor_end_ms != result.anchor_end_ms for item in feature_refs):
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_FEATURE_ANCHOR_MISMATCH"
        )
    if (
        result.anchor_end_ms % spec.anchor_interval_ms
        != spec.anchor_end_offset_ms
    ):
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_ANCHOR_NOT_ALIGNED"
        )
    expected_keys = tuple(
        (market, horizon_ms)
        for market in spec.markets
        for horizon_ms in spec.active_horizons
    )
    raw_keys = tuple(
        sorted((item.market, item.horizon_ms) for item in result.raw_signals)
    )
    if raw_keys != tuple(sorted(expected_keys)):
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_RAW_SIGNAL_COVERAGE_MISMATCH"
        )
    accepted_keys = {
        (item.market, item.horizon_ms)
        for item in result.accepted_signals
    }
    feature_by_market = {item.market: item for item in feature_refs}
    occupied = set(result.occupied_skip_markets)
    capacity = set(result.capacity_skip_markets)
    no_trade = set(result.no_trade_markets)
    signals: list[ArchiveCleanSignalEvidence] = []
    for signal in sorted(
        result.raw_signals,
        key=lambda item: (item.market, item.horizon_ms),
    ):
        key = (signal.market, signal.horizon_ms)
        if key in accepted_keys:
            disposition = "accepted"
        elif signal.direction is Direction.NO_TRADE:
            disposition = "raw_no_trade"
        elif signal.market in occupied:
            disposition = "occupied_skip"
        elif signal.market in capacity:
            disposition = "capacity_skip"
        else:
            disposition = "not_selected_horizon"
        signals.append(
            _signal_evidence(
                signal,
                feature_by_market[signal.market],
                disposition=disposition,
            )
        )

    accepted_signal_ids = {
        item.signal_id for item in signals if item.accepted
    }
    if len(accepted_signal_ids) != len(result.accepted_signals):
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_ACCEPTED_SIGNAL_MISMATCH"
        )
    if set(no_trade) != {
        market
        for market in spec.markets
        if not any(
            item.market == market and item.direction is not Direction.NO_TRADE
            for item in result.raw_signals
        )
    }:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_EVIDENCE_NO_TRADE_MARKETS_MISMATCH"
        )

    decision_as_of_ms = max(item.source_retrieved_at_ms for item in feature_refs)
    return ArchiveCleanAnchorObservation(
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        model_artifact_id=spec.model_artifact_id,
        anchor_end_ms=result.anchor_end_ms,
        decision_as_of_ms=decision_as_of_ms,
        features=feature_refs,
        signals=tuple(signals),
        state_before=state_before.active_at(result.anchor_end_ms),
        state_after=result.next_state,
    )


def build_archive_clean_outcome(
    spec: HistoricalArchiveCleanValidationSpec,
    *,
    observation: ArchiveCleanAnchorObservation,
    signal: ArchiveCleanSignalEvidence,
    exit_candle: Candle,
    as_of_ms: int,
) -> ArchiveCleanOutcome:
    if observation.validation_spec_id != spec.spec_id:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_OBSERVATION_SPEC_MISMATCH"
        )
    if signal not in observation.accepted_signals:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_SIGNAL_NOT_ACCEPTED"
        )
    if signal.direction not in {Direction.LONG, Direction.SHORT}:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_SIGNAL_NOT_DIRECTIONAL"
        )
    if exit_candle.market.canonical != signal.market:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_MARKET_MISMATCH"
        )
    if exit_candle.interval != spec.anchor_interval:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_INTERVAL_MISMATCH"
        )
    if exit_candle.end_ms != signal.target_end_ms:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_TARGET_MISMATCH"
        )
    if exit_candle.received_at_ms > as_of_ms:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_RECEIVED_AFTER_AS_OF"
        )
    if exit_candle.received_at_ms < exit_candle.end_ms:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_RECEIVED_BEFORE_CLOSE"
        )
    if not exit_candle.close_px.is_finite() or exit_candle.close_px <= ZERO:
        raise HistoricalArchiveCleanEvidenceError(
            "CLEAN_OUTCOME_EXIT_PRICE_INVALID"
        )
    long_return = exit_candle.close_px / signal.entry_px - ONE
    gross = long_return if signal.direction is Direction.LONG else -long_return
    return ArchiveCleanOutcome(
        validation_spec_id=spec.spec_id,
        candidate_id=spec.candidate_id,
        model_artifact_id=spec.model_artifact_id,
        anchor_observation_id=observation.observation_id,
        signal_id=signal.signal_id,
        market=signal.market,
        anchor_end_ms=signal.anchor_end_ms,
        target_end_ms=signal.target_end_ms,
        horizon_ms=signal.horizon_ms,
        direction=signal.direction,
        entry_px=signal.entry_px,
        exit_px=exit_candle.close_px,
        exit_candle_id=_candle_id(exit_candle),
        exit_source_received_at_ms=exit_candle.received_at_ms,
        gross_return=gross,
        modeled_cost_fraction=signal.cost_fraction,
        net_return=gross - signal.cost_fraction,
    )


def _feature_ref_from_payload(value: object) -> ArchiveCleanFeatureRef:
    raw = _mapping(value, "feature ref")
    return ArchiveCleanFeatureRef(
        market=_string(raw.get("market"), "feature market"),
        feature_id=_string(raw.get("feature_id"), "feature_id"),
        anchor_end_ms=_integer(raw.get("anchor_end_ms"), "feature anchor_end_ms"),
        anchor_close_px=_decimal(raw.get("anchor_close_px"), "feature anchor_close_px"),
        source_retrieved_at_ms=_integer(
            raw.get("source_retrieved_at_ms"),
            "feature source_retrieved_at_ms",
        ),
        source_manifest_ids=tuple(
            _string(item, "source manifest id")
            for item in _sequence(
                raw.get("source_manifest_ids"),
                "source_manifest_ids",
            )
        ),
    )


def _signal_from_payload(value: object) -> ArchiveCleanSignalEvidence:
    raw = _mapping(value, "signal evidence")
    return ArchiveCleanSignalEvidence(
        candidate_id=_string(raw.get("candidate_id"), "signal candidate_id"),
        validation_spec_id=_string(
            raw.get("validation_spec_id"),
            "signal validation_spec_id",
        ),
        model_artifact_id=_string(
            raw.get("model_artifact_id"),
            "signal model_artifact_id",
        ),
        feature_id=_string(raw.get("feature_id"), "signal feature_id"),
        market=_string(raw.get("market"), "signal market"),
        anchor_end_ms=_integer(raw.get("anchor_end_ms"), "signal anchor_end_ms"),
        horizon_ms=_integer(raw.get("horizon_ms"), "signal horizon_ms"),
        target_end_ms=_integer(raw.get("target_end_ms"), "signal target_end_ms"),
        direction=Direction(_string(raw.get("direction"), "signal direction")),
        expected_long_gross_return=_decimal(
            raw.get("expected_long_gross_return"),
            "signal expected_long_gross_return",
        ),
        expected_short_gross_return=_decimal(
            raw.get("expected_short_gross_return"),
            "signal expected_short_gross_return",
        ),
        expected_long_net_return=_decimal(
            raw.get("expected_long_net_return"),
            "signal expected_long_net_return",
        ),
        expected_short_net_return=_decimal(
            raw.get("expected_short_net_return"),
            "signal expected_short_net_return",
        ),
        expected_net_edge=_decimal(
            raw.get("expected_net_edge"),
            "signal expected_net_edge",
        ),
        cost_fraction=_decimal(raw.get("cost_fraction"), "signal cost_fraction"),
        threshold=_optional_decimal(raw.get("threshold"), "signal threshold"),
        sample_count=_integer(raw.get("sample_count"), "signal sample_count"),
        estimate_source=_string(
            raw.get("estimate_source"),
            "signal estimate_source",
        ),
        reason_codes=tuple(
            _string(item, "signal reason_code")
            for item in _sequence(raw.get("reason_codes"), "signal reason_codes")
        ),
        entry_px=_decimal(raw.get("entry_px"), "signal entry_px"),
        disposition=_string(raw.get("disposition"), "signal disposition"),
        paper_only=_boolean(raw.get("paper_only"), "signal paper_only"),
    )


def _anchor_from_payload(value: object) -> ArchiveCleanAnchorObservation:
    raw = _mapping(value, "anchor observation")
    observation = ArchiveCleanAnchorObservation(
        validation_spec_id=_string(
            raw.get("validation_spec_id"),
            "anchor validation_spec_id",
        ),
        candidate_id=_string(raw.get("candidate_id"), "anchor candidate_id"),
        model_artifact_id=_string(
            raw.get("model_artifact_id"),
            "anchor model_artifact_id",
        ),
        anchor_end_ms=_integer(raw.get("anchor_end_ms"), "anchor_end_ms"),
        decision_as_of_ms=_integer(
            raw.get("decision_as_of_ms"),
            "decision_as_of_ms",
        ),
        features=tuple(
            _feature_ref_from_payload(item)
            for item in _sequence(raw.get("features"), "anchor features")
        ),
        signals=tuple(
            _signal_from_payload(item)
            for item in _sequence(raw.get("signals"), "anchor signals")
        ),
        state_before=_state_from_payload(raw.get("state_before"), "state_before"),
        state_after=_state_from_payload(raw.get("state_after"), "state_after"),
        schema_version=_integer(raw.get("schema_version"), "anchor schema_version"),
    )
    if _string(raw.get("state_before_sha256"), "state_before_sha256") != (
        observation.state_before_sha256
    ):
        raise HistoricalArchiveCleanEvidenceConsistencyError(
            "CLEAN_EVIDENCE_STATE_BEFORE_DIGEST_MISMATCH"
        )
    if _string(raw.get("state_after_sha256"), "state_after_sha256") != (
        observation.state_after_sha256
    ):
        raise HistoricalArchiveCleanEvidenceConsistencyError(
            "CLEAN_EVIDENCE_STATE_AFTER_DIGEST_MISMATCH"
        )
    if _string(raw.get("observation_id"), "observation_id") != (
        observation.observation_id
    ):
        raise HistoricalArchiveCleanEvidenceConsistencyError(
            "CLEAN_EVIDENCE_OBSERVATION_ID_MISMATCH"
        )
    for signal_raw, signal in zip(
        _sequence(raw.get("signals"), "anchor signals"),
        observation.signals,
        strict=True,
    ):
        if _string(
            _mapping(signal_raw, "signal evidence").get("signal_id"),
            "signal_id",
        ) != signal.signal_id:
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_SIGNAL_ID_MISMATCH"
            )
    return observation


def _outcome_from_payload(value: object) -> ArchiveCleanOutcome:
    raw = _mapping(value, "clean outcome")
    outcome = ArchiveCleanOutcome(
        validation_spec_id=_string(
            raw.get("validation_spec_id"),
            "outcome validation_spec_id",
        ),
        candidate_id=_string(raw.get("candidate_id"), "outcome candidate_id"),
        model_artifact_id=_string(
            raw.get("model_artifact_id"),
            "outcome model_artifact_id",
        ),
        anchor_observation_id=_string(
            raw.get("anchor_observation_id"),
            "anchor_observation_id",
        ),
        signal_id=_string(raw.get("signal_id"), "outcome signal_id"),
        market=_string(raw.get("market"), "outcome market"),
        anchor_end_ms=_integer(raw.get("anchor_end_ms"), "outcome anchor_end_ms"),
        target_end_ms=_integer(raw.get("target_end_ms"), "outcome target_end_ms"),
        horizon_ms=_integer(raw.get("horizon_ms"), "outcome horizon_ms"),
        direction=Direction(_string(raw.get("direction"), "outcome direction")),
        entry_px=_decimal(raw.get("entry_px"), "outcome entry_px"),
        exit_px=_decimal(raw.get("exit_px"), "outcome exit_px"),
        exit_candle_id=_string(raw.get("exit_candle_id"), "exit_candle_id"),
        exit_source_received_at_ms=_integer(
            raw.get("exit_source_received_at_ms"),
            "exit_source_received_at_ms",
        ),
        gross_return=_decimal(raw.get("gross_return"), "outcome gross_return"),
        modeled_cost_fraction=_decimal(
            raw.get("modeled_cost_fraction"),
            "modeled_cost_fraction",
        ),
        net_return=_decimal(raw.get("net_return"), "outcome net_return"),
        schema_version=_integer(raw.get("schema_version"), "outcome schema_version"),
    )
    if _string(raw.get("outcome_id"), "outcome_id") != outcome.outcome_id:
        raise HistoricalArchiveCleanEvidenceConsistencyError(
            "CLEAN_EVIDENCE_OUTCOME_ID_MISMATCH"
        )
    return outcome


class ArchiveCleanEvidenceStore:
    def __init__(
        self,
        root: str | Path,
        *,
        spec: HistoricalArchiveCleanValidationSpec,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.spec = spec
        self.manifest = ArchiveCleanCampaignManifest(
            validation_spec_id=spec.spec_id,
            candidate_id=spec.candidate_id,
            model_artifact_id=spec.model_artifact_id,
            model_payload_sha256=spec.model_payload_sha256,
            markets=spec.markets,
            active_horizons=spec.active_horizons,
            validation_start_ms=spec.validation_start_ms,
            validation_end_ms=spec.validation_end_ms,
            finalization_not_before_ms=spec.finalization_not_before_ms,
            expected_anchor_count=spec.expected_anchor_count,
        )
        self.manifest_path = self.root / "manifest.json"
        self._ensure_manifest()

    @staticmethod
    def _date_path(timestamp_ms: int) -> str:
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date().isoformat()

    def _anchor_path(self, anchor_end_ms: int) -> Path:
        return (
            self.root
            / "anchors"
            / self._date_path(anchor_end_ms)
            / f"{anchor_end_ms}.json"
        )

    def _outcome_path(self, outcome: ArchiveCleanOutcome) -> Path:
        return (
            self.root
            / "outcomes"
            / self._date_path(outcome.target_end_ms)
            / f"{outcome.outcome_id}.json"
        )

    @staticmethod
    def _write_consistent(path: Path, payload: dict[str, object]) -> Path:
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    f"conflicting clean evidence record: {path.name}"
                )
            return path
        try:
            with path.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    f"conflicting clean evidence record: {path.name}"
                ) from None
        return path

    def _ensure_manifest(self) -> None:
        expected = (_canonical_json(self.manifest.to_dict()) + "\n").encode("utf-8")
        if self.manifest_path.exists():
            if self.manifest_path.read_bytes() != expected:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    "CLEAN_EVIDENCE_MANIFEST_CONFLICT"
                )
            return
        self._write_consistent(self.manifest_path, self.manifest.to_dict())

    def record_anchor(
        self,
        observation: ArchiveCleanAnchorObservation,
    ) -> Path:
        if observation.validation_spec_id != self.spec.spec_id:
            raise ValueError("anchor observation does not belong to clean campaign")
        existing = self.anchor_for_time(observation.anchor_end_ms)
        if existing is not None:
            if existing != observation:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    "CLEAN_EVIDENCE_ANCHOR_CONFLICT"
                )
            return self._anchor_path(observation.anchor_end_ms)

        prior = tuple(
            item
            for item in self.iter_anchors()
            if item.anchor_end_ms < observation.anchor_end_ms
        )
        if prior:
            latest = prior[-1]
            if latest.state_after != observation.state_before:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    "CLEAN_EVIDENCE_STATE_CONTINUITY_MISMATCH"
                )
        elif observation.state_before != ArchivePaperState():
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_INITIAL_STATE_NOT_EMPTY"
            )
        return self._write_consistent(
            self._anchor_path(observation.anchor_end_ms),
            observation.to_dict(),
        )

    def record_anchor_result(
        self,
        *,
        features: tuple[HistoricalFeatureRow, ...],
        state_before: ArchivePaperState,
        result: ArchivePaperAnchorResult,
    ) -> ArchiveCleanAnchorObservation:
        observation = build_archive_clean_anchor_observation(
            self.spec,
            features=features,
            state_before=state_before,
            result=result,
        )
        self.record_anchor(observation)
        return observation

    def record_outcome(self, outcome: ArchiveCleanOutcome) -> Path:
        if outcome.validation_spec_id != self.spec.spec_id:
            raise ValueError("outcome does not belong to clean campaign")
        observation = self.load_anchor(outcome.anchor_observation_id)
        if observation is None:
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_OUTCOME_ANCHOR_MISSING"
            )
        signal = next(
            (
                item
                for item in observation.accepted_signals
                if item.signal_id == outcome.signal_id
            ),
            None,
        )
        if signal is None:
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_OUTCOME_SIGNAL_MISSING"
            )
        existing = tuple(
            item
            for item in self.iter_outcomes()
            if item.signal_id == outcome.signal_id
        )
        if existing:
            if existing[0] != outcome or len(existing) != 1:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    "CLEAN_EVIDENCE_OUTCOME_CONFLICT"
                )
            return self._outcome_path(existing[0])
        return self._write_consistent(self._outcome_path(outcome), outcome.to_dict())

    def anchor_for_time(
        self,
        anchor_end_ms: int,
    ) -> ArchiveCleanAnchorObservation | None:
        path = self._anchor_path(anchor_end_ms)
        if not path.exists():
            return None
        return self._load_anchor_path(path)

    def load_anchor(
        self,
        observation_id: str,
    ) -> ArchiveCleanAnchorObservation | None:
        for path in sorted((self.root / "anchors").glob("*/*.json")):
            observation = self._load_anchor_path(path)
            if observation.observation_id == observation_id:
                return observation
        return None

    def iter_anchors(self) -> tuple[ArchiveCleanAnchorObservation, ...]:
        root = self.root / "anchors"
        if not root.exists():
            return ()
        values = tuple(
            self._load_anchor_path(path)
            for path in sorted(root.glob("*/*.json"))
        )
        ordered = tuple(sorted(values, key=lambda item: item.anchor_end_ms))
        if len({item.anchor_end_ms for item in ordered}) != len(ordered):
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_DUPLICATE_ANCHOR"
            )
        for previous, current in zip(ordered, ordered[1:]):
            if previous.state_after != current.state_before:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    "CLEAN_EVIDENCE_STATE_CONTINUITY_MISMATCH"
                )
        return ordered

    def iter_outcomes(self) -> tuple[ArchiveCleanOutcome, ...]:
        root = self.root / "outcomes"
        if not root.exists():
            return ()
        values = tuple(
            self._load_outcome_path(path)
            for path in sorted(root.glob("*/*.json"))
        )
        signal_ids = tuple(item.signal_id for item in values)
        if len(set(signal_ids)) != len(signal_ids):
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_DUPLICATE_SIGNAL_OUTCOME"
            )
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.target_end_ms,
                    item.market,
                    item.horizon_ms,
                    item.signal_id,
                ),
            )
        )

    def latest_state(self) -> ArchivePaperState:
        anchors = self.iter_anchors()
        return ArchivePaperState() if not anchors else anchors[-1].state_after

    def due_unsettled_signals(
        self,
        *,
        as_of_ms: int,
    ) -> tuple[tuple[ArchiveCleanAnchorObservation, ArchiveCleanSignalEvidence], ...]:
        settled = {item.signal_id for item in self.iter_outcomes()}
        due: list[
            tuple[ArchiveCleanAnchorObservation, ArchiveCleanSignalEvidence]
        ] = []
        for observation in self.iter_anchors():
            for signal in observation.accepted_signals:
                if signal.target_end_ms <= as_of_ms and signal.signal_id not in settled:
                    due.append((observation, signal))
        return tuple(
            sorted(
                due,
                key=lambda item: (
                    item[1].target_end_ms,
                    item[1].market,
                    item[1].horizon_ms,
                    item[1].signal_id,
                ),
            )
        )

    def capture_summary(self, *, as_of_ms: int) -> ArchiveCleanCaptureSummary:
        upper = min(as_of_ms, self.spec.validation_end_ms - 1)
        expected: list[int] = []
        cursor = self.spec.first_expected_anchor_ms
        while cursor <= upper:
            expected.append(cursor)
            cursor += self.spec.anchor_interval_ms
        captured = {
            item.anchor_end_ms
            for item in self.iter_anchors()
            if item.anchor_end_ms <= upper
        }
        missing = tuple(value for value in expected if value not in captured)
        expected_count = len(expected)
        captured_count = expected_count - len(missing)
        coverage = (
            None
            if expected_count == 0
            else Decimal(captured_count) / Decimal(expected_count)
        )
        return ArchiveCleanCaptureSummary(
            as_of_ms=as_of_ms,
            expected_elapsed_anchor_count=expected_count,
            captured_elapsed_anchor_count=captured_count,
            missing_anchor_end_ms=missing,
            capture_coverage=coverage,
            validation_window_complete=as_of_ms >= self.spec.validation_end_ms,
        )

    def _load_anchor_path(self, path: Path) -> ArchiveCleanAnchorObservation:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_ANCHOR_INVALID"
            ) from exc
        observation = _anchor_from_payload(raw)
        if observation.validation_spec_id != self.spec.spec_id:
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_ANCHOR_SPEC_MISMATCH"
            )
        if path.name != f"{observation.anchor_end_ms}.json":
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_ANCHOR_PATH_MISMATCH"
            )
        if path.read_text(encoding="utf-8") != _canonical_json(
            observation.to_dict()
        ) + "\n":
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_ANCHOR_NON_CANONICAL"
            )
        return observation

    def _load_outcome_path(self, path: Path) -> ArchiveCleanOutcome:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_OUTCOME_INVALID"
            ) from exc
        outcome = _outcome_from_payload(raw)
        if outcome.validation_spec_id != self.spec.spec_id:
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_OUTCOME_SPEC_MISMATCH"
            )
        if path.name != f"{outcome.outcome_id}.json":
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_OUTCOME_PATH_MISMATCH"
            )
        if path.read_text(encoding="utf-8") != _canonical_json(
            outcome.to_dict()
        ) + "\n":
            raise HistoricalArchiveCleanEvidenceConsistencyError(
                "CLEAN_EVIDENCE_OUTCOME_NON_CANONICAL"
            )
        return outcome
