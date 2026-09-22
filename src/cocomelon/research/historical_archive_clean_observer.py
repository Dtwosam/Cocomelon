from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cocomelon.domain.market import Candle, FundingRate, MarketId
from cocomelon.hyperliquid.normalize import (
    normalize_candles,
    normalize_funding_history,
)
from cocomelon.research.historical_archive_clean_evidence import (
    ArchiveCleanAnchorObservation,
    ArchiveCleanEvidenceStore,
    ArchiveCleanOutcome,
    ArchiveCleanSignalEvidence,
    build_archive_clean_outcome,
)
from cocomelon.research.historical_archive_model_artifact import (
    HistoricalArchiveCandidateModelArtifact,
    load_archive_candidate_model_artifact,
)
from cocomelon.research.historical_archive_paper_scorer import (
    score_archive_candidate_anchor,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
    load_archive_clean_validation_spec,
)
from cocomelon.research.historical_cross_market import (
    enrich_feature_rows_with_basket_context,
)
from cocomelon.research.historical_features import (
    HistoricalFeatureRow,
    build_historical_feature_rows,
)
from cocomelon.research.historical_learning import FUNDING_INTERVAL_MS
from cocomelon.research.prospective_context_evidence import (
    MAX_ENTRY_CANDLE_AGE_MS,
)

HOUR_MS = 3_600_000
FIVE_MIN_MS = 300_000
FIFTEEN_MIN_MS = 900_000
FEATURE_LOOKBACK_MS = 6 * HOUR_MS
FUNDING_LOOKBACK_MS = 3 * FUNDING_INTERVAL_MS
SOURCE_CAPTURE_SCHEMA_VERSION = 1


class HistoricalArchiveCleanObserverError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveCleanFrozenRuntime:
    artifact: HistoricalArchiveCandidateModelArtifact
    spec: HistoricalArchiveCleanValidationSpec

    def __post_init__(self) -> None:
        artifact = self.artifact
        spec = self.spec
        if (
            spec.model_artifact_id != artifact.artifact_id
            or spec.model_payload_sha256 != artifact.model_payload_sha256
            or spec.candidate_id != artifact.candidate_id
            or spec.training_plan_id != artifact.training_plan_id
            or spec.calibration_id != artifact.calibration_id
            or spec.model_family != artifact.model_family
            or spec.calibration_variant != artifact.calibration_variant
            or spec.model_format != artifact.model_format
            or spec.horizon_thresholds != artifact.selected_horizon_thresholds
            or spec.allow_coin_calibration != artifact.allow_coin_calibration
            or spec.min_sample_count != artifact.min_sample_count
            or spec.execution_policy != artifact.execution_policy
            or spec.max_concurrent_positions != artifact.max_concurrent_positions
            or spec.costs != artifact.costs
            or spec.validation_start_ms != artifact.validation_not_before_ms
        ):
            raise HistoricalArchiveCleanObserverError(
                "ARCHIVE_CLEAN_RUNTIME_LINEAGE_MISMATCH"
            )
        if (
            not spec.paper_only
            or not spec.prospective_only
            or spec.execution_ready
            or spec.promotion_eligible
            or artifact.execution_ready
            or artifact.promotion_eligible
        ):
            raise HistoricalArchiveCleanObserverError(
                "ARCHIVE_CLEAN_RUNTIME_NOT_PAPER_ONLY"
            )


def load_archive_clean_frozen_runtime(
    output_root: Path,
) -> ArchiveCleanFrozenRuntime:
    artifact = load_archive_candidate_model_artifact(
        output_root / "candidate-model.json"
    )
    spec = load_archive_clean_validation_spec(
        output_root / "candidate-validation-spec.json"
    )
    return ArchiveCleanFrozenRuntime(artifact=artifact, spec=spec)


class ArchiveCleanPublicReader(Protocol):
    def candles(
        self,
        market: MarketId,
        interval: str,
        *,
        start_ms: int,
        end_ms: int,
    ) -> object: ...

    def funding_history(
        self,
        market: MarketId,
        *,
        start_ms: int,
        end_ms: int | None = None,
    ) -> object: ...


