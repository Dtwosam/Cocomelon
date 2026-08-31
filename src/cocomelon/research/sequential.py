from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from functools import lru_cache

from cocomelon.research.contracts import (
    ResearchCandidateState,
    ResearchCheckpointState,
)


@dataclass(frozen=True, slots=True)
class SequentialResearchPolicy:
    student_t_nu: int = 5
    mu_prior_mean: float = 0.0
    mu_prior_sd: float = 0.5
    sigma_prior_sd: float = 1.0
    minimum_futility_trades: int = 20
    promising_trade_count: int = 40
    promising_day_count: int = 7
    futility_probability: Decimal = Decimal("0.05")
    promising_probability: Decimal = Decimal("0.80")
    posterior_sample_count: int = 8_192
    sampler_seed: int = 20_260_831
    probability_quantum: Decimal = Decimal("0.000001")

    def __post_init__(self) -> None:
        if self.student_t_nu <= 0:
            raise ValueError("student_t_nu must be positive")
        if self.mu_prior_sd <= 0 or self.sigma_prior_sd <= 0:
            raise ValueError("prior standard deviations must be positive")
        if self.minimum_futility_trades <= 0:
            raise ValueError("minimum_futility_trades must be positive")
        if self.promising_trade_count < self.minimum_futility_trades:
            raise ValueError("promising_trade_count must not precede futility evaluation")
        if self.promising_day_count <= 0:
            raise ValueError("promising_day_count must be positive")
        if not Decimal("0") < self.futility_probability < Decimal("1"):
            raise ValueError("futility_probability must be between zero and one")
        if not Decimal("0") < self.promising_probability < Decimal("1"):
            raise ValueError("promising_probability must be between zero and one")
        if self.futility_probability >= self.promising_probability:
            raise ValueError("futility probability must be below promising probability")
        if self.posterior_sample_count <= 0:
            raise ValueError("posterior_sample_count must be positive")
        if self.probability_quantum <= 0:
            raise ValueError("probability_quantum must be positive")

    @property
    def digest(self) -> str:
        payload = {
            "student_t_nu": self.student_t_nu,
            "mu_prior_mean": self.mu_prior_mean,
            "mu_prior_sd": self.mu_prior_sd,
            "sigma_prior_sd": self.sigma_prior_sd,
            "minimum_futility_trades": self.minimum_futility_trades,
            "promising_trade_count": self.promising_trade_count,
            "promising_day_count": self.promising_day_count,
            "futility_probability": str(self.futility_probability),
            "promising_probability": str(self.promising_probability),
            "posterior_sample_count": self.posterior_sample_count,
            "sampler_seed": self.sampler_seed,
            "probability_quantum": str(self.probability_quantum),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchCheckpoint:
    trade_count: int
    closed_trade_days: int
    posterior_probability_positive: Decimal | None
    checkpoint_state: ResearchCheckpointState
    candidate_state: ResearchCandidateState
    policy_digest: str
    reason_codes: tuple[str, ...]


DEFAULT_SEQUENTIAL_RESEARCH_POLICY = SequentialResearchPolicy()


def _validated_observations(net_r_values: tuple[Decimal, ...]) -> tuple[float, ...]:
    result: list[float] = []
    for value in net_r_values:
        if not value.is_finite():
            raise ValueError("net R observations must be finite")
        result.append(float(value))
    return tuple(result)


@lru_cache(maxsize=16)
def _prior_samples(policy: SequentialResearchPolicy) -> tuple[tuple[float, float], ...]:
    rng = random.Random(policy.sampler_seed)
    samples: list[tuple[float, float]] = []
    for _ in range(policy.posterior_sample_count):
        mu = rng.gauss(policy.mu_prior_mean, policy.mu_prior_sd)
        sigma = abs(rng.gauss(0.0, policy.sigma_prior_sd))
        samples.append((mu, max(sigma, 1e-9)))
    return tuple(samples)


def _student_t_log_likelihood(
    observations: tuple[float, ...],
    *,
    mu: float,
    sigma: float,
    nu: int,
) -> float:
    half_nu_plus_one = (nu + 1.0) / 2.0
    log_normalizer = (
        math.lgamma(half_nu_plus_one)
        - math.lgamma(nu / 2.0)
        - 0.5 * math.log(nu * math.pi)
        - math.log(sigma)
    )
    total = 0.0
    for observation in observations:
        standardized = (observation - mu) / sigma
        total += log_normalizer - half_nu_plus_one * math.log1p(
            (standardized * standardized) / nu
        )
    return total


def posterior_probability_positive(
    net_r_values: tuple[Decimal, ...],
    *,
    policy: SequentialResearchPolicy = DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
) -> Decimal:
    observations = _validated_observations(net_r_values)
    if not observations:
        raise ValueError("at least one net R observation is required")

    weighted_samples: list[tuple[float, float]] = []
    max_log_weight = -math.inf
    for mu, sigma in _prior_samples(policy):
        log_weight = _student_t_log_likelihood(
            observations,
            mu=mu,
            sigma=sigma,
            nu=policy.student_t_nu,
        )
        weighted_samples.append((mu, log_weight))
        max_log_weight = max(max_log_weight, log_weight)

    total_weight = 0.0
    positive_weight = 0.0
    for mu, log_weight in weighted_samples:
        weight = math.exp(log_weight - max_log_weight)
        total_weight += weight
        if mu > 0.0:
            positive_weight += weight

    if total_weight <= 0.0 or not math.isfinite(total_weight):
        raise RuntimeError("posterior normalization failed")
    probability = positive_weight / total_weight
    return Decimal(str(probability)).quantize(
        policy.probability_quantum,
        rounding=ROUND_HALF_EVEN,
    )


def evaluate_checkpoint(
    *,
    net_r_values: tuple[Decimal, ...],
    closed_trade_days: int,
    operational_failure: bool = False,
    hard_risk_failure: bool = False,
    policy: SequentialResearchPolicy = DEFAULT_SEQUENTIAL_RESEARCH_POLICY,
) -> ResearchCheckpoint:
    if closed_trade_days < 0:
        raise ValueError("closed_trade_days must be non-negative")
    if closed_trade_days > len(net_r_values):
        raise ValueError("closed_trade_days cannot exceed closed trade count")
    _validated_observations(net_r_values)

    trade_count = len(net_r_values)
    posterior: Decimal | None = None
    if trade_count < policy.minimum_futility_trades:
        checkpoint_state = ResearchCheckpointState.INSUFFICIENT_TRADES
        economic_candidate_state = ResearchCandidateState.RESEARCHING
    else:
        posterior = posterior_probability_positive(net_r_values, policy=policy)
        if posterior < policy.futility_probability:
            checkpoint_state = ResearchCheckpointState.REJECT_FUTILITY
            economic_candidate_state = ResearchCandidateState.REJECTED_FUTILITY
        elif (
            trade_count >= policy.promising_trade_count
            and closed_trade_days >= policy.promising_day_count
            and posterior >= policy.promising_probability
        ):
            checkpoint_state = ResearchCheckpointState.RESEARCH_PROMISING
            economic_candidate_state = ResearchCandidateState.RESEARCH_PROMISING
        else:
            checkpoint_state = ResearchCheckpointState.CONTINUE
            economic_candidate_state = ResearchCandidateState.RESEARCHING

    reason_codes: list[str] = []
    candidate_state = economic_candidate_state
    if operational_failure:
        reason_codes.append("operational_failure")
        candidate_state = ResearchCandidateState.REJECTED_OPERATIONAL
    if hard_risk_failure:
        reason_codes.append("hard_risk_failure")
        candidate_state = ResearchCandidateState.REJECTED_OPERATIONAL

    return ResearchCheckpoint(
        trade_count=trade_count,
        closed_trade_days=closed_trade_days,
        posterior_probability_positive=posterior,
        checkpoint_state=checkpoint_state,
        candidate_state=candidate_state,
        policy_digest=policy.digest,
        reason_codes=tuple(reason_codes),
    )
