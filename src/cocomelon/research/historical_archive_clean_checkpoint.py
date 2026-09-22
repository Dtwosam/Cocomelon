from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from cocomelon.research.historical_archive_clean_evidence import (
    ArchiveCleanAnchorObservation,
    ArchiveCleanCampaignManifest,
    ArchiveCleanCaptureSummary,
    ArchiveCleanOutcome,
    ArchiveCleanSignalEvidence,
    HistoricalArchiveCleanEvidenceConsistencyError,
    _anchor_from_payload,
    _state_from_payload,
    _state_payload,
    build_archive_clean_anchor_observation,
)
from cocomelon.research.historical_archive_paper_scorer import (
    ArchivePaperAnchorResult,
    ArchivePaperState,
)
from cocomelon.research.historical_archive_validation_spec import (
    HistoricalArchiveCleanValidationSpec,
)
from cocomelon.research.historical_features import HistoricalFeatureRow

ZERO = 0
CHECKPOINT_SCHEMA_VERSION = 1


class HistoricalArchiveCleanCheckpointError(RuntimeError):
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


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise HistoricalArchiveCleanCheckpointError(f"{field} must be an object")
    return value


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise HistoricalArchiveCleanCheckpointError(f"{field} must be a sequence")
    return tuple(value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalArchiveCleanCheckpointError(
            f"{field} must be a non-empty string"
        )
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HistoricalArchiveCleanCheckpointError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _bitmap_value(value: str) -> int:
    if not value:
        raise ValueError("captured_bitmap_hex must not be empty")
    if any(char not in "0123456789abcdef" for char in value):
        raise ValueError("captured_bitmap_hex must be lowercase hexadecimal")
    if value != "0" and value.startswith("0"):
        raise ValueError("captured_bitmap_hex must be canonical")
    return int(value, 16)


def _bitmap_hex(value: int) -> str:
    if value < 0:
        raise ValueError("bitmap value must be non-negative")
    return format(value, "x")


@dataclass(frozen=True, slots=True)
class ArchiveCleanPendingObservation:
    observation: ArchiveCleanAnchorObservation
    pending_signal_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            tuple(sorted(set(self.pending_signal_ids)))
            != self.pending_signal_ids
            or not self.pending_signal_ids
        ):
            raise ValueError("pending_signal_ids must be sorted unique and non-empty")
        accepted = {item.signal_id for item in self.observation.accepted_signals}
        if not set(self.pending_signal_ids).issubset(accepted):
            raise ValueError("pending signals must belong to accepted observation signals")

    def to_dict(self) -> dict[str, object]:
        return {
            "observation": self.observation.to_dict(),
            "pending_signal_ids": self.pending_signal_ids,
        }