class ArchiveCleanEvidenceBackend(Protocol):
    spec: HistoricalArchiveCleanValidationSpec

    def observation_id_for_time(self, anchor_end_ms: int) -> str | None: ...

    def latest_state(self) -> object: ...

    def record_anchor_result(
        self,
        *,
        features: tuple[HistoricalFeatureRow, ...],
        state_before: object,
        result: object,
    ) -> ArchiveCleanAnchorObservation: ...

    def due_unsettled_signals(
        self,
        *,
        as_of_ms: int,
    ) -> tuple[
        tuple[ArchiveCleanAnchorObservation, ArchiveCleanSignalEvidence],
        ...,
    ]: ...

    def record_outcome(self, outcome: ArchiveCleanOutcome) -> object: ...

    def capture_summary(self, *, as_of_ms: int) -> object: ...


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _date_path(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date().isoformat()


def _market(value: str) -> MarketId:
    if ":" not in value:
        return MarketId("", value)
    dex, coin = value.split(":", 1)
    return MarketId(dex, coin)


def _candle_payload(candle: Candle) -> dict[str, object]:
    return {
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


def _funding_payload(rate: FundingRate) -> dict[str, object]:
    return {
        "market": rate.market.canonical,
        "time_ms": rate.time_ms,
        "funding_rate": str(rate.funding_rate),
        "premium": str(rate.premium),
        "source": rate.source,
        "received_at_ms": rate.received_at_ms,
        "schema_version": rate.schema_version,
    }


@dataclass(frozen=True, slots=True)
class ArchiveCleanFeatureSourceCapture:
    validation_spec_id: str
    market: str
    anchor_end_ms: int
    candles_5m: tuple[Candle, ...]
    candles_15m: tuple[Candle, ...]
    funding_rates: tuple[FundingRate, ...]
    schema_version: int = SOURCE_CAPTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.validation_spec_id) != 64:
            raise ValueError("validation_spec_id must be SHA-256")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.anchor_end_ms < 0:
            raise ValueError("anchor_end_ms must be non-negative")
        market = self.market
        if any(item.market.canonical != market for item in self.candles_5m):
            raise ValueError("5m capture market mismatch")
        if any(item.market.canonical != market for item in self.candles_15m):
            raise ValueError("15m capture market mismatch")
        if any(item.market.canonical != market for item in self.funding_rates):
            raise ValueError("funding capture market mismatch")
        if any(item.interval != "5m" for item in self.candles_5m):
            raise ValueError("5m capture interval mismatch")
        if any(item.interval != "15m" for item in self.candles_15m):
            raise ValueError("15m capture interval mismatch")
        if not self.candles_5m or not self.candles_15m:
            raise ValueError("feature capture candles must not be empty")
        if any(item.end_ms > self.anchor_end_ms for item in self.candles_5m):
            raise ValueError("5m capture contains future candle")
        if any(item.end_ms > self.anchor_end_ms for item in self.candles_15m):
            raise ValueError("15m capture contains future candle")
        if any(item.time_ms > self.anchor_end_ms for item in self.funding_rates):
            raise ValueError("funding capture contains future rate")
        if self.schema_version != SOURCE_CAPTURE_SCHEMA_VERSION:
            raise ValueError("unsupported feature source capture schema")

    @property
    def received_at_ms(self) -> int:
        values = [
            *(item.received_at_ms for item in self.candles_5m),
            *(item.received_at_ms for item in self.candles_15m),
            *(item.received_at_ms for item in self.funding_rates),
        ]
        return max(values)

    def identity_payload(self) -> dict[str, object]:
        return {
            "kind": "archive_clean_feature_source",
            "validation_spec_id": self.validation_spec_id,
            "market": self.market,
            "anchor_end_ms": self.anchor_end_ms,
            "candles_5m": tuple(_candle_payload(item) for item in self.candles_5m),
            "candles_15m": tuple(
                _candle_payload(item) for item in self.candles_15m
            ),
            "funding_rates": tuple(
                _funding_payload(item) for item in self.funding_rates
            ),
            "received_at_ms": self.received_at_ms,
            "schema_version": self.schema_version,
        }

    @property
    def capture_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "capture_id": self.capture_id}


