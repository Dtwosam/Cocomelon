from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class SplitName(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class OOSStatus(StrEnum):
    UNTOUCHED = "untouched"
    REPRODUCTION = "reproduction"
    CONTAMINATED = "contaminated"


class EdgeEvidenceStatus(StrEnum):
    INVALID_EVIDENCE = "invalid_evidence"
    OOS_CONTAMINATED = "oos_contaminated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_EDGE_DEMONSTRATED = "no_edge_demonstrated"
    CANDIDATE_EDGE = "candidate_edge"


class EquityFactKind(StrEnum):
    MARK = "mark"
    FILL = "fill"
    FUNDING = "funding"
    POSITION_ACTION = "position_action"
    ACCOUNT_UPDATE = "account_update"


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _require_sha256(value: str, field: str) -> None:
    if (
        len(value) != 64
        or value != value.lower()
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field} must be a lowercase 64-character sha256 hex digest")


def _require_finite(value: Decimal, field: str) -> None:
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")


def _require_positive(value: Decimal, field: str) -> None:
    _require_finite(value, field)
    if value <= ZERO:
        raise ValueError(f"{field} must be positive")


def _require_nonnegative(value: Decimal, field: str) -> None:
    _require_finite(value, field)
    if value < ZERO:
        raise ValueError(f"{field} must be non-negative")


def _require_fraction(value: Decimal, field: str, *, allow_zero: bool = True) -> None:
    _require_finite(value, field)
    lower_ok = value >= ZERO if allow_zero else value > ZERO
    if not lower_ok or value > ONE:
        lower = "[0" if allow_zero else "(0"
        raise ValueError(f"{field} must be in {lower}, 1]")


def _require_score(value: Decimal) -> None:
    _require_finite(value, "score")
    if value < ZERO or value > HUNDRED:
        raise ValueError("score must be between 0 and 100")


def _canonical_strings(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    normalized = tuple(sorted(set(values)))
    if any(not value.strip() for value in normalized):
        raise ValueError(f"{field} values must not be empty")
    return normalized


def _digest(payload: dict[str, object], *, length: int = 24) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


@dataclass(frozen=True, slots=True)
class DecisionEvaluationFact:
    strategy_decision_id: str
    feature_snapshot_id: str
    replay_run_id: str
    market: MarketId
    direction: Direction
    timestamp_ms: int
    score: Decimal
    lead_strategy: str | None
    signal_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    trend_regime: TrendRegime
    volatility_regime: VolatilityRegime
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in ("strategy_decision_id", "feature_snapshot_id", "replay_run_id"):
            _require_nonempty(getattr(self, field), field)
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        _require_score(self.score)
        if self.lead_strategy is not None:
            _require_nonempty(self.lead_strategy, "lead_strategy")
        if self.direction is not Direction.NO_TRADE and self.lead_strategy is None:
            raise ValueError("directional decision facts require lead_strategy")
        object.__setattr__(self, "signal_ids", _canonical_strings(self.signal_ids, "signal_ids"))
        object.__setattr__(
            self,
            "reason_codes",
            _canonical_strings(self.reason_codes, "reason_codes"),
        )
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def fact_id(self) -> str:
        return _digest(
            {
                "strategy_decision_id": self.strategy_decision_id,
                "feature_snapshot_id": self.feature_snapshot_id,
                "replay_run_id": self.replay_run_id,
                "market": self.market.canonical,
                "direction": self.direction.value,
                "timestamp_ms": self.timestamp_ms,
                "score": str(self.score),
                "lead_strategy": self.lead_strategy,
                "signal_ids": self.signal_ids,
                "reason_codes": self.reason_codes,
                "trend_regime": self.trend_regime.value,
                "volatility_regime": self.volatility_regime.value,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class AccountEquityFact:
    replay_run_id: str
    account_state_id: str
    timestamp_ms: int
    kind: EquityFactKind
    equity: Decimal
    cash: Decimal
    unrealized_pnl: Decimal
    realized_gross_pnl: Decimal
    cumulative_fees: Decimal
    cumulative_funding: Decimal
    gross_open_notional: Decimal
    open_position_count: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty(self.replay_run_id, "replay_run_id")
        _require_nonempty(self.account_state_id, "account_state_id")
        if self.timestamp_ms < 0:
            raise ValueError("timestamp_ms must be non-negative")
        _require_positive(self.equity, "equity")
        for field in (
            "cash",
            "unrealized_pnl",
            "realized_gross_pnl",
            "cumulative_funding",
        ):
            _require_finite(getattr(self, field), field)
        _require_nonnegative(self.cumulative_fees, "cumulative_fees")
        _require_nonnegative(self.gross_open_notional, "gross_open_notional")
        if self.open_position_count < 0:
            raise ValueError("open_position_count must be non-negative")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def fact_id(self) -> str:
        return _digest(
            {
                "replay_run_id": self.replay_run_id,
                "account_state_id": self.account_state_id,
                "timestamp_ms": self.timestamp_ms,
                "kind": self.kind.value,
                "equity": str(self.equity),
                "cash": str(self.cash),
                "unrealized_pnl": str(self.unrealized_pnl),
                "realized_gross_pnl": str(self.realized_gross_pnl),
                "cumulative_fees": str(self.cumulative_fees),
                "cumulative_funding": str(self.cumulative_funding),
                "gross_open_notional": str(self.gross_open_notional),
                "open_position_count": self.open_position_count,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class TradeEvaluationSample:
    trade_id: str
    replay_run_id: str
    strategy_decision_id: str
    market: MarketId
    direction: Direction
    decision_timestamp_ms: int
    opened_at_ms: int
    closed_at_ms: int
    score: Decimal
    lead_strategy: str
    trend_regime: TrendRegime
    volatility_regime: VolatilityRegime
    evidence_class: EvidenceClass
    gross_realized_pnl: Decimal
    entry_fees: Decimal
    exit_fees: Decimal
    funding_cash_pnl: Decimal
    net_pnl: Decimal
    entry_slippage_amount: Decimal
    exit_slippage_amount: Decimal
    net_r: Decimal
    equity_before: Decimal
    equity_after: Decimal
    holding_duration_ms: int
    reason_codes: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in ("trade_id", "replay_run_id", "strategy_decision_id", "lead_strategy"):
            _require_nonempty(getattr(self, field), field)
        if self.direction is Direction.NO_TRADE:
            raise ValueError("closed trade samples cannot have NO_TRADE direction")
        if self.decision_timestamp_ms < 0 or self.opened_at_ms < 0 or self.closed_at_ms < 0:
            raise ValueError("sample timestamps must be non-negative")
        if not self.decision_timestamp_ms <= self.opened_at_ms <= self.closed_at_ms:
            raise ValueError("sample timestamps must be chronologically ordered")
        if self.holding_duration_ms < 0:
            raise ValueError("holding_duration_ms must be non-negative")
        if self.holding_duration_ms != self.closed_at_ms - self.opened_at_ms:
            raise ValueError("holding_duration_ms must equal closed_at_ms - opened_at_ms")
        _require_score(self.score)
        for field in (
            "gross_realized_pnl",
            "funding_cash_pnl",
            "net_pnl",
            "entry_slippage_amount",
            "exit_slippage_amount",
            "net_r",
        ):
            _require_finite(getattr(self, field), field)
        _require_nonnegative(self.entry_fees, "entry_fees")
        _require_nonnegative(self.exit_fees, "exit_fees")
        _require_positive(self.equity_before, "equity_before")
        _require_positive(self.equity_after, "equity_after")
        object.__setattr__(
            self,
            "reason_codes",
            _canonical_strings(self.reason_codes, "reason_codes"),
        )
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def sample_id(self) -> str:
        return _digest(
            {
                "trade_id": self.trade_id,
                "replay_run_id": self.replay_run_id,
                "strategy_decision_id": self.strategy_decision_id,
                "market": self.market.canonical,
                "direction": self.direction.value,
                "decision_timestamp_ms": self.decision_timestamp_ms,
                "opened_at_ms": self.opened_at_ms,
                "closed_at_ms": self.closed_at_ms,
                "score": str(self.score),
                "lead_strategy": self.lead_strategy,
                "trend_regime": self.trend_regime.value,
                "volatility_regime": self.volatility_regime.value,
                "evidence_class": self.evidence_class.value,
                "gross_realized_pnl": str(self.gross_realized_pnl),
                "entry_fees": str(self.entry_fees),
                "exit_fees": str(self.exit_fees),
                "funding_cash_pnl": str(self.funding_cash_pnl),
                "net_pnl": str(self.net_pnl),
                "entry_slippage_amount": str(self.entry_slippage_amount),
                "exit_slippage_amount": str(self.exit_slippage_amount),
                "net_r": str(self.net_r),
                "equity_before": str(self.equity_before),
                "equity_after": str(self.equity_after),
                "holding_duration_ms": self.holding_duration_ms,
                "reason_codes": self.reason_codes,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class ReplayEvaluationSource:
    run_id: str
    manifest_id: str
    result_digest: str
    evidence_class: EvidenceClass
    start_ms: int
    end_ms: int
    data_complete: bool

    def __post_init__(self) -> None:
        _require_nonempty(self.run_id, "run_id")
        _require_nonempty(self.manifest_id, "manifest_id")
        _require_sha256(self.result_digest, "result_digest")
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("source timestamps are invalid")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "manifest_id": self.manifest_id,
            "result_digest": self.result_digest,
            "evidence_class": self.evidence_class.value,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "data_complete": self.data_complete,
        }


@dataclass(frozen=True, slots=True)
class EvaluationDatasetManifest:
    sources: tuple[ReplayEvaluationSource, ...]
    trade_ids: tuple[str, ...]
    decision_fact_ids: tuple[str, ...]
    equity_fact_ids: tuple[str, ...]
    start_ms: int
    end_ms: int
    code_revision: str
    data_complete: bool
    gap_refs: tuple[str, ...]
    mixed_evidence_diagnostic: bool
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("sources must not be empty")
        ordered_sources = tuple(
            sorted(
                self.sources,
                key=lambda item: (
                    item.start_ms,
                    item.end_ms,
                    item.run_id,
                    item.manifest_id,
                    item.result_digest,
                ),
            )
        )
        if len({item.run_id for item in ordered_sources}) != len(ordered_sources):
            raise ValueError("sources must not repeat replay run ids")
        object.__setattr__(self, "sources", ordered_sources)
        for field in ("trade_ids", "decision_fact_ids", "equity_fact_ids", "gap_refs"):
            object.__setattr__(self, field, _canonical_strings(getattr(self, field), field))
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("dataset timestamps are invalid")
        _require_nonempty(self.code_revision, "code_revision")
        evidence_classes = {source.evidence_class for source in ordered_sources}
        if len(evidence_classes) > 1 and not self.mixed_evidence_diagnostic:
            raise ValueError("mixed evidence requires explicit diagnostic mode")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def evidence_class(self) -> EvidenceClass | None:
        values = {source.evidence_class for source in self.sources}
        if len(values) == 1:
            return next(iter(values))
        return None

    @property
    def manifest_id(self) -> str:
        return _digest(
            {
                "sources": tuple(item.canonical_payload() for item in self.sources),
                "trade_ids": self.trade_ids,
                "decision_fact_ids": self.decision_fact_ids,
                "equity_fact_ids": self.equity_fact_ids,
                "start_ms": self.start_ms,
                "end_ms": self.end_ms,
                "code_revision": self.code_revision,
                "data_complete": self.data_complete,
                "gap_refs": self.gap_refs,
                "mixed_evidence_diagnostic": self.mixed_evidence_diagnostic,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class EvaluationPolicy:
    policy_version: str = "phase9-v1"
    min_oos_trades: int = 100
    min_oos_days: int = 30
    min_walkforward_windows: int = 3
    min_trades_per_walkforward_window: int = 20
    min_score_bucket_trades: int = 20
    positive_walkforward_fraction: Decimal = Decimal("0.60")
    bootstrap_confidence: Decimal = Decimal("0.95")
    bootstrap_block_days: int = 5
    bootstrap_resamples: int = 2_000
    split_embargo_ms: int = 6 * 60 * 60 * 1000
    no_trade_horizons_ms: tuple[int, ...] = (
        60 * 60 * 1000,
        4 * 60 * 60 * 1000,
    )

    def __post_init__(self) -> None:
        _require_nonempty(self.policy_version, "policy_version")
        for field in (
            "min_oos_trades",
            "min_oos_days",
            "min_walkforward_windows",
            "min_trades_per_walkforward_window",
            "min_score_bucket_trades",
            "bootstrap_block_days",
            "bootstrap_resamples",
        ):
            if getattr(self, field) <= 0:
                raise ValueError(f"{field} must be positive")
        _require_fraction(
            self.positive_walkforward_fraction,
            "positive_walkforward_fraction",
            allow_zero=False,
        )
        _require_fraction(self.bootstrap_confidence, "bootstrap_confidence", allow_zero=False)
        if self.split_embargo_ms < 0:
            raise ValueError("split_embargo_ms must be non-negative")
        horizons = tuple(sorted(set(self.no_trade_horizons_ms)))
        if not horizons or any(value <= 0 for value in horizons):
            raise ValueError("no_trade_horizons_ms values must be positive")
        object.__setattr__(self, "no_trade_horizons_ms", horizons)

    @property
    def policy_id(self) -> str:
        return _digest(
            {
                "policy_version": self.policy_version,
                "min_oos_trades": self.min_oos_trades,
                "min_oos_days": self.min_oos_days,
                "min_walkforward_windows": self.min_walkforward_windows,
                "min_trades_per_walkforward_window": self.min_trades_per_walkforward_window,
                "min_score_bucket_trades": self.min_score_bucket_trades,
                "positive_walkforward_fraction": str(self.positive_walkforward_fraction),
                "bootstrap_confidence": str(self.bootstrap_confidence),
                "bootstrap_block_days": self.bootstrap_block_days,
                "bootstrap_resamples": self.bootstrap_resamples,
                "split_embargo_ms": self.split_embargo_ms,
                "no_trade_horizons_ms": self.no_trade_horizons_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class TimePartition:
    name: SplitName
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("partition timestamps must satisfy 0 <= start < end")

    @property
    def partition_id(self) -> str:
        return _digest(
            {
                "name": self.name.value,
                "start_ms": self.start_ms,
                "end_ms": self.end_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class FrozenSplitManifest:
    dataset_manifest_id: str
    train: TimePartition
    validation: TimePartition
    test: TimePartition
    embargo_ms: int
    policy_id: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty(self.dataset_manifest_id, "dataset_manifest_id")
        _require_nonempty(self.policy_id, "policy_id")
        if self.train.name is not SplitName.TRAIN:
            raise ValueError("train partition must use SplitName.TRAIN")
        if self.validation.name is not SplitName.VALIDATION:
            raise ValueError("validation partition must use SplitName.VALIDATION")
        if self.test.name is not SplitName.TEST:
            raise ValueError("test partition must use SplitName.TEST")
        if not (
            self.train.start_ms < self.train.end_ms <= self.validation.start_ms
            and self.validation.start_ms < self.validation.end_ms <= self.test.start_ms
            and self.test.start_ms < self.test.end_ms
        ):
            raise ValueError("partitions must be chronologically ordered and non-overlapping")
        if self.embargo_ms < 0:
            raise ValueError("embargo_ms must be non-negative")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def split_manifest_id(self) -> str:
        return _digest(
            {
                "dataset_manifest_id": self.dataset_manifest_id,
                "train": self.train.partition_id,
                "validation": self.validation.partition_id,
                "test": self.test.partition_id,
                "embargo_ms": self.embargo_ms,
                "policy_id": self.policy_id,
                "schema_version": self.schema_version,
            }
        )

    @property
    def test_partition_digest(self) -> str:
        return _digest(
            {
                "dataset_manifest_id": self.dataset_manifest_id,
                "test": self.test.partition_id,
                "embargo_ms": self.embargo_ms,
            },
            length=64,
        )


@dataclass(frozen=True, slots=True)
class CandidateDefinition:
    name: str
    strategy_version: str
    risk_version: str
    execution_config_version: str
    code_revision: str
    config_digest: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in (
            "name",
            "strategy_version",
            "risk_version",
            "execution_config_version",
            "code_revision",
        ):
            _require_nonempty(getattr(self, field), field)
        _require_sha256(self.config_digest, "config_digest")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def candidate_id(self) -> str:
        return _digest(
            {
                "name": self.name,
                "strategy_version": self.strategy_version,
                "risk_version": self.risk_version,
                "execution_config_version": self.execution_config_version,
                "code_revision": self.code_revision,
                "config_digest": self.config_digest,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class FrozenCandidateSet:
    candidates: tuple[CandidateDefinition, ...]
    sensitivity_profile_ids: tuple[str, ...]
    policy_id: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("candidates must not be empty")
        ordered = tuple(sorted(self.candidates, key=lambda item: item.candidate_id))
        if len({item.candidate_id for item in ordered}) != len(ordered):
            raise ValueError("candidates must be unique")
        object.__setattr__(self, "candidates", ordered)
        object.__setattr__(
            self,
            "sensitivity_profile_ids",
            _canonical_strings(self.sensitivity_profile_ids, "sensitivity_profile_ids"),
        )
        if not self.sensitivity_profile_ids:
            raise ValueError("sensitivity_profile_ids must not be empty")
        if self.policy_id is not None:
            _require_nonempty(self.policy_id, "policy_id")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def candidate_set_id(self) -> str:
        return _digest(
            {
                "candidate_ids": tuple(item.candidate_id for item in self.candidates),
                "sensitivity_profile_ids": self.sensitivity_profile_ids,
                "policy_id": self.policy_id,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    metric: str
    lower: Decimal
    upper: Decimal
    confidence: Decimal
    resamples: int
    block_days: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty(self.metric, "metric")
        _require_finite(self.lower, "lower")
        _require_finite(self.upper, "upper")
        if self.lower > self.upper:
            raise ValueError("confidence interval bounds must be ordered")
        _require_fraction(self.confidence, "confidence", allow_zero=False)
        if self.resamples <= 0:
            raise ValueError("resamples must be positive")
        if self.block_days <= 0:
            raise ValueError("block_days must be positive")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def interval_id(self) -> str:
        return _digest(
            {
                "metric": self.metric,
                "lower": str(self.lower),
                "upper": str(self.upper),
                "confidence": str(self.confidence),
                "resamples": self.resamples,
                "block_days": self.block_days,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    trade_count: int
    covered_days: int
    gross_pnl: Decimal
    total_fees: Decimal
    funding_cash_pnl: Decimal
    signed_slippage_amount: Decimal
    net_pnl: Decimal
    total_net_r: Decimal
    mean_net_r: Decimal
    median_net_r: Decimal
    win_rate: Decimal
    average_winner_r: Decimal | None
    average_loser_r: Decimal | None
    profit_factor: Decimal | None
    profit_factor_unavailable_reason: str | None
    largest_winner_r: Decimal | None
    largest_loser_r: Decimal | None
    p05_net_r: Decimal | None
    expected_shortfall_5pct: Decimal | None
    median_holding_duration_ms: int | None
    p95_holding_duration_ms: int | None
    realized_closed_trade_max_drawdown_fraction: Decimal | None
    account_equity_max_drawdown_fraction: Decimal | None
    account_drawdown_unavailable_reason: str | None
    max_market_positive_pnl_share: Decimal | None
    max_strategy_positive_pnl_share: Decimal | None
    max_seven_day_positive_pnl_share: Decimal | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.trade_count < 0:
            raise ValueError("trade_count must be non-negative")
        if self.covered_days < 0:
            raise ValueError("covered_days must be non-negative")
        for field in (
            "gross_pnl",
            "funding_cash_pnl",
            "signed_slippage_amount",
            "net_pnl",
            "total_net_r",
            "mean_net_r",
            "median_net_r",
        ):
            _require_finite(getattr(self, field), field)
        _require_nonnegative(self.total_fees, "total_fees")
        _require_fraction(self.win_rate, "win_rate")
        for field in (
            "average_winner_r",
            "average_loser_r",
            "profit_factor",
            "largest_winner_r",
            "largest_loser_r",
            "p05_net_r",
            "expected_shortfall_5pct",
        ):
            value = getattr(self, field)
            if value is not None:
                _require_finite(value, field)
        if self.profit_factor is None:
            if self.profit_factor_unavailable_reason is None:
                raise ValueError(
                    "profit_factor_unavailable_reason is required when profit_factor is unavailable"
                )
            _require_nonempty(
                self.profit_factor_unavailable_reason,
                "profit_factor_unavailable_reason",
            )
        elif self.profit_factor_unavailable_reason is not None:
            raise ValueError("profit_factor_unavailable_reason must be null when available")
        for field in ("median_holding_duration_ms", "p95_holding_duration_ms"):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValueError(f"{field} must be non-negative")
        for field in (
            "realized_closed_trade_max_drawdown_fraction",
            "account_equity_max_drawdown_fraction",
            "max_market_positive_pnl_share",
            "max_strategy_positive_pnl_share",
            "max_seven_day_positive_pnl_share",
        ):
            value = getattr(self, field)
            if value is not None:
                _require_fraction(value, field)
        if self.account_equity_max_drawdown_fraction is None:
            if self.account_drawdown_unavailable_reason is None:
                raise ValueError(
                    "account_drawdown_unavailable_reason is required "
                    "when account drawdown is unavailable"
                )
            _require_nonempty(
                self.account_drawdown_unavailable_reason,
                "account_drawdown_unavailable_reason",
            )
        elif self.account_drawdown_unavailable_reason is not None:
            raise ValueError("account_drawdown_unavailable_reason must be null when available")
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def metrics_id(self) -> str:
        return _digest(
            {
                field: str(value) if isinstance(value, Decimal) else value
                for field, value in (
                    (name, getattr(self, name)) for name in self.__dataclass_fields__
                )
            }
        )


@dataclass(frozen=True, slots=True)
class SliceMetrics:
    slice_kind: str
    slice_key: str
    sample_size: int
    research_ready: bool
    metrics: PerformanceMetrics
    reason_codes: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty(self.slice_kind, "slice_kind")
        _require_nonempty(self.slice_key, "slice_key")
        if self.sample_size < 0:
            raise ValueError("sample_size must be non-negative")
        if self.sample_size != self.metrics.trade_count:
            raise ValueError("sample_size must match metrics.trade_count")
        object.__setattr__(
            self,
            "reason_codes",
            _canonical_strings(self.reason_codes, "reason_codes"),
        )
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def slice_id(self) -> str:
        return _digest(
            {
                "slice_kind": self.slice_kind,
                "slice_key": self.slice_key,
                "sample_size": self.sample_size,
                "research_ready": self.research_ready,
                "metrics_id": self.metrics.metrics_id,
                "reason_codes": self.reason_codes,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class WalkForwardWindowResult:
    split_manifest_id: str
    evaluation_start_ms: int
    evaluation_end_ms: int
    included_trade_ids: tuple[str, ...]
    excluded_trade_ids: tuple[str, ...]
    metrics: PerformanceMetrics
    eligible: bool
    reason_codes: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _require_nonempty(self.split_manifest_id, "split_manifest_id")
        if self.evaluation_start_ms < 0 or self.evaluation_end_ms <= self.evaluation_start_ms:
            raise ValueError("walk-forward evaluation timestamps are invalid")
        object.__setattr__(
            self,
            "included_trade_ids",
            _canonical_strings(self.included_trade_ids, "included_trade_ids"),
        )
        object.__setattr__(
            self,
            "excluded_trade_ids",
            _canonical_strings(self.excluded_trade_ids, "excluded_trade_ids"),
        )
        if set(self.included_trade_ids) & set(self.excluded_trade_ids):
            raise ValueError("included and excluded trade ids must not overlap")
        if self.metrics.trade_count != len(self.included_trade_ids):
            raise ValueError("metrics.trade_count must match included_trade_ids")
        object.__setattr__(
            self,
            "reason_codes",
            _canonical_strings(self.reason_codes, "reason_codes"),
        )
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def result_digest(self) -> str:
        return _digest(
            {
                "split_manifest_id": self.split_manifest_id,
                "evaluation_start_ms": self.evaluation_start_ms,
                "evaluation_end_ms": self.evaluation_end_ms,
                "included_trade_ids": self.included_trade_ids,
                "excluded_trade_ids": self.excluded_trade_ids,
                "metrics_id": self.metrics.metrics_id,
                "eligible": self.eligible,
                "reason_codes": self.reason_codes,
                "schema_version": self.schema_version,
            },
            length=64,
        )


@dataclass(frozen=True, slots=True)
class PromotionGatePreview:
    profit_factor_pass: bool | None
    max_drawdown_pass: bool | None
    market_concentration_pass: bool | None
    seven_day_concentration_pass: bool | None
    closed_trade_count_pass: bool | None
    covered_days_pass: bool | None
    invariant_health_pass: bool | None
    reason_codes: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason_codes",
            _canonical_strings(self.reason_codes, "reason_codes"),
        )
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def preview_only(self) -> bool:
        return True

    @property
    def preview_id(self) -> str:
        return _digest(
            {
                "profit_factor_pass": self.profit_factor_pass,
                "max_drawdown_pass": self.max_drawdown_pass,
                "market_concentration_pass": self.market_concentration_pass,
                "seven_day_concentration_pass": self.seven_day_concentration_pass,
                "closed_trade_count_pass": self.closed_trade_count_pass,
                "covered_days_pass": self.covered_days_pass,
                "invariant_health_pass": self.invariant_health_pass,
                "reason_codes": self.reason_codes,
                "preview_only": True,
                "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    dataset_manifest_id: str
    split_manifest_id: str
    candidate_set_id: str
    policy_id: str
    oos_status: OOSStatus
    train_metrics: PerformanceMetrics
    validation_metrics: PerformanceMetrics
    test_metrics: PerformanceMetrics
    mean_net_r_confidence_interval: ConfidenceInterval | None
    walkforward_results: tuple[WalkForwardWindowResult, ...]
    slice_reports: tuple[SliceMetrics, ...]
    sensitivity_report_ids: tuple[str, ...]
    no_trade_report_ids: tuple[str, ...]
    edge_status: EdgeEvidenceStatus
    promotion_preview: PromotionGatePreview
    included_sample_count: int
    excluded_sample_count: int
    reason_codes: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        for field in (
            "dataset_manifest_id",
            "split_manifest_id",
            "candidate_set_id",
            "policy_id",
        ):
            _require_nonempty(getattr(self, field), field)
        if self.included_sample_count < 0 or self.excluded_sample_count < 0:
            raise ValueError("sample counts must be non-negative")
        object.__setattr__(
            self,
            "walkforward_results",
            tuple(sorted(self.walkforward_results, key=lambda item: item.result_digest)),
        )
        object.__setattr__(
            self,
            "slice_reports",
            tuple(sorted(self.slice_reports, key=lambda item: item.slice_id)),
        )
        for field in ("sensitivity_report_ids", "no_trade_report_ids", "reason_codes"):
            object.__setattr__(self, field, _canonical_strings(getattr(self, field), field))
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")

    @property
    def evaluation_id(self) -> str:
        return _digest(
            {
                "dataset_manifest_id": self.dataset_manifest_id,
                "split_manifest_id": self.split_manifest_id,
                "candidate_set_id": self.candidate_set_id,
                "policy_id": self.policy_id,
                "oos_status": self.oos_status.value,
                "train_metrics_id": self.train_metrics.metrics_id,
                "validation_metrics_id": self.validation_metrics.metrics_id,
                "test_metrics_id": self.test_metrics.metrics_id,
                "confidence_interval_id": (
                    None
                    if self.mean_net_r_confidence_interval is None
                    else self.mean_net_r_confidence_interval.interval_id
                ),
                "walkforward_result_digests": tuple(
                    item.result_digest for item in self.walkforward_results
                ),
                "slice_ids": tuple(item.slice_id for item in self.slice_reports),
                "sensitivity_report_ids": self.sensitivity_report_ids,
                "no_trade_report_ids": self.no_trade_report_ids,
                "edge_status": self.edge_status.value,
                "promotion_preview_id": self.promotion_preview.preview_id,
                "included_sample_count": self.included_sample_count,
                "excluded_sample_count": self.excluded_sample_count,
                "reason_codes": self.reason_codes,
                "schema_version": self.schema_version,
            }
        )

    @property
    def result_digest(self) -> str:
        return _digest({"evaluation_id": self.evaluation_id}, length=64)