@dataclass(frozen=True, slots=True)
class ArchiveCleanOperationalCheckpoint:
    validation_spec_id: str
    candidate_id: str
    model_artifact_id: str
    campaign_id: str
    runtime_id: str
    pin_id: str
    first_expected_anchor_ms: int
    anchor_interval_ms: int
    expected_anchor_count: int
    captured_bitmap_hex: str
    latest_anchor_end_ms: int | None
    latest_observation_id: str | None
    latest_state: ArchivePaperState
    pending_observations: tuple[ArchiveCleanPendingObservation, ...]
    settled_outcome_count: int
    as_of_ms: int
    schema_version: int = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field in (
            "validation_spec_id",
            "candidate_id",
            "model_artifact_id",
            "campaign_id",
            "runtime_id",
            "pin_id",
        ):
            _require_sha256(getattr(self, field), field)
        if self.first_expected_anchor_ms < 0:
            raise ValueError("first_expected_anchor_ms must be non-negative")
        if self.anchor_interval_ms <= 0:
            raise ValueError("anchor_interval_ms must be positive")
        if self.expected_anchor_count <= 0:
            raise ValueError("expected_anchor_count must be positive")
        bitmap = _bitmap_value(self.captured_bitmap_hex)
        if bitmap >> self.expected_anchor_count:
            raise ValueError("captured bitmap contains out-of-range anchors")
        captured_count = bitmap.bit_count()
        if captured_count == 0:
            if self.latest_anchor_end_ms is not None or self.latest_observation_id is not None:
                raise ValueError("empty checkpoint cannot have latest observation")
            if self.latest_state != ArchivePaperState():
                raise ValueError("empty checkpoint state must be empty")
            if self.pending_observations:
                raise ValueError("empty checkpoint cannot have pending observations")
        else:
            if self.latest_anchor_end_ms is None or self.latest_observation_id is None:
                raise ValueError("captured checkpoint requires latest observation")
            _require_sha256(self.latest_observation_id, "latest_observation_id")
            index = self.anchor_index(self.latest_anchor_end_ms)
            if not (bitmap & (1 << index)):
                raise ValueError("latest anchor must be marked captured")
        observation_ids = tuple(
            item.observation.observation_id for item in self.pending_observations
        )
        if len(set(observation_ids)) != len(observation_ids):
            raise ValueError("pending observations must be unique")
        signal_ids = tuple(
            signal_id
            for item in self.pending_observations
            for signal_id in item.pending_signal_ids
        )
        if len(set(signal_ids)) != len(signal_ids):
            raise ValueError("pending signal IDs must be unique")
        for item in self.pending_observations:
            if item.observation.validation_spec_id != self.validation_spec_id:
                raise ValueError("pending observation validation spec mismatch")
            if item.observation.candidate_id != self.candidate_id:
                raise ValueError("pending observation candidate mismatch")
            if item.observation.model_artifact_id != self.model_artifact_id:
                raise ValueError("pending observation model artifact mismatch")
            index = self.anchor_index(item.observation.anchor_end_ms)
            if not (bitmap & (1 << index)):
                raise ValueError("pending observation anchor must be captured")
        if self.settled_outcome_count < 0:
            raise ValueError("settled_outcome_count must be non-negative")
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if (
            self.latest_anchor_end_ms is not None
            and self.as_of_ms < self.latest_anchor_end_ms
        ):
            raise ValueError("checkpoint as_of_ms cannot precede latest anchor")
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported archive clean checkpoint schema")

    @property
    def captured_anchor_count(self) -> int:
        return _bitmap_value(self.captured_bitmap_hex).bit_count()

    def anchor_index(self, anchor_end_ms: int) -> int:
        delta = anchor_end_ms - self.first_expected_anchor_ms
        if delta < 0 or delta % self.anchor_interval_ms != 0:
            raise ValueError("anchor is not aligned to checkpoint geometry")
        index = delta // self.anchor_interval_ms
        if index >= self.expected_anchor_count:
            raise ValueError("anchor is outside checkpoint geometry")
        return index

    def is_captured(self, anchor_end_ms: int) -> bool:
        index = self.anchor_index(anchor_end_ms)
        return bool(_bitmap_value(self.captured_bitmap_hex) & (1 << index))

    def identity_payload(self) -> dict[str, object]:
        return {
            "validation_spec_id": self.validation_spec_id,
            "candidate_id": self.candidate_id,
            "model_artifact_id": self.model_artifact_id,
            "campaign_id": self.campaign_id,
            "runtime_id": self.runtime_id,
            "pin_id": self.pin_id,
            "first_expected_anchor_ms": self.first_expected_anchor_ms,
            "anchor_interval_ms": self.anchor_interval_ms,
            "expected_anchor_count": self.expected_anchor_count,
            "captured_bitmap_hex": self.captured_bitmap_hex,
            "latest_anchor_end_ms": self.latest_anchor_end_ms,
            "latest_observation_id": self.latest_observation_id,
            "latest_state": _state_payload(self.latest_state),
            "pending_observations": tuple(
                item.to_dict() for item in self.pending_observations
            ),
            "settled_outcome_count": self.settled_outcome_count,
            "as_of_ms": self.as_of_ms,
            "schema_version": self.schema_version,
        }

    @property
    def checkpoint_id(self) -> str:
        return _sha256(self.identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "checkpoint_id": self.checkpoint_id}


def _pending_from_payload(value: object) -> ArchiveCleanPendingObservation:
    raw = _mapping(value, "pending observation")
    observation = _anchor_from_payload(raw.get("observation"))
    pending_signal_ids = tuple(
        _string(item, "pending signal ID")
        for item in _sequence(
            raw.get("pending_signal_ids"),
            "pending signal IDs",
        )
    )
    return ArchiveCleanPendingObservation(
        observation=observation,
        pending_signal_ids=pending_signal_ids,
    )


