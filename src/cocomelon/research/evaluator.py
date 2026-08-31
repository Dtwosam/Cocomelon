from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT
from cocomelon.research.artifact import VerifiedResearchBatch, verify_research_batch_artifact
from cocomelon.research.attestation import (
    attest_verified_research_batch,
    load_candidate_attested_health,
)
from cocomelon.research.checkpoint_commit import commit_checkpoint_report_and_state
from cocomelon.research.contracts import (
    ResearchCandidateState,
    ResearchCheckpointState,
    TimeInterval,
)
from cocomelon.research.metrics import compute_checkpoint_risk_metrics
from cocomelon.research.observations import load_trade_observations, record_trade_observations
from cocomelon.research.provenance import load_sealed_admitted_batch_provenance
from cocomelon.research.registry import (
    ResearchContaminationError,
    ResearchRegistry,
    ResearchRegistryError,
)
from cocomelon.research.seals import seal_research_batch
from cocomelon.research.sequential import (
    DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
    evaluate_checkpoint,
)

DAY_MS = 86_400_000
TOUCHED_NON_PROMOTIONAL_LABEL = "TOUCHED / NON-PROMOTIONAL"
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ResearchArtifactBatch:
    artifact_root: Path
    batch_id: str
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_root", Path(self.artifact_root))
        for field in ("batch_id", "source_id"):
            value = getattr(self, field)
            if not value.strip():
                raise ValueError(f"{field} must not be empty")


