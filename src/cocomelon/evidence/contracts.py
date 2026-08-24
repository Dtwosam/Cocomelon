from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from cocomelon.config import MAINNET_API_URL, MAINNET_WS_URL
from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayManifest
from cocomelon.domain.risk import RiskLimits
from cocomelon.scanner.eligibility import EligibilityConfig

MAX_PUBLIC_SUBSCRIPTIONS = 1_000
SUBSCRIPTION_SAFETY_CEILING = 800
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def _require_nonempty(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _require_sha256(value: str, field_name: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase 64-character sha256 digest")


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical Decimal values must be finite")
        return str(value)
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, MarketId):
        return value.canonical
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("canonical mapping keys must be non-empty strings")
            normalized[key] = _canonical(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _digest(value: object) -> str:
    encoded = json.dumps(
        _canonical(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _dataclass_payload(value: object) -> dict[str, object]:
    canonical = _canonical(value)
    if not isinstance(canonical, dict):
        raise TypeError("expected dataclass canonical payload to be a mapping")
    return canonical


@dataclass(frozen=True, slots=True)
class EvidenceRecordingConfig:
    duration_seconds: int
    deep_limit: int = 20
    context_poll_seconds: int = 60
    funding_poll_seconds: int = 60
    warmup_5m_bars: int = 25
    warmup_15m_bars: int = 25
    candle_intervals: tuple[str, ...] = ("1m", "5m", "15m")
    max_records: int = 100_000
    max_bytes: int = 64 * 1024 * 1024
    api_url: str = MAINNET_API_URL
    ws_url: str = MAINNET_WS_URL
    selection_policy_id: str = "rankable-native-top-v1"
    config_version: str = "phase9-evidence-v1"

    def __post_init__(self) -> None:
        if self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.deep_limit <= 0:
            raise ValueError("deep_limit must be positive")
        if self.context_poll_seconds <= 0:
            raise ValueError("context_poll_seconds must be positive")
        if self.funding_poll_seconds <= 0:
            raise ValueError("funding_poll_seconds must be positive")
        if self.warmup_5m_bars <= 0 or self.warmup_15m_bars <= 0:
            raise ValueError("warmup bar counts must be positive")
        if self.candle_intervals != ("1m", "5m", "15m"):
            raise ValueError("candle_intervals must remain the fixed V1 interval set")
        if self.max_records <= 0 or self.max_bytes <= 0:
            raise ValueError("recorder segment limits must be positive")
        if self.api_url != MAINNET_API_URL or self.ws_url != MAINNET_WS_URL:
            raise ValueError("evidence recording requires exact Hyperliquid mainnet endpoints")
        _require_nonempty(self.selection_policy_id, "selection_policy_id")
        _require_nonempty(self.config_version, "config_version")
        per_market_subscriptions = 3 + len(self.candle_intervals)
        subscription_count = 1 + self.deep_limit * per_market_subscriptions
        if subscription_count > SUBSCRIPTION_SAFETY_CEILING:
            raise ValueError("deep_limit exceeds the public subscription safety ceiling")
        if subscription_count > MAX_PUBLIC_SUBSCRIPTIONS:
            raise ValueError("deep_limit exceeds the public subscription limit")

    @property
    def config_digest(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class SelectedEvidenceMarket:
    market: MarketId
    rank: int
    feature_snapshot_id: str
    score: Decimal

    def __post_init__(self) -> None:
        if self.market.dex != "":
            raise ValueError("selected evidence market must use the native execution namespace")
        if self.rank <= 0:
            raise ValueError("rank must be positive")
        _require_nonempty(self.feature_snapshot_id, "feature_snapshot_id")
        if not self.score.is_finite() or self.score < ZERO or self.score > HUNDRED:
            raise ValueError("score must be finite and between 0 and 100")


@dataclass(frozen=True, slots=True)
class EvidenceRecordingSession:
    started_at_ms: int
    recorder_code_revision: str
    selected: tuple[SelectedEvidenceMarket, ...]
    recording_config_digest: str
    api_url: str
    ws_url: str
    selection_policy_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.started_at_ms < 0:
            raise ValueError("started_at_ms must be non-negative")
        _require_nonempty(self.recorder_code_revision, "recorder_code_revision")
        if not self.selected:
            raise ValueError("selected markets must not be empty")
        selected = tuple(sorted(self.selected, key=lambda item: item.market.canonical))
        markets = tuple(item.market.canonical for item in selected)
        ranks = tuple(item.rank for item in selected)
        if len(set(markets)) != len(markets):
            raise ValueError("selected markets contain duplicate market")
        if len(set(ranks)) != len(ranks):
            raise ValueError("selected markets contain duplicate rank")
        object.__setattr__(self, "selected", selected)
        _require_sha256(self.recording_config_digest, "recording_config_digest")
        if self.api_url != MAINNET_API_URL or self.ws_url != MAINNET_WS_URL:
            raise ValueError("recording session endpoints must be Hyperliquid mainnet")
        _require_nonempty(self.selection_policy_id, "selection_policy_id")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def session_id(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class BaselineReplayConfig:
    starting_cash: Decimal = Decimal("10000")
    decision_interval: str = "15m"
    decision_grace_ms: int = 30_000
    microstructure_window_ms: int = 60_000
    correlation_bucket: str = "crypto_beta"
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    eligibility: EligibilityConfig = field(default_factory=EligibilityConfig)
    execution: PaperExecutionConfig = field(default_factory=PaperExecutionConfig)
    liquidation_policy_id: str = "paper-leverage-distance-v1"
    feature_version: str = "phase4-v1"
    strategy_version: str = "phase5-v1"
    risk_version: str = "phase6-v1"
    replay_engine_version: str = "phase8-v1"
    config_version: str = "phase9-baseline-replay-v1"

    def __post_init__(self) -> None:
        if not self.starting_cash.is_finite() or self.starting_cash <= ZERO:
            raise ValueError("starting_cash must be positive and finite")
        if self.decision_interval != "15m":
            raise ValueError("decision_interval must remain 15m for V1")
        if self.decision_grace_ms < 0:
            raise ValueError("decision_grace_ms must be non-negative")
        if self.microstructure_window_ms <= 0:
            raise ValueError("microstructure_window_ms must be positive")
        for name in (
            "correlation_bucket",
            "liquidation_policy_id",
            "feature_version",
            "strategy_version",
            "risk_version",
            "replay_engine_version",
            "config_version",
        ):
            _require_nonempty(str(getattr(self, name)), name)

    @property
    def config_digest(self) -> str:
        return _digest(self)


def baseline_manifest_config_digest(
    replay_config: BaselineReplayConfig,
    recording_session_digest: str,
) -> str:
    _require_sha256(recording_session_digest, "recording_session_digest")
    return _digest(
        {
            "replay_config": _dataclass_payload(replay_config),
            "recording_session_digest": recording_session_digest,
        }
    )


@dataclass(frozen=True, slots=True)
class FrozenBaselineReplayBundle:
    manifest: ReplayManifest
    replay_config: BaselineReplayConfig
    recording_session_digest: str
    source_set_digest: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_sha256(self.recording_session_digest, "recording_session_digest")
        _require_sha256(self.source_set_digest, "source_set_digest")
        if self.manifest.evidence_class is not EvidenceClass.MICROSTRUCTURE:
            raise ValueError("baseline replay bundle requires microstructure evidence")
        expected = baseline_manifest_config_digest(
            self.replay_config,
            self.recording_session_digest,
        )
        if self.manifest.config_digest != expected:
            raise ValueError("manifest config_digest does not match replay configuration")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def bundle_id(self) -> str:
        return _digest(
            {
                "manifest_id": self.manifest.manifest_id,
                "replay_config": _dataclass_payload(self.replay_config),
                "recording_session_digest": self.recording_session_digest,
                "source_set_digest": self.source_set_digest,
                "schema_version": self.schema_version,
            }
        )


def canonical_contract_payload(value: Any) -> dict[str, object]:
    """Return a canonical mapping for persisted bridge configuration codecs."""
    return _dataclass_payload(value)