@dataclass(frozen=True, slots=True)
class ArchiveCleanSettlementSourceCapture:
    validation_spec_id: str
    market: str
    requested_start_ms: int
    requested_end_ms: int
    received_at_ms: int
    candles: tuple[Candle, ...]
    schema_version: int = SOURCE_CAPTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.validation_spec_id) != 64:
            raise ValueError("validation_spec_id must be SHA-256")
        if not self.market.strip():
            raise ValueError("market must not be empty")
        if self.requested_start_ms < 0:
            raise ValueError("requested_start_ms must be non-negative")
        if self.requested_end_ms < self.requested_start_ms:
            raise ValueError("requested_end_ms must follow requested_start_ms")
        if self.received_at_ms < self.requested_end_ms:
            raise ValueError("settlement capture must be received after requested end")
        if any(item.market.canonical != self.market for item in self.candles):
            raise ValueError("settlement capture market mismatch")
        if any(item.interval != "5m" for item in self.candles):
            raise ValueError("settlement capture interval mismatch")
        if any(item.end_ms > self.requested_end_ms for item in self.candles):
            raise ValueError("settlement capture contains future candle")
        if self.schema_version != SOURCE_CAPTURE_SCHEMA_VERSION:
            raise ValueError("unsupported settlement source capture schema")

    def identity_payload(self) -> dict[str, object]:
        return {
            "kind": "archive_clean_settlement_source",
            "validation_spec_id": self.validation_spec_id,
            "market": self.market,
            "requested_start_ms": self.requested_start_ms,
            "requested_end_ms": self.requested_end_ms,
            "candles": tuple(_candle_payload(item) for item in self.candles),
            "received_at_ms": self.received_at_ms,
            "schema_version": self.schema_version,
        }

    @property
    def capture_id(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.identity_payload()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "capture_id": self.capture_id}


class ArchiveCleanSourceCaptureStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _write_consistent(path: Path, payload: dict[str, object]) -> Path:
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise HistoricalArchiveCleanObserverError(
                    "ARCHIVE_CLEAN_SOURCE_CAPTURE_CONFLICT"
                )
            return path
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return path

    def record_feature(
        self,
        capture: ArchiveCleanFeatureSourceCapture,
    ) -> Path:
        path = (
            self.root
            / "feature"
            / _date_path(capture.anchor_end_ms)
            / f"{capture.capture_id}.json"
        )
        return self._write_consistent(path, capture.to_dict())

    def record_settlement(
        self,
        capture: ArchiveCleanSettlementSourceCapture,
    ) -> Path:
        timestamp_ms = capture.requested_end_ms
        path = (
            self.root
            / "settlement"
            / _date_path(timestamp_ms)
            / f"{capture.capture_id}.json"
        )
        return self._write_consistent(path, capture.to_dict())


@dataclass(frozen=True, slots=True)
class ArchiveCleanFeatureCollection:
    anchor_end_ms: int
    as_of_ms: int
    features: tuple[HistoricalFeatureRow, ...]
    capture_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.anchor_end_ms < 0 or self.as_of_ms < self.anchor_end_ms:
            raise ValueError("invalid feature collection timing")
        markets = tuple(item.market.canonical for item in self.features)
        if markets != tuple(sorted(set(markets))) or not markets:
            raise ValueError("features must be sorted unique by market")
        if any(item.anchor_end_ms != self.anchor_end_ms for item in self.features):
            raise ValueError("feature collection anchor mismatch")
        if any(item.source_retrieved_at_ms > self.as_of_ms for item in self.features):
            raise ValueError("feature source received after collection as_of")
        if (
            self.capture_ids != tuple(sorted(set(self.capture_ids)))
            or not self.capture_ids
        ):
            raise ValueError("capture_ids must be sorted unique and non-empty")


@dataclass(frozen=True, slots=True)
class ArchiveCleanSettlementResult:
    as_of_ms: int
    settled: tuple[ArchiveCleanOutcome, ...]
    missing_signal_ids: tuple[str, ...]
    capture_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("settlement as_of_ms must be non-negative")
        if self.missing_signal_ids != tuple(sorted(set(self.missing_signal_ids))):
            raise ValueError("missing_signal_ids must be sorted unique")
        if self.capture_ids != tuple(sorted(set(self.capture_ids))):
            raise ValueError("capture_ids must be sorted unique")