@dataclass(frozen=True, slots=True)
class ResearchBatch:
    """Legacy descriptor retained only for data-model compatibility.

    Checkpoint admission does not accept this type; production checkpoints must
    start from ResearchArtifactBatch so replay evidence is verified internally.
    """

    batch_id: str
    source_id: str
    replay_run_id: str
    interval: TimeInterval

    def __post_init__(self) -> None:
        for field in ("batch_id", "source_id", "replay_run_id"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be empty")


@dataclass(frozen=True, slots=True)
class ResearchBatchSeal:
    """Legacy value object; never authorizes checkpoint admission."""

    batch_id: str
    trade_ids: tuple[str, ...]
    sample_digest: str

    def __post_init__(self) -> None:
        if not self.batch_id.strip():
            raise ValueError("batch_id must not be empty")
        normalized_ids = tuple(sorted(self.trade_ids))
        if any(not trade_id.strip() for trade_id in normalized_ids):
            raise ValueError("sealed trade ids must not be empty")
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("sealed trade ids must be unique")
        object.__setattr__(self, "trade_ids", normalized_ids)
        if (
            len(self.sample_digest) != 64
            or self.sample_digest != self.sample_digest.lower()
            or any(char not in "0123456789abcdef" for char in self.sample_digest)
        ):
            raise ValueError("sample_digest must be a lowercase sha256 digest")


@dataclass(frozen=True, slots=True)
class ResearchCheckpointReport:
    label: str
    candidate_id: str
    family_id: str
    config_digest: str
    code_revision: str
    execution_config_json: str
    risk_config_json: str
    batch_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    closed_trade_count: int
    closed_trade_days: int
    net_pnl: Decimal
    mean_net_r: Decimal | None
    total_fees: Decimal
    funding_cash_pnl: Decimal
    total_slippage_amount: Decimal
    realized_closed_trade_max_drawdown_fraction: Decimal | None
    max_realized_planned_risk_utilization: Decimal | None
    long_count: int
    short_count: int
    market_trade_counts: tuple[tuple[str, int], ...]
    exit_reason_counts: tuple[tuple[str, int], ...]
    checkpoint_state: ResearchCheckpointState
    candidate_state: ResearchCandidateState
    posterior_probability_positive: Decimal | None
    policy_digest: str
    reason_codes: tuple[str, ...]

    def _payload_without_id(self) -> dict[str, object]:
        return {
            "label": self.label,
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "config_digest": self.config_digest,
            "code_revision": self.code_revision,
            "execution_config_json": self.execution_config_json,
            "risk_config_json": self.risk_config_json,
            "batch_ids": self.batch_ids,
            "source_ids": self.source_ids,
            "closed_trade_count": self.closed_trade_count,
            "closed_trade_days": self.closed_trade_days,
            "net_pnl": str(self.net_pnl),
            "mean_net_r": None if self.mean_net_r is None else str(self.mean_net_r),
            "total_fees": str(self.total_fees),
            "funding_cash_pnl": str(self.funding_cash_pnl),
            "total_slippage_amount": str(self.total_slippage_amount),
            "realized_closed_trade_max_drawdown_fraction": (
                None
                if self.realized_closed_trade_max_drawdown_fraction is None
                else str(self.realized_closed_trade_max_drawdown_fraction)
            ),
            "max_realized_planned_risk_utilization": (
                None
                if self.max_realized_planned_risk_utilization is None
                else str(self.max_realized_planned_risk_utilization)
            ),
            "long_count": self.long_count,
            "short_count": self.short_count,
            "market_trade_counts": self.market_trade_counts,
            "exit_reason_counts": self.exit_reason_counts,
            "checkpoint_state": self.checkpoint_state.value,
            "candidate_state": self.candidate_state.value,
            "posterior_probability_positive": (
                None
                if self.posterior_probability_positive is None
                else str(self.posterior_probability_positive)
            ),
            "policy_digest": self.policy_digest,
            "reason_codes": self.reason_codes,
        }

    @property
    def report_id(self) -> str:
        canonical = json.dumps(
            self._payload_without_id(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {"report_id": self.report_id, **self._payload_without_id()}


def _sample_identity_digest(samples: tuple[TradeEvaluationSample, ...]) -> str:
    payload = tuple(sorted((sample.trade_id, sample.sample_id) for sample in samples))
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_research_batch_seal(
    *,
    batch: ResearchBatch,
    samples: tuple[TradeEvaluationSample, ...],
) -> ResearchBatchSeal:
    """Build a deterministic legacy seal value without granting admission authority."""

    if any(sample.replay_run_id != batch.replay_run_id for sample in samples):
        raise ValueError("research batch seal samples must belong to the batch replay run")
    return ResearchBatchSeal(
        batch_id=batch.batch_id,
        trade_ids=tuple(sample.trade_id for sample in samples),
        sample_digest=_sample_identity_digest(samples),
    )


def _observation_from_verified_sample(
    sample: TradeEvaluationSample,
    verified: VerifiedResearchBatch,
    *,
    planned_risk_fraction: Decimal,
) -> dict[str, object]:
    with localcontext(AUTHORITATIVE_CONTEXT):
        fees = sample.entry_fees + sample.exit_fees
        slippage_amount = sample.entry_slippage_amount + sample.exit_slippage_amount
    return {
        "sample_id": sample.sample_id,
        "trade_id": sample.trade_id,
        "batch_id": verified.batch_id,
        "source_id": verified.source_id,
        "replay_run_id": verified.replay_run_id,
        "strategy_decision_id": sample.strategy_decision_id,
        "market": sample.market.canonical,
        "direction": sample.direction.value,
        "decision_timestamp_ms": sample.decision_timestamp_ms,
        "opened_at_ms": sample.opened_at_ms,
        "closed_at_ms": sample.closed_at_ms,
        "score": str(sample.score),
        "lead_strategy": sample.lead_strategy,
        "trend_regime": sample.trend_regime.value,
        "volatility_regime": sample.volatility_regime.value,
        "evidence_class": sample.evidence_class.value,
        "gross_realized_pnl": str(sample.gross_realized_pnl),
        "entry_fees": str(sample.entry_fees),
        "exit_fees": str(sample.exit_fees),
        "funding_cash_pnl": str(sample.funding_cash_pnl),
        "net_pnl": str(sample.net_pnl),
        "entry_slippage_amount": str(sample.entry_slippage_amount),
        "exit_slippage_amount": str(sample.exit_slippage_amount),
        "net_r": str(sample.net_r),
        "equity_before": str(sample.equity_before),
        "equity_after": str(sample.equity_after),
        "planned_risk_fraction": str(planned_risk_fraction),
        "holding_duration_ms": sample.holding_duration_ms,
        "reason_codes": sample.reason_codes,
        "schema_version": sample.schema_version,
        "fees": str(fees),
        "slippage_amount": str(slippage_amount),
    }


def _observation_string(observation: dict[str, object], field: str) -> str:
    value = observation.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ResearchRegistryError(f"stored research observation {field} is invalid")
    return value


def _observation_integer(observation: dict[str, object], field: str) -> int:
    value = observation.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResearchRegistryError(f"stored research observation {field} is invalid")
    return value


def _observation_decimal(observation: dict[str, object], field: str) -> Decimal:
    value = observation.get(field)
    if not isinstance(value, str):
        raise ResearchRegistryError(f"stored research observation {field} is invalid")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ResearchRegistryError(
            f"stored research observation {field} is invalid"
        ) from exc
    if not result.is_finite():
        raise ResearchRegistryError(f"stored research observation {field} is invalid")
    return result


def _observation_reason_codes(observation: dict[str, object]) -> tuple[str, ...]:
    value = observation.get("reason_codes")
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ResearchRegistryError("stored research observation reason_codes is invalid")
    return tuple(value)


def _configured_risk_per_trade(risk_config_json: str) -> Decimal:
    try:
        raw = json.loads(risk_config_json)
    except json.JSONDecodeError as exc:
        raise ResearchRegistryError("candidate risk config is invalid JSON") from exc
    if not isinstance(raw, dict):
        raise ResearchRegistryError("candidate risk config must be an object")
    value = raw.get("risk_per_trade")
    if not isinstance(value, str):
        raise ResearchRegistryError("candidate risk_per_trade must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ResearchRegistryError("candidate risk_per_trade is invalid") from exc
    if not result.is_finite() or result <= ZERO:
        raise ResearchRegistryError("candidate risk_per_trade must be positive")
    return result


def _verify_artifact_batches(
    artifact_batches: tuple[ResearchArtifactBatch, ...],
) -> tuple[VerifiedResearchBatch, ...]:
    if not artifact_batches:
        raise ValueError("at least one authoritative research artifact batch is required")
    batch_ids: set[str] = set()
    replay_ids: set[str] = set()
    verified_batches: list[VerifiedResearchBatch] = []
    for descriptor in artifact_batches:
        if descriptor.batch_id in batch_ids:
            raise ValueError(f"duplicate research batch id: {descriptor.batch_id}")
        batch_ids.add(descriptor.batch_id)
        verified = verify_research_batch_artifact(
            descriptor.artifact_root,
            batch_id=descriptor.batch_id,
            source_id=descriptor.source_id,
        )
        if verified.replay_run_id in replay_ids:
            raise ValueError(f"duplicate research replay run id: {verified.replay_run_id}")
        replay_ids.add(verified.replay_run_id)
        verified_batches.append(verified)
    return tuple(verified_batches)


def evaluate_research_checkpoint(
    *,
    registry: ResearchRegistry,
    candidate_id: str,
    artifact_batches: tuple[ResearchArtifactBatch, ...],
) -> ResearchCheckpointReport:
    candidate = registry.load_candidate(candidate_id)
    configured_risk = _configured_risk_per_trade(candidate.risk_config_json)
    verified_batches = _verify_artifact_batches(artifact_batches)

    try:
        for verified in verified_batches:
            registry.record_batch(
                candidate_id=candidate_id,
                batch_id=verified.batch_id,
                source_id=verified.source_id,
                replay_run_id=verified.replay_run_id,
                interval=verified.interval,
            )
            seal_research_batch(
                registry.connection,
                candidate_id=candidate_id,
                batch_id=verified.batch_id,
                trade_ids=verified.trade_ids,
                sample_digest=verified.sample_digest,
            )
            attest_verified_research_batch(
                registry.connection,
                candidate_id=candidate_id,
                verified=verified,
            )
    except ResearchContaminationError:
        registry.transition_candidate(
            candidate_id,
            ResearchCandidateState.REJECTED_CONTAMINATION,
            reason="v4_source_interval_overlap",
        )
        raise

    incoming_observations: list[dict[str, object]] = []
    for verified in verified_batches:
        planned_by_trade = dict(verified.planned_risk_fractions)
        for sample in verified.samples:
            planned = planned_by_trade.get(sample.trade_id)
            if planned is None:
                raise ResearchRegistryError(
                    "authoritative research artifact lacks planned risk for closed trade"
                )
            incoming_observations.append(
                _observation_from_verified_sample(
                    sample,
                    verified,
                    planned_risk_fraction=planned,
                )
            )
    record_trade_observations(
        registry.connection,
        candidate_id=candidate_id,
        observations=tuple(incoming_observations),
    )
    observations = load_trade_observations(
        registry.connection,
        candidate_id=candidate_id,
    )
    batch_ids, source_ids = load_sealed_admitted_batch_provenance(
        registry.connection,
        candidate_id=candidate_id,
    )
    operational_failure, hard_risk_failure, _ = load_candidate_attested_health(
        registry.connection,
        candidate_id=candidate_id,
    )

    net_pnl_values = tuple(
        _observation_decimal(observation, "net_pnl") for observation in observations
    )
    net_r_values = tuple(
        _observation_decimal(observation, "net_r") for observation in observations
    )
    fee_values = tuple(
        _observation_decimal(observation, "fees") for observation in observations
    )
    funding_values = tuple(
        _observation_decimal(observation, "funding_cash_pnl")
        for observation in observations
    )
    slippage_values = tuple(
        _observation_decimal(observation, "slippage_amount")
        for observation in observations
    )

    with localcontext(AUTHORITATIVE_CONTEXT):
        net_pnl = sum(net_pnl_values, start=ZERO)
        total_net_r = sum(net_r_values, start=ZERO)
        total_fees = sum(fee_values, start=ZERO)
        funding_cash_pnl = sum(funding_values, start=ZERO)
        total_slippage = sum(slippage_values, start=ZERO)
        mean_net_r = (
            None if not observations else total_net_r / Decimal(len(observations))
        )
    closed_days = {
        _observation_integer(observation, "closed_at_ms") // DAY_MS
        for observation in observations
    }
    try:
        risk_metrics = compute_checkpoint_risk_metrics(
            observations,
            configured_risk_per_trade=configured_risk,
        )
    except ValueError as exc:
        raise ResearchRegistryError(str(exc)) from exc

    market_counts = Counter(
        _observation_string(observation, "market") for observation in observations
    )
    exit_reason_counts: Counter[str] = Counter()
    for observation in observations:
        exit_reason_counts.update(_observation_reason_codes(observation))

    checkpoint = evaluate_checkpoint(
        net_r_values=net_r_values,
        closed_trade_days=len(closed_days),
        operational_failure=operational_failure,
        hard_risk_failure=hard_risk_failure,
        policy=DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
    )
    report = ResearchCheckpointReport(
        label=TOUCHED_NON_PROMOTIONAL_LABEL,
        candidate_id=candidate.candidate_id,
        family_id=candidate.family_id,
        config_digest=candidate.config_digest,
        code_revision=candidate.code_revision,
        execution_config_json=candidate.execution_config_json,
        risk_config_json=candidate.risk_config_json,
        batch_ids=batch_ids,
        source_ids=source_ids,
        closed_trade_count=len(observations),
        closed_trade_days=len(closed_days),
        net_pnl=net_pnl,
        mean_net_r=mean_net_r,
        total_fees=total_fees,
        funding_cash_pnl=funding_cash_pnl,
        total_slippage_amount=total_slippage,
        realized_closed_trade_max_drawdown_fraction=(
            risk_metrics.realized_closed_trade_max_drawdown_fraction
        ),
        max_realized_planned_risk_utilization=(
            risk_metrics.max_realized_planned_risk_utilization
        ),
        long_count=sum(
            _observation_string(observation, "direction") == Direction.LONG.value
            for observation in observations
        ),
        short_count=sum(
            _observation_string(observation, "direction") == Direction.SHORT.value
            for observation in observations
        ),
        market_trade_counts=tuple(sorted(market_counts.items())),
        exit_reason_counts=tuple(sorted(exit_reason_counts.items())),
        checkpoint_state=checkpoint.checkpoint_state,
        candidate_state=checkpoint.candidate_state,
        posterior_probability_positive=checkpoint.posterior_probability_positive,
        policy_digest=checkpoint.policy_digest,
        reason_codes=checkpoint.reason_codes,
    )
    commit_checkpoint_report_and_state(
        registry,
        candidate_id=candidate_id,
        state=checkpoint.candidate_state,
        report_id=report.report_id,
        payload=report.to_dict(),
    )
    return report
