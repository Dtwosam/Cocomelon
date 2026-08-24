from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from collections.abc import Sequence
from decimal import (
    ROUND_CEILING,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    localcontext,
)

from cocomelon.domain.evaluation import ConfidenceInterval, EvaluationPolicy, TradeEvaluationSample

DAY_MS = 86_400_000
ZERO = Decimal("0")
ONE = Decimal("1")
TWO = Decimal("2")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


def _bootstrap_seed(evaluation_manifest_id: str) -> int:
    if not evaluation_manifest_id.strip():
        raise ValueError("evaluation_manifest_id must not be empty")
    seed_bytes = hashlib.sha256(f"{evaluation_manifest_id}:mean_net_r".encode()).digest()[:8]
    return int.from_bytes(seed_bytes, "big")


def _sampled_day_indices(
    *,
    day_count: int,
    block_days: int,
    rng: random.Random,
) -> tuple[int, ...]:
    if day_count <= 0:
        raise ValueError("day_count must be positive")
    if block_days <= 0:
        raise ValueError("block_days must be positive")

    selected: list[int] = []
    while len(selected) < day_count:
        start = rng.randrange(day_count)
        for offset in range(block_days):
            selected.append((start + offset) % day_count)
            if len(selected) == day_count:
                break
    return tuple(selected)


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("bootstrap mean requires at least one value")
    with localcontext(AUTHORITATIVE_CONTEXT):
        return sum(values, ZERO) / Decimal(len(values))


def _nearest_rank(values: Sequence[Decimal], quantile: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile requires at least one value")
    if quantile < ZERO or quantile > ONE:
        raise ValueError("quantile must be in [0, 1]")
    ordered = sorted(values)
    with localcontext(AUTHORITATIVE_CONTEXT):
        raw_rank = quantile * Decimal(len(ordered))
        rank = int(raw_rank.to_integral_value(rounding=ROUND_CEILING))
    rank = min(len(ordered), max(1, rank))
    return ordered[rank - 1]


def mean_net_r_confidence_interval(
    samples: Sequence[TradeEvaluationSample],
    *,
    evaluation_manifest_id: str,
    policy: EvaluationPolicy,
) -> ConfidenceInterval | None:
    ordered = tuple(
        sorted(
            samples,
            key=lambda item: (
                item.closed_at_ms,
                item.opened_at_ms,
                item.trade_id,
            ),
        )
    )
    if len(ordered) < policy.min_oos_trades:
        return None

    grouped: dict[int, list[TradeEvaluationSample]] = defaultdict(list)
    for item in ordered:
        grouped[item.closed_at_ms // DAY_MS].append(item)
    days = tuple(sorted(grouped))
    if len(days) < policy.min_oos_days:
        return None

    rng = random.Random(_bootstrap_seed(evaluation_manifest_id))
    bootstrap_means: list[Decimal] = []
    for _ in range(policy.bootstrap_resamples):
        indices = _sampled_day_indices(
            day_count=len(days),
            block_days=policy.bootstrap_block_days,
            rng=rng,
        )
        resampled_rs: list[Decimal] = []
        for index in indices:
            day = days[index]
            resampled_rs.extend(item.net_r for item in grouped[day])
        bootstrap_means.append(_mean(resampled_rs))

    with localcontext(AUTHORITATIVE_CONTEXT):
        tail = (ONE - policy.bootstrap_confidence) / TWO
        lower_quantile = tail
        upper_quantile = ONE - tail

    return ConfidenceInterval(
        metric="mean_net_r",
        lower=_nearest_rank(bootstrap_means, lower_quantile),
        upper=_nearest_rank(bootstrap_means, upper_quantile),
        confidence=policy.bootstrap_confidence,
        resamples=policy.bootstrap_resamples,
        block_days=policy.bootstrap_block_days,
    )