@dataclass(frozen=True, slots=True)
class ArchiveCleanObserverCycleResult:
    status: str
    cycle_started_ms: int
    anchor_end_ms: int | None
    observation_id: str | None
    settled_outcome_ids: tuple[str, ...]
    missing_settlement_signal_ids: tuple[str, ...]
    capture_coverage: str | None
    expected_elapsed_anchor_count: int
    captured_elapsed_anchor_count: int
    paper_only: bool = True

    def __post_init__(self) -> None:
        if not self.status.strip():
            raise ValueError("status must not be empty")
        if self.cycle_started_ms < 0:
            raise ValueError("cycle_started_ms must be non-negative")
        if not self.paper_only:
            raise ValueError("observer cycle must remain paper-only")


def latest_closed_anchor_ms(
    as_of_ms: int,
    spec: HistoricalArchiveCleanValidationSpec,
) -> int:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    interval = spec.anchor_interval_ms
    candidate = ((as_of_ms + 1) // interval) * interval - 1
    if candidate > as_of_ms:
        candidate -= interval
    return candidate


def _trim_candles(
    candles: Sequence[Candle],
    *,
    anchor_end_ms: int,
) -> tuple[Candle, ...]:
    return tuple(item for item in candles if item.end_ms <= anchor_end_ms)


def _trim_funding(
    rates: Sequence[FundingRate],
    *,
    anchor_end_ms: int,
) -> tuple[FundingRate, ...]:
    return tuple(item for item in rates if item.time_ms <= anchor_end_ms)


def _collect_market_feature_source(
    reader: ArchiveCleanPublicReader,
    *,
    spec: HistoricalArchiveCleanValidationSpec,
    market: MarketId,
    anchor_end_ms: int,
    clock_ms: Callable[[], int],
) -> ArchiveCleanFeatureSourceCapture:
    five_start = max(
        0,
        anchor_end_ms - (2 * FIVE_MIN_MS) + 1,
    )
    raw_5m = reader.candles(
        market,
        "5m",
        start_ms=five_start,
        end_ms=anchor_end_ms,
    )
    received_5m = clock_ms()
    candles_5m = _trim_candles(
        normalize_candles(
            market,
            raw_5m,
            received_at_ms=received_5m,
        ),
        anchor_end_ms=anchor_end_ms,
    )

    fifteen_start = max(0, anchor_end_ms - FEATURE_LOOKBACK_MS)
    raw_15m = reader.candles(
        market,
        "15m",
        start_ms=fifteen_start,
        end_ms=anchor_end_ms,
    )
    received_15m = clock_ms()
    candles_15m = _trim_candles(
        normalize_candles(
            market,
            raw_15m,
            received_at_ms=received_15m,
        ),
        anchor_end_ms=anchor_end_ms,
    )

    funding_start = max(0, anchor_end_ms - FUNDING_LOOKBACK_MS)
    raw_funding = reader.funding_history(
        market,
        start_ms=funding_start,
        end_ms=anchor_end_ms,
    )
    received_funding = clock_ms()
    funding_rates = _trim_funding(
        normalize_funding_history(
            market,
            raw_funding,
            received_at_ms=received_funding,
        ),
        anchor_end_ms=anchor_end_ms,
    )

    if not any(item.end_ms == anchor_end_ms for item in candles_5m):
        raise HistoricalArchiveCleanObserverError(
            f"ARCHIVE_CLEAN_ANCHOR_CANDLE_MISSING:{market.canonical}"
        )
    return ArchiveCleanFeatureSourceCapture(
        validation_spec_id=spec.spec_id,
        market=market.canonical,
        anchor_end_ms=anchor_end_ms,
        candles_5m=candles_5m,
        candles_15m=candles_15m,
        funding_rates=funding_rates,
    )


def collect_archive_clean_features(
    reader: ArchiveCleanPublicReader,
    *,
    spec: HistoricalArchiveCleanValidationSpec,
    anchor_end_ms: int,
    clock_ms: Callable[[], int],
    source_store: ArchiveCleanSourceCaptureStore,
) -> ArchiveCleanFeatureCollection:
    if anchor_end_ms < spec.first_expected_anchor_ms:
        raise HistoricalArchiveCleanObserverError(
            "ARCHIVE_CLEAN_ANCHOR_BEFORE_VALIDATION"
        )
    if anchor_end_ms >= spec.validation_end_ms:
        raise HistoricalArchiveCleanObserverError(
            "ARCHIVE_CLEAN_ANCHOR_AFTER_VALIDATION"
        )
    captures: list[ArchiveCleanFeatureSourceCapture] = []
    base_features: list[HistoricalFeatureRow] = []
    for canonical in spec.markets:
        market = _market(canonical)
        capture = _collect_market_feature_source(
            reader,
            spec=spec,
            market=market,
            anchor_end_ms=anchor_end_ms,
            clock_ms=clock_ms,
        )
        source_store.record_feature(capture)
        captures.append(capture)
        rows = build_historical_feature_rows(
            candles_5m=capture.candles_5m,
            candles_15m=capture.candles_15m,
            funding_rates=capture.funding_rates,
            source_manifest_ids=(capture.capture_id,),
        )
        feature = next(
            (item for item in rows if item.anchor_end_ms == anchor_end_ms),
            None,
        )
        if feature is None:
            raise HistoricalArchiveCleanObserverError(
                f"ARCHIVE_CLEAN_FEATURE_ROW_MISSING:{canonical}"
            )
        base_features.append(feature)

    enriched = enrich_feature_rows_with_basket_context(base_features)
    markets = tuple(item.market.canonical for item in enriched)
    if markets != spec.markets:
        raise HistoricalArchiveCleanObserverError(
            "ARCHIVE_CLEAN_FEATURE_MARKETS_MISMATCH"
        )
    as_of_ms = clock_ms()
    if any(item.source_retrieved_at_ms > as_of_ms for item in enriched):
        raise HistoricalArchiveCleanObserverError(
            "ARCHIVE_CLEAN_FEATURE_RECEIVED_AFTER_AS_OF"
        )
    return ArchiveCleanFeatureCollection(
        anchor_end_ms=anchor_end_ms,
        as_of_ms=as_of_ms,
        features=enriched,
        capture_ids=tuple(sorted(item.capture_id for item in captures)),
    )


def settle_archive_clean_due_signals(
    reader: ArchiveCleanPublicReader,
    *,
    spec: HistoricalArchiveCleanValidationSpec,
    evidence_store: ArchiveCleanEvidenceBackend,
    source_store: ArchiveCleanSourceCaptureStore,
    clock_ms: Callable[[], int],
) -> ArchiveCleanSettlementResult:
    started_ms = clock_ms()
    due = evidence_store.due_unsettled_signals(as_of_ms=started_ms)
    if not due:
        return ArchiveCleanSettlementResult(
            as_of_ms=started_ms,
            settled=(),
            missing_signal_ids=(),
            capture_ids=(),
        )

    due_by_market: dict[
        str,
        list[tuple[ArchiveCleanAnchorObservation, ArchiveCleanSignalEvidence]],
    ] = {}
    for observation, signal in due:
        due_by_market.setdefault(signal.market, []).append((observation, signal))

    candle_by_market_end: dict[tuple[str, int], Candle] = {}
    capture_ids: list[str] = []
    for canonical in sorted(due_by_market):
        values = due_by_market[canonical]
        target_ends = tuple(
            sorted({signal.target_end_ms for _observation, signal in values})
        )
        start_ms = max(0, min(target_ends) - spec.anchor_interval_ms + 1)
        end_ms = max(target_ends)
        market = _market(canonical)
        raw = reader.candles(
            market,
            spec.anchor_interval,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        received_at_ms = clock_ms()
        candles = tuple(
            item
            for item in normalize_candles(
                market,
                raw,
                received_at_ms=received_at_ms,
            )
            if item.end_ms <= end_ms
        )
        capture = ArchiveCleanSettlementSourceCapture(
            validation_spec_id=spec.spec_id,
            market=canonical,
            requested_start_ms=start_ms,
            requested_end_ms=end_ms,
            received_at_ms=received_at_ms,
            candles=candles,
        )
        source_store.record_settlement(capture)
        capture_ids.append(capture.capture_id)
        for candle in candles:
            key = (canonical, candle.end_ms)
            if key in candle_by_market_end:
                raise HistoricalArchiveCleanObserverError(
                    "ARCHIVE_CLEAN_DUPLICATE_SETTLEMENT_CANDLE"
                )
            candle_by_market_end[key] = candle

    as_of_ms = clock_ms()
    settled: list[ArchiveCleanOutcome] = []
    missing: list[str] = []
    for observation, signal in due:
        exit_candle = candle_by_market_end.get(
            (signal.market, signal.target_end_ms)
        )
        if exit_candle is None:
            missing.append(signal.signal_id)
            continue
        outcome = build_archive_clean_outcome(
            spec,
            observation=observation,
            signal=signal,
            exit_candle=exit_candle,
            as_of_ms=as_of_ms,
        )
        evidence_store.record_outcome(outcome)
        settled.append(outcome)

    return ArchiveCleanSettlementResult(
        as_of_ms=as_of_ms,
        settled=tuple(
            sorted(
                settled,
                key=lambda item: (
                    item.target_end_ms,
                    item.market,
                    item.horizon_ms,
                    item.signal_id,
                ),
            )
        ),
        missing_signal_ids=tuple(sorted(set(missing))),
        capture_ids=tuple(sorted(set(capture_ids))),
    )


def run_archive_clean_observer_cycle(
    reader: ArchiveCleanPublicReader,
    *,
    artifact: HistoricalArchiveCandidateModelArtifact,
    spec: HistoricalArchiveCleanValidationSpec,
    evidence_store: ArchiveCleanEvidenceBackend,
    source_store: ArchiveCleanSourceCaptureStore,
    clock_ms: Callable[[], int],
) -> ArchiveCleanObserverCycleResult:
    if evidence_store.spec.spec_id != spec.spec_id:
        raise ValueError("clean evidence store does not match validation spec")
    cycle_started_ms = clock_ms()
    candidate_anchor_end_ms = latest_closed_anchor_ms(cycle_started_ms, spec)
    anchor_end_ms: int | None = candidate_anchor_end_ms

    status = "no_anchor_recorded"
    observation_id: str | None = None
    if cycle_started_ms < spec.validation_start_ms:
        status = "before_validation_window"
        anchor_end_ms = None
    elif candidate_anchor_end_ms >= spec.validation_end_ms:
        status = "after_validation_window"
        anchor_end_ms = None
    elif (
        cycle_started_ms - candidate_anchor_end_ms
        > MAX_ENTRY_CANDLE_AGE_MS
    ):
        status = "missed_anchor_window"
    else:
        existing_observation_id = evidence_store.observation_id_for_time(
            candidate_anchor_end_ms
        )
        if existing_observation_id is not None:
            status = "already_recorded"
            observation_id = existing_observation_id
        else:
            collection = collect_archive_clean_features(
                reader,
                spec=spec,
                anchor_end_ms=candidate_anchor_end_ms,
                clock_ms=clock_ms,
                source_store=source_store,
            )
            state_before = evidence_store.latest_state()
            result = score_archive_candidate_anchor(
                artifact,
                spec,
                collection.features,
                state=state_before,
            )
            observation = evidence_store.record_anchor_result(
                features=collection.features,
                state_before=state_before,
                result=result,
            )
            observation_id = observation.observation_id
            status = "recorded"

    settlement = settle_archive_clean_due_signals(
        reader,
        spec=spec,
        evidence_store=evidence_store,
        source_store=source_store,
        clock_ms=clock_ms,
    )
    summary = evidence_store.capture_summary(as_of_ms=settlement.as_of_ms)
    return ArchiveCleanObserverCycleResult(
        status=status,
        cycle_started_ms=cycle_started_ms,
        anchor_end_ms=anchor_end_ms,
        observation_id=observation_id,
        settled_outcome_ids=tuple(item.outcome_id for item in settlement.settled),
        missing_settlement_signal_ids=settlement.missing_signal_ids,
        capture_coverage=(
            None
            if summary.capture_coverage is None
            else str(summary.capture_coverage)
        ),
        expected_elapsed_anchor_count=summary.expected_elapsed_anchor_count,
        captured_elapsed_anchor_count=summary.captured_elapsed_anchor_count,
    )
