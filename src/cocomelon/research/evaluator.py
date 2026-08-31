from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT
from cocomelon.research.contracts import (
    ResearchCandidateState,
    ResearchCheckpointState,
    TimeInterval,
)
from cocomelon.research.observations import (
    load_trade_observations,
    record_trade_observations,
)
from cocomelon.research.registry import (
    ResearchContaminationError,
    ResearchRegistry,
    ResearchRegistryError,
)
from cocomelon.research.sequential import (
    DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
    SequentialResearchPolicy,
    evaluate_checkpoint,
)

DAY_MS = 86_400_000
TOUCHED_NON_PROMOTIONAL_LABEL = "TOUCHED / NON-PROMOTIONAL"
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ResearchBatch:
    batch_id: str
    source_id: str
    replay_run_id: str
    interval: TimeInterval

    def __post_init__(self) -> None:
        for field in ("batch_id", "source_id", "replay_run_id"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must not be empty")


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


def _validate_batch_set(batches: tuple[ResearchBatch, ...]) -> dict[str, ResearchBatch]:
    if not batches:
        raise ValueError("at least one research batch is required")
    replay_map: dict[str, ResearchBatch] = {}
    batch_ids: set[str] = set()
    for batch in batches:
        if batch.batch_id in batch_ids:
            raise ValueError(f"duplicate research batch id: {batch.batch_id}")
        batch_ids.add(batch.batch_id)
        if batch.replay_run_id in replay_map:
            raise ValueError(f"duplicate research replay run id: {batch.replay_run_id}")
        replay_map[batch.replay_run_id] = batch
    return replay_map


def _validate_samples_against_batches(
    samples: tuple[TradeEvaluationSample, ...],
    replay_map: dict[str, ResearchBatch],
) -> None:
    trade_ids: set[str] = set()
    for sample in samples:
        if sample.trade_id in trade_ids:
            raise ValueError(f"duplicate research trade id: {sample.trade_id}")
        trade_ids.add(sample.trade_id)
        batch = replay_map.get(sample.replay_run_id)
        if batch is None:
            raise ValueError(f"sample is outside research batch set: {sample.trade_id}")
        if (
            sample.decision_timestamp_ms < batch.interval.start_ms
            or sample.closed_at_ms >= batch.interval.end_ms
        ):
            raise ValueError(f"sample is outside research batch interval: {sample.trade_id}")


def _observation_from_sample(
    sample: TradeEvaluationSample,
    batch: ResearchBatch,
) -> dict[str, object]:
    with localcontext(AUTHORITATIVE_CONTEXT):
        fees = sample.entry_fees + sample.exit_fees
        slippage_amount = sample.entry_slippage_amount + sample.exit_slippage_amount
    return {
        "trade_id": sample.trade_id,
        "batch_id": batch.batch_id,
        "source_id": batch.source_id,
        "replay_run_id": sample.replay_run_id,
        "decision_timestamp_ms": sample.decision_timestamp_ms,
        "opened_at_ms": sample.opened_at_ms,
        "closed_at_ms": sample.closed_at_ms,
        "market": sample.market.canonical,
        "direction": sample.direction.value,
        "net_pnl": str(sample.net_pnl),
        "net_r": str(sample.net_r),
        "fees": str(fees),
        "funding_cash_pnl": str(sample.funding_cash_pnl),
        "slippage_amount": str(slippage_amount),
        "reason_codes": sample.reason_codes,
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


def evaluate_research_checkpoint(
    *,
    registry: ResearchRegistry,
    candidate_id: str,
    batches: tuple[ResearchBatch, ...],
    samples: tuple[TradeEvaluationSample, ...],
    operational_failure: bool = False,
    hard_risk_failure: bool = False,
    policy: SequentialResearchPolicy = DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
) -> ResearchCheckpointReport:
    candidate = registry.load_candidate(candidate_id)
    replay_map = _validate_batch_set(batches)

    _validate_samples_against_batches(samples, replay_map)
    try:
        for batch in batches:
            registry.record_batch(
                candidate_id=candidate_id,
                batch_id=batch.batch_id,
                source_id=batch.source_id,
                replay_run_id=batch.replay_run_id,
                interval=batch.interval,
            )
    except ResearchContaminationError:
        registry.transition_candidate(
            candidate_id,
            ResearchCandidateState.REJECTED_CONTAMINATION,
            reason="v4_source_interval_overlap",
        )
        raise

    incoming_observations = tuple(
        _observation_from_sample(sample, replay_map[sample.replay_run_id])
        for sample in samples
    )
    record_trade_observations(
        registry.connection,
        candidate_id=candidate_id,
        observations=incoming_observations,
    )
    observations = load_trade_observations(
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
        policy=policy,
    )
    report = ResearchCheckpointReport(
        label=TOUCHED_NON_PROMOTIONAL_LABEL,
        candidate_id=candidate.candidate_id,
        family_id=candidate.family_id,
        config_digest=candidate.config_digest,
        code_revision=candidate.code_revision,
        execution_config_json=candidate.execution_config_json,
        risk_config_json=candidate.risk_config_json,
        batch_ids=tuple(
            sorted(
                {
                    _observation_string(observation, "batch_id")
                    for observation in observations
                }
            )
        ),
        source_ids=tuple(
            sorted(
                {
                    _observation_string(observation, "source_id")
                    for observation in observations
                }
            )
        ),
        closed_trade_count=len(observations),
        closed_trade_days=len(closed_days),
        net_pnl=net_pnl,
        mean_net_r=mean_net_r,
        total_fees=total_fees,
        funding_cash_pnl=funding_cash_pnl,
        total_slippage_amount=total_slippage,
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
    registry.record_performance_report(
        candidate_id=candidate_id,
        report_id=report.report_id,
        payload=report.to_dict(),
    )
    registry.apply_checkpoint_state(
        candidate_id,
        checkpoint.candidate_state,
        report_id=report.report_id,
    )
    return report
