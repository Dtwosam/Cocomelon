from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import Enum

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, SourceSegment


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("configuration Decimal values must be finite")
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("configuration datetime values must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("configuration mapping keys must be non-empty strings")
            normalized[key] = _canonical_value(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported configuration value: {type(value).__name__}")


def canonical_config_digest(config_snapshot: Mapping[str, object]) -> str:
    canonical = _canonical_value(config_snapshot)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_replay_manifest(
    segments: Sequence[SourceSegment],
    *,
    evidence_class: EvidenceClass,
    start_ms: int,
    end_ms: int,
    code_revision: str,
    config_snapshot: Mapping[str, object],
    feature_version: str,
    strategy_version: str,
    risk_version: str,
    execution_config: PaperExecutionConfig | None,
    gap_refs: Sequence[str] = (),
    replay_engine_version: str = "phase8-v1",
    dataset_manifest_id: str | None = None,
) -> ReplayManifest:
    if evidence_class is EvidenceClass.MICROSTRUCTURE and execution_config is None:
        raise ValueError("microstructure replay requires execution_config")
    if evidence_class is EvidenceClass.CANDLE_CONTEXT and execution_config is not None:
        raise ValueError("candle-context replay must not claim execution_config")

    return ReplayManifest(
        evidence_class=evidence_class,
        start_ms=start_ms,
        end_ms=end_ms,
        segments=tuple(segments),
        gap_refs=tuple(gap_refs),
        code_revision=code_revision,
        config_digest=canonical_config_digest(config_snapshot),
        feature_version=feature_version,
        strategy_version=strategy_version,
        risk_version=risk_version,
        execution_config_version=(
            None if execution_config is None else execution_config.config_version
        ),
        fee_schedule_id=None if execution_config is None else execution_config.fee_schedule_id,
        replay_engine_version=replay_engine_version,
        dataset_manifest_id=dataset_manifest_id,
    )
