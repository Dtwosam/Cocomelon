from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from decimal import Decimal

from cocomelon.domain.evaluation import EvaluationPolicy, SliceMetrics, TradeEvaluationSample
from cocomelon.evaluation.metrics import compute_performance_metrics

HOUR_MS = 3_600_000


def _score_bucket(score: Decimal) -> str:
    lower = min(90, (int(score) // 10) * 10)
    upper = lower + 10
    closing = "]" if lower == 90 else ")"
    return f"[{lower},{upper}{closing}"


def _slice_key_functions() -> tuple[
    tuple[str, Callable[[TradeEvaluationSample], str]],
    ...,
]:
    return (
        ("market", lambda item: item.market.canonical),
        ("lead_strategy", lambda item: item.lead_strategy),
        ("direction", lambda item: item.direction.value),
        ("trend_regime", lambda item: item.trend_regime.value),
        ("volatility_regime", lambda item: item.volatility_regime.value),
        ("utc_hour", lambda item: f"{(item.decision_timestamp_ms // HOUR_MS) % 24:02d}"),
        ("score_bucket", lambda item: _score_bucket(item.score)),
        ("evidence_class", lambda item: item.evidence_class.value),
    )


def evaluate_slices(
    samples: Sequence[TradeEvaluationSample],
    *,
    policy: EvaluationPolicy,
) -> tuple[SliceMetrics, ...]:
    ordered = tuple(
        sorted(
            samples,
            key=lambda item: (
                item.decision_timestamp_ms,
                item.opened_at_ms,
                item.trade_id,
            ),
        )
    )
    reports: list[SliceMetrics] = []
    for slice_kind, key_fn in _slice_key_functions():
        grouped: dict[str, list[TradeEvaluationSample]] = defaultdict(list)
        for item in ordered:
            grouped[key_fn(item)].append(item)

        for slice_key in sorted(grouped):
            values = tuple(grouped[slice_key])
            if slice_kind == "score_bucket" and len(values) < policy.min_score_bucket_trades:
                ready = False
                reasons = ("INSUFFICIENT_SCORE_BUCKET_TRADES",)
            else:
                ready = True
                reasons = ()
            reports.append(
                SliceMetrics(
                    slice_kind=slice_kind,
                    slice_key=slice_key,
                    sample_size=len(values),
                    research_ready=ready,
                    metrics=compute_performance_metrics(values),
                    reason_codes=reasons,
                )
            )

    return tuple(sorted(reports, key=lambda item: (item.slice_kind, item.slice_key)))