def load_archive_clean_operational_checkpoint(
    path: Path,
) -> ArchiveCleanOperationalCheckpoint:
    try:
        raw = _mapping(
            json.loads(path.read_text(encoding="utf-8")),
            "archive clean operational checkpoint",
        )
        checkpoint = ArchiveCleanOperationalCheckpoint(
            validation_spec_id=_string(
                raw.get("validation_spec_id"),
                "validation_spec_id",
            ),
            candidate_id=_string(raw.get("candidate_id"), "candidate_id"),
            model_artifact_id=_string(
                raw.get("model_artifact_id"),
                "model_artifact_id",
            ),
            campaign_id=_string(raw.get("campaign_id"), "campaign_id"),
            runtime_id=_string(raw.get("runtime_id"), "runtime_id"),
            pin_id=_string(raw.get("pin_id"), "pin_id"),
            first_expected_anchor_ms=_integer(
                raw.get("first_expected_anchor_ms"),
                "first_expected_anchor_ms",
            ),
            anchor_interval_ms=_integer(
                raw.get("anchor_interval_ms"),
                "anchor_interval_ms",
            ),
            expected_anchor_count=_integer(
                raw.get("expected_anchor_count"),
                "expected_anchor_count",
            ),
            captured_bitmap_hex=_string(
                raw.get("captured_bitmap_hex"),
                "captured_bitmap_hex",
            ),
            latest_anchor_end_ms=_optional_integer(
                raw.get("latest_anchor_end_ms"),
                "latest_anchor_end_ms",
            ),
            latest_observation_id=_optional_string(
                raw.get("latest_observation_id"),
                "latest_observation_id",
            ),
            latest_state=_state_from_payload(
                raw.get("latest_state"),
                "latest_state",
            ),
            pending_observations=tuple(
                _pending_from_payload(item)
                for item in _sequence(
                    raw.get("pending_observations"),
                    "pending_observations",
                )
            ),
            settled_outcome_count=_integer(
                raw.get("settled_outcome_count"),
                "settled_outcome_count",
            ),
            as_of_ms=_integer(raw.get("as_of_ms"), "as_of_ms"),
            schema_version=_integer(
                raw.get("schema_version"),
                "schema_version",
            ),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HistoricalArchiveCleanCheckpointError(
            "ARCHIVE_CLEAN_CHECKPOINT_INVALID"
        ) from exc
    if raw.get("checkpoint_id") != checkpoint.checkpoint_id:
        raise HistoricalArchiveCleanCheckpointError(
            "ARCHIVE_CLEAN_CHECKPOINT_ID_MISMATCH"
        )
    if path.read_text(encoding="utf-8") != _canonical_json(
        checkpoint.to_dict()
    ) + "\n":
        raise HistoricalArchiveCleanCheckpointError(
            "ARCHIVE_CLEAN_CHECKPOINT_NON_CANONICAL"
        )
    return checkpoint


def _write_checkpoint(
    path: Path,
    checkpoint: ArchiveCleanOperationalCheckpoint,
) -> None:
    payload = (_canonical_json(checkpoint.to_dict()) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _date_path(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date().isoformat()


class ArchiveCleanCheckpointEvidenceStore:
    def __init__(
        self,
        checkpoint_path: Path,
        *,
        cycle_evidence_root: Path,
        spec: HistoricalArchiveCleanValidationSpec,
        runtime_id: str,
        pin_id: str,
    ) -> None:
        self.checkpoint_path = checkpoint_path
        self.cycle_evidence_root = cycle_evidence_root
        self.cycle_evidence_root.mkdir(parents=True, exist_ok=True)
        self.spec = spec
        manifest = ArchiveCleanCampaignManifest(
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
        self.campaign_id = manifest.campaign_id
        self.runtime_id = runtime_id
        self.pin_id = pin_id
        if checkpoint_path.exists():
            checkpoint = load_archive_clean_operational_checkpoint(checkpoint_path)
            self._verify_lineage(checkpoint)
            self._checkpoint = checkpoint
        else:
            self._checkpoint = ArchiveCleanOperationalCheckpoint(
                validation_spec_id=spec.spec_id,
                candidate_id=spec.candidate_id,
                model_artifact_id=spec.model_artifact_id,
                campaign_id=self.campaign_id,
                runtime_id=runtime_id,
                pin_id=pin_id,
                first_expected_anchor_ms=spec.first_expected_anchor_ms,
                anchor_interval_ms=spec.anchor_interval_ms,
                expected_anchor_count=spec.expected_anchor_count,
                captured_bitmap_hex="0",
                latest_anchor_end_ms=None,
                latest_observation_id=None,
                latest_state=ArchivePaperState(),
                pending_observations=(),
                settled_outcome_count=0,
                as_of_ms=0,
            )

    @property
    def checkpoint(self) -> ArchiveCleanOperationalCheckpoint:
        return self._checkpoint

    def _verify_lineage(
        self,
        checkpoint: ArchiveCleanOperationalCheckpoint,
    ) -> None:
        expected = (
            self.spec.spec_id,
            self.spec.candidate_id,
            self.spec.model_artifact_id,
            self.campaign_id,
            self.runtime_id,
            self.pin_id,
            self.spec.first_expected_anchor_ms,
            self.spec.anchor_interval_ms,
            self.spec.expected_anchor_count,
        )
        actual = (
            checkpoint.validation_spec_id,
            checkpoint.candidate_id,
            checkpoint.model_artifact_id,
            checkpoint.campaign_id,
            checkpoint.runtime_id,
            checkpoint.pin_id,
            checkpoint.first_expected_anchor_ms,
            checkpoint.anchor_interval_ms,
            checkpoint.expected_anchor_count,
        )
        if actual != expected:
            raise HistoricalArchiveCleanCheckpointError(
                "ARCHIVE_CLEAN_CHECKPOINT_LINEAGE_MISMATCH"
            )

    @staticmethod
    def _write_consistent(path: Path, payload: dict[str, object]) -> Path:
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != encoded:
                raise HistoricalArchiveCleanEvidenceConsistencyError(
                    f"conflicting clean cycle evidence record: {path.name}"
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

    def _anchor_path(
        self,
        observation: ArchiveCleanAnchorObservation,
    ) -> Path:
        return (
            self.cycle_evidence_root
            / "anchors"
            / _date_path(observation.anchor_end_ms)
            / f"{observation.anchor_end_ms}.json"
        )

    def _outcome_path(self, outcome: ArchiveCleanOutcome) -> Path:
        return (
            self.cycle_evidence_root
            / "outcomes"
            / _date_path(outcome.target_end_ms)
            / f"{outcome.outcome_id}.json"
        )

    def observation_id_for_time(self, anchor_end_ms: int) -> str | None:
        if not self._checkpoint.is_captured(anchor_end_ms):
            return None
        if self._checkpoint.latest_anchor_end_ms != anchor_end_ms:
            raise HistoricalArchiveCleanCheckpointError(
                "ARCHIVE_CLEAN_CHECKPOINT_CLOCK_REGRESSION"
            )
        return self._checkpoint.latest_observation_id

    def latest_state(self) -> ArchivePaperState:
        return self._checkpoint.latest_state

    def record_anchor_result(
        self,
        *,
        features: tuple[HistoricalFeatureRow, ...],
        state_before: ArchivePaperState,
        result: ArchivePaperAnchorResult,
    ) -> ArchiveCleanAnchorObservation:
        anchor_end_ms = result.anchor_end_ms
        if self._checkpoint.latest_anchor_end_ms is not None:
            if anchor_end_ms <= self._checkpoint.latest_anchor_end_ms:
                raise HistoricalArchiveCleanCheckpointError(
                    "ARCHIVE_CLEAN_CHECKPOINT_ANCHOR_NOT_FORWARD"
                )
        expected_state = self._checkpoint.latest_state.active_at(anchor_end_ms)
        if state_before != expected_state:
            raise HistoricalArchiveCleanCheckpointError(
                "ARCHIVE_CLEAN_CHECKPOINT_STATE_CONTINUITY_MISMATCH"
            )
        if self._checkpoint.is_captured(anchor_end_ms):
            raise HistoricalArchiveCleanCheckpointError(
                "ARCHIVE_CLEAN_CHECKPOINT_DUPLICATE_ANCHOR"
            )

        observation = build_archive_clean_anchor_observation(
            self.spec,
            features=features,
            state_before=state_before,
            result=result,
        )
        self._write_consistent(
            self._anchor_path(observation),
            observation.to_dict(),
        )

        index = self._checkpoint.anchor_index(anchor_end_ms)
        bitmap = _bitmap_value(self._checkpoint.captured_bitmap_hex)
        bitmap |= 1 << index
        pending = list(self._checkpoint.pending_observations)
        accepted_ids = tuple(
            sorted(item.signal_id for item in observation.accepted_signals)
        )
        if accepted_ids:
            pending.append(
                ArchiveCleanPendingObservation(
                    observation=observation,
                    pending_signal_ids=accepted_ids,
                )
            )
        pending.sort(key=lambda item: item.observation.anchor_end_ms)
        self._checkpoint = replace(
            self._checkpoint,
            captured_bitmap_hex=_bitmap_hex(bitmap),
            latest_anchor_end_ms=anchor_end_ms,
            latest_observation_id=observation.observation_id,
            latest_state=observation.state_after,
            pending_observations=tuple(pending),
        )
        return observation

    def due_unsettled_signals(
        self,
        *,
        as_of_ms: int,
    ) -> tuple[
        tuple[ArchiveCleanAnchorObservation, ArchiveCleanSignalEvidence],
        ...,
    ]:
        due: list[
            tuple[ArchiveCleanAnchorObservation, ArchiveCleanSignalEvidence]
        ] = []
        for pending in self._checkpoint.pending_observations:
            signals = {
                item.signal_id: item for item in pending.observation.accepted_signals
            }
            for signal_id in pending.pending_signal_ids:
                signal = signals[signal_id]
                if signal.target_end_ms <= as_of_ms:
                    due.append((pending.observation, signal))
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

    def record_outcome(self, outcome: ArchiveCleanOutcome) -> Path:
        pending_values = list(self._checkpoint.pending_observations)
        matched_index: int | None = None
        for index, pending in enumerate(pending_values):
            if pending.observation.observation_id != outcome.anchor_observation_id:
                continue
            if outcome.signal_id not in pending.pending_signal_ids:
                continue
            signal = next(
                (
                    item
                    for item in pending.observation.accepted_signals
                    if item.signal_id == outcome.signal_id
                ),
                None,
            )
            if signal is None:
                raise HistoricalArchiveCleanCheckpointError(
                    "ARCHIVE_CLEAN_CHECKPOINT_PENDING_SIGNAL_MISSING"
                )
            if (
                signal.market != outcome.market
                or signal.anchor_end_ms != outcome.anchor_end_ms
                or signal.target_end_ms != outcome.target_end_ms
                or signal.horizon_ms != outcome.horizon_ms
                or signal.direction != outcome.direction
            ):
                raise HistoricalArchiveCleanCheckpointError(
                    "ARCHIVE_CLEAN_CHECKPOINT_OUTCOME_LINEAGE_MISMATCH"
                )
            matched_index = index
            remaining = tuple(
                item
                for item in pending.pending_signal_ids
                if item != outcome.signal_id
            )
            if remaining:
                pending_values[index] = ArchiveCleanPendingObservation(
                    observation=pending.observation,
                    pending_signal_ids=remaining,
                )
            else:
                pending_values.pop(index)
            break
        if matched_index is None:
            raise HistoricalArchiveCleanCheckpointError(
                "ARCHIVE_CLEAN_CHECKPOINT_OUTCOME_NOT_PENDING"
            )

        path = self._write_consistent(
            self._outcome_path(outcome),
            outcome.to_dict(),
        )
        self._checkpoint = replace(
            self._checkpoint,
            pending_observations=tuple(pending_values),
            settled_outcome_count=self._checkpoint.settled_outcome_count + 1,
        )
        return path

    def capture_summary(self, *, as_of_ms: int) -> ArchiveCleanCaptureSummary:
        upper = min(as_of_ms, self.spec.validation_end_ms - 1)
        if upper < self.spec.first_expected_anchor_ms:
            expected_count = 0
        else:
            expected_count = (
                (upper - self.spec.first_expected_anchor_ms)
                // self.spec.anchor_interval_ms
            ) + 1
            expected_count = min(expected_count, self.spec.expected_anchor_count)
        bitmap = _bitmap_value(self._checkpoint.captured_bitmap_hex)
        mask = (1 << expected_count) - 1 if expected_count else ZERO
        captured_count = (bitmap & mask).bit_count()
        missing = tuple(
            self.spec.first_expected_anchor_ms
            + index * self.spec.anchor_interval_ms
            for index in range(expected_count)
            if not (bitmap & (1 << index))
        )
        coverage = (
            None
            if expected_count == 0
            else self._decimal_ratio(captured_count, expected_count)
        )
        return ArchiveCleanCaptureSummary(
            as_of_ms=as_of_ms,
            expected_elapsed_anchor_count=expected_count,
            captured_elapsed_anchor_count=captured_count,
            missing_anchor_end_ms=missing,
            capture_coverage=coverage,
            validation_window_complete=as_of_ms >= self.spec.validation_end_ms,
        )

    @staticmethod
    def _decimal_ratio(numerator: int, denominator: int):
        from decimal import Decimal

        return Decimal(numerator) / Decimal(denominator)

    def save(self, *, as_of_ms: int) -> ArchiveCleanOperationalCheckpoint:
        if as_of_ms < self._checkpoint.as_of_ms:
            raise HistoricalArchiveCleanCheckpointError(
                "ARCHIVE_CLEAN_CHECKPOINT_AS_OF_REGRESSION"
            )
        self._checkpoint = replace(self._checkpoint, as_of_ms=as_of_ms)
        _write_checkpoint(self.checkpoint_path, self._checkpoint)
        return self._checkpoint
